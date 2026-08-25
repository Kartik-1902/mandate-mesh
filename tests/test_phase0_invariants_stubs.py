"""Phase 0: Invariant test stubs freezing semantics for Phase 2 implementation."""

import pytest
from app.schemas import PaymentMandate


def test_mandate_sign_has_no_status_field():
    """PaymentMandate JWT claims dict must NOT contain 'status' or 'razorpay_order_id'."""
    assert "status" not in PaymentMandate.model_fields
    assert "razorpay_order_id" not in PaymentMandate.model_fields


@pytest.mark.xfail(reason="Phase 2 policy engine not implemented yet", strict=True)
def test_policy_over_budget_blocked():
    """Attack 1: cart.total_paise > available_paise raises POLICY_SPEND_CAP_EXCEEDED."""
    from app.policy import authorize_mandate  # noqa: F401
    raise NotImplementedError


@pytest.mark.xfail(reason="Phase 2 policy engine not implemented yet", strict=True)
def test_policy_nonce_is_checked_per_intent_registration():
    """An intent JWT is verified and inserted to IntentRegistry."""
    from app.policy import verify_intent  # noqa: F401
    raise NotImplementedError


@pytest.mark.xfail(reason="Phase 2 policy engine not implemented yet", strict=True)
def test_same_transaction_identity_is_replay():
    """Same intent_jwt and same idempotency_key submitted twice returns 409."""
    from app.policy import authorize_mandate  # noqa: F401
    raise NotImplementedError


@pytest.mark.xfail(reason="Phase 2 ledger engine not implemented yet", strict=True)
def test_ledger_chain_valid_after_happy_path():
    """After a complete intent->mandate->capture flow, verify_chain() returns (True, None)."""
    from app.ledger import verify_chain  # noqa: F401
    raise NotImplementedError
