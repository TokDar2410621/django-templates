"""Segment filter DSL — compile a JSON tree to a Django ``Q`` over Subscriber.

The DSL is intentionally small. It covers the 90% of marketing segments
(field equality, has-tag, list membership, recent engagement) without
needing a full query language.

JSON node schema
----------------

Boolean nodes::

    {"op": "and", "children": [<node>, ...]}
    {"op": "or",  "children": [<node>, ...]}
    {"op": "not", "child":    <node>}

Field comparison on the ``Subscriber`` model::

    {"op": "field", "field": <name>, "compare": <op>, "value": <any>}

    Supported fields:  email, name, status, source, locale,
                       consented_marketing, bounce_count, created_at,
                       confirmed_at, last_bounce_at
    Supported compare: eq, neq, in, gt, gte, lt, lte,
                       contains, icontains, isnull

Membership / tagging::

    {"op": "has_tag",  "tag_id": <int>}
    {"op": "in_list",  "list_id": <int>}

Engagement (relative to "now")::

    {"op": "opened_in_last_days",  "campaign_id": <int|null>, "days": <int>}
    {"op": "clicked_in_last_days", "campaign_id": <int|null>, "days": <int>}
    {"op": "no_engagement_for_days", "days": <int>}
        # subscriber has not opened nor clicked any campaign in N days

Time::

    {"op": "subscribed_after",  "date": "YYYY-MM-DD"}
    {"op": "subscribed_before", "date": "YYYY-MM-DD"}

Example
-------

Active subscribers tagged "VIP" who opened any campaign in the last 30 days::

    {
        "op": "and",
        "children": [
            {"op": "field", "field": "status", "compare": "eq", "value": "confirmed"},
            {"op": "has_tag", "tag_id": 5},
            {"op": "opened_in_last_days", "campaign_id": null, "days": 30},
        ]
    }

Errors
------

``SegmentDSLError`` is raised on unknown ops, missing required keys, or
unsupported compare operators. The ``node`` attribute pinpoints the
offending sub-tree for debugging.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone as _tz
from typing import Any

from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from .exceptions import SegmentDSLError

logger = logging.getLogger(__name__)


# Whitelist — never widen casually; new fields require a migration if they're
# not on Subscriber.
ALLOWED_FIELDS: set[str] = {
    "email",
    "name",
    "status",
    "source",
    "locale",
    "consented_marketing",
    "bounce_count",
    "created_at",
    "confirmed_at",
    "last_bounce_at",
}

# Mapping DSL compare -> Django ORM suffix.
COMPARE_OPS: dict[str, str] = {
    "eq":         "exact",
    "neq":        "exact",     # negated in code
    "in":         "in",
    "gt":         "gt",
    "gte":        "gte",
    "lt":         "lt",
    "lte":        "lte",
    "contains":   "contains",
    "icontains":  "icontains",
    "isnull":     "isnull",
}


def compile_to_q(node: Any) -> Q:
    """Convert a DSL tree to a Django Q over Subscriber.

    An empty dict or None compiles to ``Q()`` (i.e. "match all"). This makes
    empty/unset Segment.filters effectively "every subscriber".
    """
    if not node:
        return Q()
    if not isinstance(node, dict):
        raise SegmentDSLError(f"Node must be a dict, got {type(node).__name__}", node=node)

    op = node.get("op")
    if not op:
        raise SegmentDSLError("Missing 'op' key", node=node)

    handler = _OP_HANDLERS.get(op)
    if handler is None:
        raise SegmentDSLError(f"Unknown op: {op!r}", node=node)
    return handler(node)


# ---------------------------------------------------------------------------
# Boolean ops
# ---------------------------------------------------------------------------
def _op_and(node: dict) -> Q:
    children = node.get("children") or []
    if not isinstance(children, list):
        raise SegmentDSLError("'and' requires a list 'children'", node=node)
    q = Q()
    for child in children:
        q &= compile_to_q(child)
    return q


def _op_or(node: dict) -> Q:
    children = node.get("children") or []
    if not isinstance(children, list):
        raise SegmentDSLError("'or' requires a list 'children'", node=node)
    if not children:
        # Empty OR matches nothing (canonically). Use pk__in=[] to be explicit.
        return Q(pk__in=[])
    q = Q(pk__in=[])
    for child in children:
        q |= compile_to_q(child)
    return q


def _op_not(node: dict) -> Q:
    child = node.get("child")
    if child is None:
        raise SegmentDSLError("'not' requires a 'child'", node=node)
    return ~compile_to_q(child)


# ---------------------------------------------------------------------------
# Field comparison
# ---------------------------------------------------------------------------
def _op_field(node: dict) -> Q:
    field = node.get("field")
    compare = node.get("compare")
    value = node.get("value")
    if field not in ALLOWED_FIELDS:
        raise SegmentDSLError(f"Field {field!r} not in allow-list", node=node)
    if compare not in COMPARE_OPS:
        raise SegmentDSLError(f"Compare {compare!r} not supported", node=node)
    lookup = f"{field}__{COMPARE_OPS[compare]}"
    if compare == "in" and not isinstance(value, list):
        raise SegmentDSLError("'in' compare requires a list value", node=node)
    q = Q(**{lookup: value})
    if compare == "neq":
        q = ~q
    return q


# ---------------------------------------------------------------------------
# Tag / list membership
# ---------------------------------------------------------------------------
def _op_has_tag(node: dict) -> Q:
    tag_id = node.get("tag_id")
    if not isinstance(tag_id, int):
        raise SegmentDSLError("'has_tag' requires int 'tag_id'", node=node)
    # Import here to avoid circular import at module load (models.py imports
    # nothing from this file, but the reverse would be circular).
    from .models import SubscriberTag
    sub_q = SubscriberTag.objects.filter(
        subscriber=OuterRef("pk"),
        tag_id=tag_id,
    )
    return Q(Exists(sub_q))


def _op_in_list(node: dict) -> Q:
    list_id = node.get("list_id")
    if not isinstance(list_id, int):
        raise SegmentDSLError("'in_list' requires int 'list_id'", node=node)
    from .models import Membership
    sub_q = Membership.objects.filter(
        subscriber=OuterRef("pk"),
        list_id=list_id,
        status=Membership.STATUS_ACTIVE,
    )
    return Q(Exists(sub_q))


# ---------------------------------------------------------------------------
# Engagement
# ---------------------------------------------------------------------------
def _engagement_q(node: dict, *, field: str) -> Q:
    """Shared compiler for opened_in_last_days / clicked_in_last_days."""
    days = node.get("days")
    if not isinstance(days, int) or days < 0:
        raise SegmentDSLError(f"{node.get('op')!r} requires non-negative int 'days'", node=node)
    threshold = timezone.now() - timedelta(days=days)
    from .models import Delivery
    filters = {f"{field}__gte": threshold}
    cid = node.get("campaign_id")
    if cid is not None:
        if not isinstance(cid, int):
            raise SegmentDSLError("'campaign_id' must be int or null", node=node)
        filters["campaign_id"] = cid
    sub_q = Delivery.objects.filter(subscriber=OuterRef("pk"), **filters)
    return Q(Exists(sub_q))


def _op_opened_in_last_days(node: dict) -> Q:
    return _engagement_q(node, field="last_opened_at")


def _op_clicked_in_last_days(node: dict) -> Q:
    return _engagement_q(node, field="last_clicked_at")


def _op_no_engagement_for_days(node: dict) -> Q:
    days = node.get("days")
    if not isinstance(days, int) or days < 0:
        raise SegmentDSLError("'no_engagement_for_days' requires non-negative 'days'", node=node)
    threshold = timezone.now() - timedelta(days=days)
    from .models import Delivery
    # No delivery with engagement (opened or clicked) more recent than threshold.
    recent = Delivery.objects.filter(
        subscriber=OuterRef("pk"),
    ).filter(
        Q(last_opened_at__gte=threshold) | Q(last_clicked_at__gte=threshold)
    )
    return ~Q(Exists(recent))


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------
def _parse_date(s: Any, node: dict) -> datetime:
    if not isinstance(s, str):
        raise SegmentDSLError("'date' must be ISO-format string YYYY-MM-DD", node=node)
    try:
        return datetime.fromisoformat(s).replace(tzinfo=_tz.utc)
    except ValueError as exc:
        raise SegmentDSLError(f"Invalid date {s!r}: {exc}", node=node) from exc


def _op_subscribed_after(node: dict) -> Q:
    return Q(created_at__gte=_parse_date(node.get("date"), node))


def _op_subscribed_before(node: dict) -> Q:
    return Q(created_at__lt=_parse_date(node.get("date"), node))


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
_OP_HANDLERS: dict[str, Any] = {
    "and":                    _op_and,
    "or":                     _op_or,
    "not":                    _op_not,
    "field":                  _op_field,
    "has_tag":                _op_has_tag,
    "in_list":                _op_in_list,
    "opened_in_last_days":    _op_opened_in_last_days,
    "clicked_in_last_days":   _op_clicked_in_last_days,
    "no_engagement_for_days": _op_no_engagement_for_days,
    "subscribed_after":       _op_subscribed_after,
    "subscribed_before":      _op_subscribed_before,
}
