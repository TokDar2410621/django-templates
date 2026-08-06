"""Custom exceptions for newsletter_engine.

Raised by the service layer (NOT by DRF views directly) so non-DRF callers
(Celery tasks, management commands) can react without importing DRF. The
view layer catches each and maps to the appropriate HTTP response.
"""
from __future__ import annotations

from typing import Any, Optional


class NewsletterError(Exception):
    """Base class for all newsletter_engine domain errors."""


class SegmentDSLError(NewsletterError):
    """Raised when a Segment.filters payload is malformed or references
    unknown ops/fields.

    Attributes
    ----------
    node : Any
        The offending sub-tree (or None when the error is at the root).
    reason : str
        Human-readable explanation.
    """

    def __init__(self, reason: str, *, node: Any = None) -> None:
        self.reason = reason
        self.node = node
        super().__init__(reason)


class SubscriberConflict(NewsletterError):
    """Raised when a subscribe call hits a state we can't reconcile
    automatically (e.g. trying to re-subscribe a hard-bounced address).
    """


class CampaignStateError(NewsletterError):
    """Raised when an action is invalid for the campaign's current status
    (e.g. trying to send a campaign already marked ``sent``).
    """

    def __init__(self, current_status: str, action: str,
                 message: Optional[str] = None) -> None:
        self.current_status = current_status
        self.action = action
        super().__init__(
            message
            or f"Cannot perform '{action}' on a campaign in status '{current_status}'."
        )


class UnsubscribeTokenInvalid(NewsletterError):
    """Raised when an unsubscribe/confirm token is unknown, expired, or
    already consumed (when reuse is forbidden).
    """


class AutomationTriggerError(NewsletterError):
    """Raised when an automation is asked to handle a trigger it doesn't
    support, or when ``trigger_config`` doesn't satisfy the trigger.
    """
