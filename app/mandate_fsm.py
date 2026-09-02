"""Formal State Machine Enforcement for MandateRecord (Milestone M3 / ADR-005).

Defines the formal finite state machine (FSM) governing MandateRecord lifecycles.
All state mutations on MandateRecord MUST go through transition(). Direct assignment
to record.status is strictly forbidden.

Legal Transitions:
- RESERVED -> ORDER_CREATING
- ORDER_CREATING -> ORDER_CREATED
- ORDER_CREATING -> RESERVED (recoverable failure during Razorpay order creation)
- ORDER_CREATED -> PAYMENT_PENDING
- ORDER_CREATED -> PAYMENT_CAPTURED (terminal capture confirmed by webhook)
- ORDER_CREATED -> PAYMENT_FAILED (webhook reports payment failure)
- ORDER_CREATED -> RELEASED (timeout/release)
- PAYMENT_PENDING -> PAYMENT_CAPTURED (terminal capture confirmed by webhook)
- PAYMENT_PENDING -> PAYMENT_FAILED (webhook reports payment failure)
- PAYMENT_PENDING -> RELEASED (timeout/release)
- PAYMENT_FAILED -> RELEASED (terminal: reservation returned to available budget)
- EXPIRED -> RELEASED (terminal: reservation returned to available budget)

Terminal States (no outgoing transitions):
- PAYMENT_CAPTURED
- RELEASED
"""

from __future__ import annotations

from typing import Final
from sqlalchemy.orm import Session

from app.errors import PolicyMandateStateInvalid, PolicyViolation
from app.models import MandateRecord, MandateStatus

ALLOWED_TRANSITIONS: Final[dict[MandateStatus, set[MandateStatus]]] = {
    MandateStatus.RESERVED: {
        MandateStatus.ORDER_CREATING,
        MandateStatus.RELEASED,
    },
    MandateStatus.ORDER_CREATING: {
        MandateStatus.ORDER_CREATED,
        MandateStatus.RESERVED,
    },
    MandateStatus.ORDER_CREATED: {
        MandateStatus.PAYMENT_PENDING,
        MandateStatus.PAYMENT_CAPTURED,
        MandateStatus.PAYMENT_FAILED,
        MandateStatus.RELEASED,
    },
    MandateStatus.PAYMENT_PENDING: {
        MandateStatus.PAYMENT_CAPTURED,
        MandateStatus.PAYMENT_FAILED,
        MandateStatus.RELEASED,
    },
    MandateStatus.PAYMENT_FAILED: {
        MandateStatus.RELEASED,
    },
    MandateStatus.EXPIRED: {
        MandateStatus.RELEASED,
    },
    MandateStatus.PAYMENT_CAPTURED: set(),  # Terminal
    MandateStatus.RELEASED: set(),          # Terminal
}


class InvalidStateTransition(PolicyMandateStateInvalid):
    """Raised when an illegal mandate state transition is attempted."""

    def __init__(
        self,
        current_status: MandateStatus | str,
        target_status: MandateStatus | str,
        mandate_id: str | None = None,
    ) -> None:
        curr_val = current_status.value if hasattr(current_status, "value") else str(current_status)
        target_val = target_status.value if hasattr(target_status, "value") else str(target_status)
        msg = f"Illegal mandate transition from '{curr_val}' to '{target_val}'"
        if mandate_id:
            msg += f" for mandate '{mandate_id}'"
        super().__init__(
            message=msg,
            details={
                "current_status": curr_val,
                "target_status": target_val,
                "mandate_id": mandate_id,
            },
        )


def can_transition(
    current_status: MandateStatus | str,
    target_status: MandateStatus | str,
) -> bool:
    """Returns True if current_status can legally transition to target_status."""
    curr = MandateStatus(current_status) if isinstance(current_status, str) else current_status
    target = MandateStatus(target_status) if isinstance(target_status, str) else target_status
    return target in ALLOWED_TRANSITIONS.get(curr, set())


def transition(
    record: MandateRecord,
    new_status: MandateStatus | str,
    db: Session | None = None,
) -> MandateRecord:
    """Executes a validated state transition on a MandateRecord.

    Args:
        record: The MandateRecord instance to transition.
        new_status: Target MandateStatus.
        db: Optional SQLAlchemy Session. If provided, changes are flushed to ensure DB synchronization.

    Returns:
        MandateRecord: The updated record.

    Raises:
        InvalidStateTransition: If the attempted transition is not in ALLOWED_TRANSITIONS.
    """
    curr = MandateStatus(record.status) if isinstance(record.status, str) else record.status
    target = MandateStatus(new_status) if isinstance(new_status, str) else new_status

    # Idempotent same-state no-op
    if curr == target:
        return record

    allowed = ALLOWED_TRANSITIONS.get(curr, set())
    if target not in allowed:
        raise InvalidStateTransition(
            current_status=curr,
            target_status=target,
            mandate_id=getattr(record, "mandate_id", None),
        )

    record.status = target

    if db is not None:
        db.flush()

    return record
