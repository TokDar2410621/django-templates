"""Service layer for newsletter_engine.

Imported as ``from newsletter_engine.services import subscribe, send_campaign, ...``.
The split into submodules keeps each concern focused; this ``__init__`` re-
exports the most commonly used entry points for callers who don't want to
remember which submodule owns which function.
"""
from .automations import (
    enroll_subscriber,
    handle_trigger,
    process_due_enrollments,
    tick_automation,
)
from .campaigns import (
    cancel_campaign,
    compute_campaign_stats,
    create_campaign,
    send_campaign,
)
from .segments import (
    cache_segment_count,
    evaluate_segment,
)
from .subscribers import (
    add_to_list,
    confirm_subscriber,
    mark_bounced,
    remove_from_list,
    subscribe,
    tag_subscriber,
    unsubscribe,
    untag_subscriber,
)
from .tracking import (
    record_click,
    record_open,
    rewrite_html_for_tracking,
)

__all__ = [
    # subscribers
    "subscribe",
    "confirm_subscriber",
    "unsubscribe",
    "mark_bounced",
    "add_to_list",
    "remove_from_list",
    "tag_subscriber",
    "untag_subscriber",
    # segments
    "evaluate_segment",
    "cache_segment_count",
    # campaigns
    "create_campaign",
    "send_campaign",
    "cancel_campaign",
    "compute_campaign_stats",
    # automations
    "enroll_subscriber",
    "tick_automation",
    "process_due_enrollments",
    "handle_trigger",
    # tracking
    "record_open",
    "record_click",
    "rewrite_html_for_tracking",
]
