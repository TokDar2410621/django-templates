"""Unit tests for the segment DSL compiler (no DB needed for most)."""
from __future__ import annotations

import pytest
from django.db.models import Q

from newsletter_engine.exceptions import SegmentDSLError
from newsletter_engine.segment_dsl import compile_to_q


def test_empty_node_compiles_to_match_all():
    assert compile_to_q({}) == Q()
    assert compile_to_q(None) == Q()


def test_unknown_op_raises():
    with pytest.raises(SegmentDSLError):
        compile_to_q({"op": "no_such_thing"})


def test_field_eq_compiles():
    q = compile_to_q({"op": "field", "field": "status", "compare": "eq", "value": "confirmed"})
    assert q == Q(status__exact="confirmed")


def test_field_neq_compiles_to_negation():
    q = compile_to_q({"op": "field", "field": "status", "compare": "neq", "value": "bounced"})
    # ~Q(status__exact='bounced') == Q.__invert__ — compare by repr to avoid
    # depending on Q internals.
    assert str(q) == str(~Q(status__exact="bounced"))


def test_field_not_in_allowlist_raises():
    with pytest.raises(SegmentDSLError):
        compile_to_q({"op": "field", "field": "password", "compare": "eq", "value": "x"})


def test_in_requires_list_value():
    with pytest.raises(SegmentDSLError):
        compile_to_q({"op": "field", "field": "status", "compare": "in", "value": "not-a-list"})


def test_and_or_not_compose():
    tree = {
        "op": "and",
        "children": [
            {"op": "field", "field": "status", "compare": "eq", "value": "confirmed"},
            {"op": "or", "children": [
                {"op": "field", "field": "locale", "compare": "eq", "value": "fr"},
                {"op": "field", "field": "locale", "compare": "eq", "value": "en"},
            ]},
            {"op": "not", "child": {
                "op": "field", "field": "consented_marketing", "compare": "eq", "value": False,
            }},
        ],
    }
    q = compile_to_q(tree)
    # Smoke check — just ensure it doesn't raise + is a Q object.
    assert isinstance(q, Q)


def test_subscribed_after_compiles():
    q = compile_to_q({"op": "subscribed_after", "date": "2026-01-01"})
    assert isinstance(q, Q)


def test_subscribed_after_bad_date_raises():
    with pytest.raises(SegmentDSLError):
        compile_to_q({"op": "subscribed_after", "date": "not-a-date"})


def test_engagement_days_negative_raises():
    with pytest.raises(SegmentDSLError):
        compile_to_q({"op": "opened_in_last_days", "days": -1})


def test_has_tag_requires_int_id():
    with pytest.raises(SegmentDSLError):
        compile_to_q({"op": "has_tag", "tag_id": "abc"})


def test_in_list_requires_int_id():
    with pytest.raises(SegmentDSLError):
        compile_to_q({"op": "in_list", "list_id": None})
