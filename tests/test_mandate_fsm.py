"""Milestone M3: Tests for formal Mandate Finite State Machine (FSM)."""

from uuid import uuid4
import pytest

from app.mandate_fsm import (
    ALLOWED_TRANSITIONS,
    InvalidStateTransition,
    can_transition,
    transition,
)
from app.models import MandateRecord, MandateStatus


def _create_mock_record(initial_status: MandateStatus = MandateStatus.RESERVED) -> MandateRecord:
    """Helper to instantiate a transient MandateRecord for testing."""
    return MandateRecord(
        mandate_id=str(uuid4()),
        intent_id=f"intent_{uuid4().hex[:8]}",
        merchant_id="merchant_cakehouse_01",
        idempotency_key=f"tx_{uuid4().hex[:8]}",
        order_idempotency_key=f"rec_{uuid4().hex[:8]}",
        authorized_amount_paise=10000,
        cart_hash="hash_placeholder",
        mandate_jwt="dummy_jwt_string",
        status=initial_status,
        reserved_paise=10000,
        captured_paise=0,
    )


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [
        (MandateStatus.RESERVED, MandateStatus.ORDER_CREATING),
        (MandateStatus.ORDER_CREATING, MandateStatus.ORDER_CREATED),
        (MandateStatus.ORDER_CREATING, MandateStatus.RESERVED),
        (MandateStatus.ORDER_CREATING, MandateStatus.RELEASED),
        (MandateStatus.ORDER_CREATED, MandateStatus.PAYMENT_PENDING),
        (MandateStatus.ORDER_CREATED, MandateStatus.PAYMENT_CAPTURED),
        (MandateStatus.ORDER_CREATED, MandateStatus.PAYMENT_FAILED),
        (MandateStatus.ORDER_CREATED, MandateStatus.EXPIRED),
        (MandateStatus.PAYMENT_PENDING, MandateStatus.PAYMENT_CAPTURED),
        (MandateStatus.PAYMENT_PENDING, MandateStatus.PAYMENT_FAILED),
        (MandateStatus.PAYMENT_FAILED, MandateStatus.RELEASED),
        (MandateStatus.EXPIRED, MandateStatus.RELEASED),
    ],
)
def test_all_legal_transitions_succeed(from_status, to_status):
    """Verify that every transition explicitly defined in the architecture succeeds."""
    assert can_transition(from_status, to_status) is True
    record = _create_mock_record(from_status)
    transition(record, to_status)
    assert record.status == to_status


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [
        # Terminal PAYMENT_CAPTURED cannot transition anywhere
        (MandateStatus.PAYMENT_CAPTURED, MandateStatus.RESERVED),
        (MandateStatus.PAYMENT_CAPTURED, MandateStatus.ORDER_CREATING),
        (MandateStatus.PAYMENT_CAPTURED, MandateStatus.ORDER_CREATED),
        (MandateStatus.PAYMENT_CAPTURED, MandateStatus.PAYMENT_PENDING),
        (MandateStatus.PAYMENT_CAPTURED, MandateStatus.PAYMENT_FAILED),
        (MandateStatus.PAYMENT_CAPTURED, MandateStatus.RELEASED),
        (MandateStatus.PAYMENT_CAPTURED, MandateStatus.EXPIRED),
        # Terminal RELEASED cannot transition anywhere
        (MandateStatus.RELEASED, MandateStatus.RESERVED),
        (MandateStatus.RELEASED, MandateStatus.ORDER_CREATING),
        (MandateStatus.RELEASED, MandateStatus.ORDER_CREATED),
        (MandateStatus.RELEASED, MandateStatus.PAYMENT_CAPTURED),
        (MandateStatus.RELEASED, MandateStatus.PAYMENT_PENDING),
        (MandateStatus.RELEASED, MandateStatus.EXPIRED),
        # Removed / illegal transitions to RELEASED
        (MandateStatus.RESERVED, MandateStatus.RELEASED),
        (MandateStatus.ORDER_CREATED, MandateStatus.RELEASED),
        (MandateStatus.PAYMENT_PENDING, MandateStatus.RELEASED),
        # Skipping intermediate steps is forbidden
        (MandateStatus.RESERVED, MandateStatus.ORDER_CREATED),
        (MandateStatus.RESERVED, MandateStatus.PAYMENT_PENDING),
        (MandateStatus.RESERVED, MandateStatus.PAYMENT_CAPTURED),
        (MandateStatus.RESERVED, MandateStatus.PAYMENT_FAILED),
        (MandateStatus.RESERVED, MandateStatus.EXPIRED),
        (MandateStatus.ORDER_CREATING, MandateStatus.PAYMENT_CAPTURED),
        (MandateStatus.ORDER_CREATING, MandateStatus.PAYMENT_PENDING),
        (MandateStatus.ORDER_CREATING, MandateStatus.PAYMENT_FAILED),
        (MandateStatus.ORDER_CREATING, MandateStatus.EXPIRED),
        # Backwards transitions from ORDER_CREATED
        (MandateStatus.ORDER_CREATED, MandateStatus.ORDER_CREATING),
        (MandateStatus.ORDER_CREATED, MandateStatus.RESERVED),
        # Backwards transitions from PAYMENT_PENDING
        (MandateStatus.PAYMENT_PENDING, MandateStatus.ORDER_CREATING),
        (MandateStatus.PAYMENT_PENDING, MandateStatus.ORDER_CREATED),
        (MandateStatus.PAYMENT_PENDING, MandateStatus.RESERVED),
        (MandateStatus.PAYMENT_PENDING, MandateStatus.EXPIRED),
        # Backwards transitions from PAYMENT_FAILED
        (MandateStatus.PAYMENT_FAILED, MandateStatus.ORDER_CREATING),
        (MandateStatus.PAYMENT_FAILED, MandateStatus.ORDER_CREATED),
        (MandateStatus.PAYMENT_FAILED, MandateStatus.PAYMENT_PENDING),
        (MandateStatus.PAYMENT_FAILED, MandateStatus.PAYMENT_CAPTURED),
        (MandateStatus.PAYMENT_FAILED, MandateStatus.RESERVED),
        (MandateStatus.PAYMENT_FAILED, MandateStatus.EXPIRED),
        # Backwards transitions from EXPIRED
        (MandateStatus.EXPIRED, MandateStatus.RESERVED),
        (MandateStatus.EXPIRED, MandateStatus.ORDER_CREATING),
        (MandateStatus.EXPIRED, MandateStatus.ORDER_CREATED),
        (MandateStatus.EXPIRED, MandateStatus.PAYMENT_PENDING),
        (MandateStatus.EXPIRED, MandateStatus.PAYMENT_CAPTURED),
        (MandateStatus.EXPIRED, MandateStatus.PAYMENT_FAILED),
    ],
)
def test_illegal_transitions_raise_policy_violation(from_status, to_status):
    """Verify that any illegal state mutation raises InvalidStateTransition (409 Conflict)."""
    assert can_transition(from_status, to_status) is False
    record = _create_mock_record(from_status)

    with pytest.raises(InvalidStateTransition) as exc_info:
        transition(record, to_status)

    err = exc_info.value
    assert err.code == "POLICY_MANDATE_STATE_INVALID"
    assert err.http_status == 409
    assert f"Illegal mandate transition from '{from_status.value}' to '{to_status.value}'" in err.message
    assert err.details["current_status"] == from_status.value
    assert err.details["target_status"] == to_status.value
    assert err.details["mandate_id"] == record.mandate_id

    # Ensure record status was not mutated
    assert record.status == from_status


def test_idempotent_same_state_transition():
    """Transitioning to the same state is an idempotent no-op."""
    for status in MandateStatus:
        record = _create_mock_record(status)
        transition(record, status)
        assert record.status == status


def test_transition_with_string_status_values():
    """transition accepts string values as well as MandateStatus enums."""
    record = _create_mock_record(MandateStatus.RESERVED)
    transition(record, "ORDER_CREATING")
    assert record.status == MandateStatus.ORDER_CREATING
    transition(record, "ORDER_CREATED")
    assert record.status == MandateStatus.ORDER_CREATED


def test_transition_flushes_db_session(db_session):
    """When db session is passed, transition calls db.flush()."""
    record = _create_mock_record(MandateStatus.RESERVED)
    db_session.add(record)
    db_session.commit()

    transition(record, MandateStatus.ORDER_CREATING, db=db_session)
    # Status should be persisted in session
    refreshed = db_session.query(MandateRecord).filter_by(mandate_id=record.mandate_id).first()
    assert refreshed.status == MandateStatus.ORDER_CREATING
