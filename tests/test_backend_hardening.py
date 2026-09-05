"""Regression test suite for Backend Correctness Hardening Fixes (FIX 1 to FIX 5).

Covers:
FIX 1: Re-quote amount correctness (higher, lower, and unchanged quotes).
FIX 2: authorize_mandate() lock ordering and registration semantics.
FIX 3: Webhook concurrency locking and state re-checks (captured and failed).
FIX 4: release_failed_leg() row locking and duplicate release idempotency.
FIX 5: Reject standalone authorization after PurchasePlan exists, allow when no plan exists.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest

from app.crypto import generate_es256_keypair, issue_cart_jwt, issue_intent_jwt
from app.errors import PolicyViolation
from app.hitl_execution import (
    LegExecutionStatus,
    PlanExecutionStatus,
    execute_plan_leg,
    release_failed_leg,
    revalidate_or_requote_leg,
)
from app.mandate_fsm import transition
from app.merchant import sign_cart
from app.models import (
    CatalogItem,
    IntentRegistry,
    IntentStatus,
    LedgerEntryType,
    MandateRecord,
    MandateStatus,
    PurchasePlan,
)
from app.policy import authorize_mandate, authorize_plan, verify_intent
from app.razorpay_client import RazorpayClient, simulate_payment_captured_webhook
from app.schemas import UserIntentCredential
from app.webhooks import process_payment_webhook


@pytest.fixture
def hardening_keys():
    """Deterministic test keypairs."""
    from app.merchant_keys import get_merchant_private_key, get_merchant_public_key
    u_priv, u_pub = generate_es256_keypair()
    p_priv, p_pub = generate_es256_keypair()

    return {
        "user": {"private_key_pem": u_priv, "public_key_pem": u_pub},
        "merchant_cake": {
            "private_key_pem": get_merchant_private_key("merchant_cakehouse_01"),
            "public_key_pem": get_merchant_public_key("merchant_cakehouse_01"),
        },
        "merchant_sweet": {
            "private_key_pem": get_merchant_private_key("merchant_sweetdelight_02"),
            "public_key_pem": get_merchant_public_key("merchant_sweetdelight_02"),
        },
        "platform": {"private_key_pem": p_priv, "public_key_pem": p_pub},
    }


def _create_test_intent_and_cart(hardening_keys, db_session, price_paise=50000, spend_cap_paise=200000):
    """Helper to create an intent and signed cart for merchant_cakehouse_01."""
    now = datetime.now(timezone.utc)
    intent = UserIntentCredential(
        intent_id=uuid4(),
        user_id="test_buyer_hardening",
        spend_cap_paise=spend_cap_paise,
        currency="INR",
        allowed_categories=["bakery"],
        allowed_merchant_ids=["merchant_cakehouse_01", "merchant_sweetdelight_02"],
        max_transactions=5,
        nonce=f"nonce_{uuid4().hex}",
        not_before=now - timedelta(minutes=5),
        expires_at=now + timedelta(hours=2),
    )
    intent_jwt = issue_intent_jwt(intent, hardening_keys["user"]["private_key_pem"])

    item = CatalogItem(
        merchant_id="merchant_cakehouse_01",
        sku=f"CAKE-{uuid4().hex[:6]}",
        name="Choc Cake Hardening",
        description="Fresh cake",
        category="bakery",
        price_paise=price_paise,
        in_stock=True,
    )
    db_session.add(item)
    db_session.commit()

    cart, cart_jwt = sign_cart(
        merchant_id="merchant_cakehouse_01",
        line_items_req=[{"sku": item.sku, "quantity": 1}],
        merchant_private_key_pem=hardening_keys["merchant_cake"]["private_key_pem"],
        db=db_session,
    )
    return intent, intent_jwt, item, cart, cart_jwt


# =============================================================================
# FIX 1: Re-quote amount correctness
# =============================================================================

def test_fix1_requote_higher_amount_requires_reauth(hardening_keys, db_session):
    """FIX 1a: Fresh quote > authorized amount -> Requires re-authorization."""
    intent, intent_jwt, item, cart, cart_jwt = _create_test_intent_and_cart(
        hardening_keys, db_session, price_paise=50000
    )

    plan_id = uuid4()
    plan, mandates, records = authorize_plan(
        intent_jwt=intent_jwt,
        legs=[{"merchant_id": "merchant_cakehouse_01", "cart_jwt": cart_jwt}],
        user_public_key_pem=hardening_keys["user"]["public_key_pem"],
        platform_private_key_pem=hardening_keys["platform"]["private_key_pem"],
        db=db_session,
        plan_id=plan_id,
        merchant_public_keys={"merchant_cakehouse_01": hardening_keys["merchant_cake"]["public_key_pem"]},
    )
    rec = records[0]
    rec.created_at = datetime.now(timezone.utc) - timedelta(hours=3)

    # Change catalog price up to 60000 paise
    item.price_paise = 60000
    db_session.commit()

    rzp = RazorpayClient(key_id="rzp_test", key_secret="rzp_secret")
    is_valid, fresh_cart, fresh_jwt, msg = revalidate_or_requote_leg(
        mandate_record=rec,
        db=db_session,
        cart_jwt=cart_jwt,
        merchant_private_key_pem=hardening_keys["merchant_cake"]["private_key_pem"],
    )
    assert not is_valid
    assert "re-authorization required" in msg.lower()
    assert fresh_cart.total_paise == 60000

    result = execute_plan_leg(
        mandate_record=rec,
        db=db_session,
        rzp_client=rzp,
        cart_jwt=cart_jwt,
        merchant_private_key_pem=hardening_keys["merchant_cake"]["private_key_pem"],
    )
    assert result.status == LegExecutionStatus.REQUIRES_REAUTH
    assert result.error_code == "PRICE_INCREASE_REQUIRES_REAUTH"
    assert rec.authorized_amount_paise == 50000  # Immutable authorization amount unchanged


def test_fix1_requote_lower_amount_requires_reauth(hardening_keys, db_session):
    """FIX 1b: Fresh quote < authorized amount -> Requires re-authorization (not silent change)."""
    intent, intent_jwt, item, cart, cart_jwt = _create_test_intent_and_cart(
        hardening_keys, db_session, price_paise=50000
    )

    plan_id = uuid4()
    plan, mandates, records = authorize_plan(
        intent_jwt=intent_jwt,
        legs=[{"merchant_id": "merchant_cakehouse_01", "cart_jwt": cart_jwt}],
        user_public_key_pem=hardening_keys["user"]["public_key_pem"],
        platform_private_key_pem=hardening_keys["platform"]["private_key_pem"],
        db=db_session,
        plan_id=plan_id,
        merchant_public_keys={"merchant_cakehouse_01": hardening_keys["merchant_cake"]["public_key_pem"]},
    )
    rec = records[0]
    rec.created_at = datetime.now(timezone.utc) - timedelta(hours=3)

    # Change catalog price down to 40000 paise
    item.price_paise = 40000
    db_session.commit()

    rzp = RazorpayClient(key_id="rzp_test", key_secret="rzp_secret")
    is_valid, fresh_cart, fresh_jwt, msg = revalidate_or_requote_leg(
        mandate_record=rec,
        db=db_session,
        cart_jwt=cart_jwt,
        merchant_private_key_pem=hardening_keys["merchant_cake"]["private_key_pem"],
    )
    assert not is_valid
    assert "re-authorization required" in msg.lower()
    assert fresh_cart.total_paise == 40000

    result = execute_plan_leg(
        mandate_record=rec,
        db=db_session,
        rzp_client=rzp,
        cart_jwt=cart_jwt,
        merchant_private_key_pem=hardening_keys["merchant_cake"]["private_key_pem"],
    )
    assert result.status == LegExecutionStatus.REQUIRES_REAUTH
    assert result.error_code == "PRICE_DECREASE_REQUIRES_REAUTH"
    assert rec.authorized_amount_paise == 50000  # Immutable authorization amount preserved


def test_fix1_requote_equal_amount_proceeds(hardening_keys, db_session):
    """FIX 1c: Fresh quote == authorized amount -> Proceeds with execution."""
    intent, intent_jwt, item, cart, cart_jwt = _create_test_intent_and_cart(
        hardening_keys, db_session, price_paise=50000
    )

    plan_id = uuid4()
    plan, mandates, records = authorize_plan(
        intent_jwt=intent_jwt,
        legs=[{"merchant_id": "merchant_cakehouse_01", "cart_jwt": cart_jwt}],
        user_public_key_pem=hardening_keys["user"]["public_key_pem"],
        platform_private_key_pem=hardening_keys["platform"]["private_key_pem"],
        db=db_session,
        plan_id=plan_id,
        merchant_public_keys={"merchant_cakehouse_01": hardening_keys["merchant_cake"]["public_key_pem"]},
    )
    rec = records[0]
    rec.created_at = datetime.now(timezone.utc) - timedelta(hours=3)
    db_session.commit()

    # Price is unchanged (50000 paise)
    rzp = RazorpayClient(key_id="rzp_test", key_secret="rzp_secret")
    is_valid, fresh_cart, fresh_jwt, msg = revalidate_or_requote_leg(
        mandate_record=rec,
        db=db_session,
        cart_jwt=cart_jwt,
        merchant_private_key_pem=hardening_keys["merchant_cake"]["private_key_pem"],
    )
    assert is_valid
    assert fresh_cart is not None
    assert fresh_cart.total_paise == 50000

    result = execute_plan_leg(
        mandate_record=rec,
        db=db_session,
        cart_jwt=cart_jwt,
        merchant_private_key_pem=hardening_keys["merchant_cake"]["private_key_pem"],
    )
    assert result.status == LegExecutionStatus.ORDER_CREATED
    assert result.razorpay_order_id is not None
    assert rec.status == MandateStatus.ORDER_CREATED
    assert rec.authorized_amount_paise == 50000


# =============================================================================
# FIX 2: authorize_mandate() lock ordering
# =============================================================================

def test_fix2_authorize_mandate_registers_and_enforces_under_lock(hardening_keys, db_session):
    """FIX 2: First-time intent registration and limit enforcement under row lock."""
    now = datetime.now(timezone.utc)
    intent = UserIntentCredential(
        intent_id=uuid4(),
        user_id="test_buyer_lock_ordering",
        spend_cap_paise=100000,
        currency="INR",
        allowed_categories=["bakery"],
        allowed_merchant_ids=["merchant_cakehouse_01"],
        max_transactions=1,
        nonce=f"nonce_{uuid4().hex}",
        not_before=now - timedelta(minutes=5),
        expires_at=now + timedelta(hours=2),
    )
    intent_jwt = issue_intent_jwt(intent, hardening_keys["user"]["private_key_pem"])

    item = CatalogItem(
        merchant_id="merchant_cakehouse_01",
        sku=f"CAKE-{uuid4().hex[:6]}",
        name="Choc Cake Lock",
        description="Fresh cake",
        category="bakery",
        price_paise=50000,
        in_stock=True,
    )
    db_session.add(item)
    db_session.commit()

    cart, cart_jwt = sign_cart(
        merchant_id="merchant_cakehouse_01",
        line_items_req=[{"sku": item.sku, "quantity": 1}],
        merchant_private_key_pem=hardening_keys["merchant_cake"]["private_key_pem"],
        db=db_session,
    )

    # IntentRegistry does not have this intent yet
    intent_id_str = str(intent.intent_id)
    assert db_session.query(IntentRegistry).filter_by(intent_id=intent_id_str).first() is None

    # First authorization automatically registers intent and issues mandate
    mandate, mandate_jwt, record = authorize_mandate(
        intent_jwt=intent_jwt,
        cart_jwt=cart_jwt,
        idempotency_key="tx_lock_order_1",
        user_public_key_pem=hardening_keys["user"]["public_key_pem"],
        merchant_public_key_pem=hardening_keys["merchant_cake"]["public_key_pem"],
        platform_private_key_pem=hardening_keys["platform"]["private_key_pem"],
        db=db_session,
    )
    db_session.commit()

    intent_row = db_session.query(IntentRegistry).filter_by(intent_id=intent_id_str).one()
    assert intent_row.transactions_consumed == 1
    assert intent_row.reserved_paise == 50000


# =============================================================================
# FIX 3: Webhook concurrency locking and state re-checks
# =============================================================================

def test_fix3_webhook_payment_captured_and_deduplication(hardening_keys, db_session):
    """FIX 3: payment.captured acquires lock, verifies state, and deduplicates cleanly."""
    intent, intent_jwt, item, cart, cart_jwt = _create_test_intent_and_cart(
        hardening_keys, db_session, price_paise=50000
    )

    mandate, mandate_jwt, record = authorize_mandate(
        intent_jwt=intent_jwt,
        cart_jwt=cart_jwt,
        idempotency_key="tx_wh_hardening_01",
        user_public_key_pem=hardening_keys["user"]["public_key_pem"],
        merchant_public_key_pem=hardening_keys["merchant_cake"]["public_key_pem"],
        platform_private_key_pem=hardening_keys["platform"]["private_key_pem"],
        db=db_session,
    )
    transition(record, MandateStatus.ORDER_CREATING, db_session)
    record.razorpay_order_id = "order_wh_hardening_01"
    transition(record, MandateStatus.ORDER_CREATED, db_session)
    db_session.commit()

    raw_body, signature = simulate_payment_captured_webhook(
        razorpay_order_id="order_wh_hardening_01",
        amount_paise=50000,
        event_id="evt_hardening_cap_01",
        webhook_secret="whsec_demo_secret",
    )

    # First delivery: Captures payment
    res1 = process_payment_webhook(
        raw_body=raw_body,
        signature=signature,
        db=db_session,
        webhook_secret="whsec_demo_secret",
        platform_private_key_pem=hardening_keys["platform"]["private_key_pem"],
    )
    assert res1["status"] == "PAYMENT_CAPTURED"
    assert res1.get("deduplicated") is not True

    # Reload under test
    intent_row = db_session.query(IntentRegistry).filter_by(intent_id=str(intent.intent_id)).one()
    assert intent_row.captured_paise == 50000
    assert intent_row.reserved_paise == 0

    # Second delivery: Re-check under lock deduplicates
    res2 = process_payment_webhook(
        raw_body=raw_body,
        signature=signature,
        db=db_session,
        webhook_secret="whsec_demo_secret",
        platform_private_key_pem=hardening_keys["platform"]["private_key_pem"],
    )
    assert res2.get("deduplicated") is True
    assert intent_row.captured_paise == 50000  # No double accounting


def test_fix3_webhook_payment_failed_releases_reservation(hardening_keys, db_session):
    """FIX 3: payment.failed locks row, transitions to PAYMENT_FAILED, and releases reserved_paise."""
    import hmac
    import hashlib
    import json

    intent, intent_jwt, item, cart, cart_jwt = _create_test_intent_and_cart(
        hardening_keys, db_session, price_paise=50000
    )

    mandate, mandate_jwt, record = authorize_mandate(
        intent_jwt=intent_jwt,
        cart_jwt=cart_jwt,
        idempotency_key="tx_wh_fail_01",
        user_public_key_pem=hardening_keys["user"]["public_key_pem"],
        merchant_public_key_pem=hardening_keys["merchant_cake"]["public_key_pem"],
        platform_private_key_pem=hardening_keys["platform"]["private_key_pem"],
        db=db_session,
    )
    transition(record, MandateStatus.ORDER_CREATING, db_session)
    record.razorpay_order_id = "order_wh_fail_01"
    transition(record, MandateStatus.ORDER_CREATED, db_session)
    db_session.commit()

    webhook_secret = "whsec_demo_secret"
    payload_dict = {
        "entity": "event",
        "event": "payment.failed",
        "event_id": "evt_hardening_fail_01",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_fail_123",
                    "order_id": "order_wh_fail_01",
                    "amount": 50000,
                    "status": "failed",
                }
            }
        },
    }
    raw_body = json.dumps(payload_dict).encode("utf-8")
    signature = hmac.new(webhook_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()

    # First delivery: Fails mandate and restores reservation
    res1 = process_payment_webhook(
        raw_body=raw_body,
        signature=signature,
        db=db_session,
        webhook_secret=webhook_secret,
        platform_private_key_pem=hardening_keys["platform"]["private_key_pem"],
    )
    assert res1["status"] == "PAYMENT_FAILED"

    intent_row = db_session.query(IntentRegistry).filter_by(intent_id=str(intent.intent_id)).one()
    assert intent_row.reserved_paise == 0
    assert record.status == MandateStatus.PAYMENT_FAILED

    # Second delivery: Deduplicates under lock
    res2 = process_payment_webhook(
        raw_body=raw_body,
        signature=signature,
        db=db_session,
        webhook_secret=webhook_secret,
        platform_private_key_pem=hardening_keys["platform"]["private_key_pem"],
    )
    assert res2.get("deduplicated") is True
    assert intent_row.reserved_paise == 0


def test_fix3_webhook_payment_failed_ignored_if_already_captured(hardening_keys, db_session):
    """FIX 3: payment.failed arriving after payment.captured is ignored under lock."""
    import hmac
    import hashlib
    import json

    intent, intent_jwt, item, cart, cart_jwt = _create_test_intent_and_cart(
        hardening_keys, db_session, price_paise=50000
    )

    mandate, mandate_jwt, record = authorize_mandate(
        intent_jwt=intent_jwt,
        cart_jwt=cart_jwt,
        idempotency_key="tx_wh_cap_then_fail",
        user_public_key_pem=hardening_keys["user"]["public_key_pem"],
        merchant_public_key_pem=hardening_keys["merchant_cake"]["public_key_pem"],
        platform_private_key_pem=hardening_keys["platform"]["private_key_pem"],
        db=db_session,
    )
    transition(record, MandateStatus.ORDER_CREATING, db_session)
    record.razorpay_order_id = "order_wh_cap_then_fail"
    transition(record, MandateStatus.ORDER_CREATED, db_session)
    db_session.commit()

    webhook_secret = "whsec_demo_secret"
    raw_cap, sig_cap = simulate_payment_captured_webhook(
        razorpay_order_id="order_wh_cap_then_fail",
        amount_paise=50000,
        event_id="evt_cap_first",
        webhook_secret=webhook_secret,
    )
    process_payment_webhook(
        raw_body=raw_cap,
        signature=sig_cap,
        db=db_session,
        webhook_secret=webhook_secret,
        platform_private_key_pem=hardening_keys["platform"]["private_key_pem"],
    )
    assert record.status == MandateStatus.PAYMENT_CAPTURED

    # Now simulate payment.failed event for the same order
    fail_dict = {
        "entity": "event",
        "event": "payment.failed",
        "event_id": "evt_fail_second",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_fail_late",
                    "order_id": "order_wh_cap_then_fail",
                    "amount": 50000,
                    "status": "failed",
                }
            }
        },
    }
    raw_fail = json.dumps(fail_dict).encode("utf-8")
    sig_fail = hmac.new(webhook_secret.encode("utf-8"), raw_fail, hashlib.sha256).hexdigest()

    res = process_payment_webhook(
        raw_body=raw_fail,
        signature=sig_fail,
        db=db_session,
        webhook_secret=webhook_secret,
        platform_private_key_pem=hardening_keys["platform"]["private_key_pem"],
    )
    assert res.get("status") == "IGNORED_ALREADY_CAPTURED"
    assert record.status == MandateStatus.PAYMENT_CAPTURED


# =============================================================================
# FIX 4: release_failed_leg() locking and idempotency
# =============================================================================

def test_fix4_release_failed_leg_locking_and_duplicate_safety(hardening_keys, db_session):
    """FIX 4: release_failed_leg releases reservation under row lock and is duplicate-safe."""
    intent, intent_jwt, item, cart, cart_jwt = _create_test_intent_and_cart(
        hardening_keys, db_session, price_paise=50000
    )

    plan_id = uuid4()
    plan, mandates, records = authorize_plan(
        intent_jwt=intent_jwt,
        legs=[{"merchant_id": "merchant_cakehouse_01", "cart_jwt": cart_jwt}],
        user_public_key_pem=hardening_keys["user"]["public_key_pem"],
        platform_private_key_pem=hardening_keys["platform"]["private_key_pem"],
        db=db_session,
        plan_id=plan_id,
        merchant_public_keys={"merchant_cakehouse_01": hardening_keys["merchant_cake"]["public_key_pem"]},
    )
    rec = records[0]

    intent_row = db_session.query(IntentRegistry).filter_by(intent_id=str(intent.intent_id)).one()
    assert intent_row.reserved_paise == 50000

    # 1. First release succeeds
    release_failed_leg(rec, db=db_session, reason="Test leg failure")
    assert rec.status == MandateStatus.RELEASED
    assert intent_row.reserved_paise == 0

    # 2. Duplicate release call is an idempotent no-op (does not double-decrement or error)
    release_failed_leg(rec, db=db_session, reason="Duplicate call")
    assert rec.status == MandateStatus.RELEASED
    assert intent_row.reserved_paise == 0


def test_fix4_release_failed_leg_preserves_captured_payments(hardening_keys, db_session):
    """FIX 4: release_failed_leg does not touch captured payments."""
    intent, intent_jwt, item, cart, cart_jwt = _create_test_intent_and_cart(
        hardening_keys, db_session, price_paise=50000
    )

    plan_id = uuid4()
    plan, mandates, records = authorize_plan(
        intent_jwt=intent_jwt,
        legs=[{"merchant_id": "merchant_cakehouse_01", "cart_jwt": cart_jwt}],
        user_public_key_pem=hardening_keys["user"]["public_key_pem"],
        platform_private_key_pem=hardening_keys["platform"]["private_key_pem"],
        db=db_session,
        plan_id=plan_id,
        merchant_public_keys={"merchant_cakehouse_01": hardening_keys["merchant_cake"]["public_key_pem"]},
    )
    rec = records[0]
    rec.status = MandateStatus.PAYMENT_CAPTURED
    db_session.commit()

    res = release_failed_leg(rec, db=db_session, reason="Attempt invalid release")
    assert res.status == LegExecutionStatus.CAPTURED
    assert rec.status == MandateStatus.PAYMENT_CAPTURED


# =============================================================================
# FIX 5: Prevent standalone authorization after PurchasePlan exists
# =============================================================================

def test_fix5_standalone_authorize_rejected_when_plan_exists(hardening_keys, db_session):
    """FIX 5: Standalone authorize_mandate() rejected with POLICY_PLAN_EXISTS_FOR_INTENT when PurchasePlan exists."""
    intent, intent_jwt, item, cart, cart_jwt = _create_test_intent_and_cart(
        hardening_keys, db_session, price_paise=50000
    )

    plan_id = uuid4()
    plan, mandates, records = authorize_plan(
        intent_jwt=intent_jwt,
        legs=[{"merchant_id": "merchant_cakehouse_01", "cart_jwt": cart_jwt}],
        user_public_key_pem=hardening_keys["user"]["public_key_pem"],
        platform_private_key_pem=hardening_keys["platform"]["private_key_pem"],
        db=db_session,
        plan_id=plan_id,
        merchant_public_keys={"merchant_cakehouse_01": hardening_keys["merchant_cake"]["public_key_pem"]},
    )

    # Attempting standalone authorize_mandate() on the same intent MUST be rejected
    with pytest.raises(PolicyViolation) as exc_info:
        authorize_mandate(
            intent_jwt=intent_jwt,
            cart_jwt=cart_jwt,
            idempotency_key="tx_standalone_after_plan",
            user_public_key_pem=hardening_keys["user"]["public_key_pem"],
            merchant_public_key_pem=hardening_keys["merchant_cake"]["public_key_pem"],
            platform_private_key_pem=hardening_keys["platform"]["private_key_pem"],
            db=db_session,
        )

    assert exc_info.value.code == "POLICY_PLAN_EXISTS_FOR_INTENT"
    assert "already exists for intent" in str(exc_info.value)


def test_fix5_standalone_authorize_allowed_when_no_plan_exists(hardening_keys, db_session):
    """FIX 5: Standalone authorize_mandate() succeeds normally when NO PurchasePlan exists."""
    intent, intent_jwt, item, cart, cart_jwt = _create_test_intent_and_cart(
        hardening_keys, db_session, price_paise=50000
    )

    # Verify no PurchasePlan exists
    intent_id_str = str(intent.intent_id)
    assert db_session.query(PurchasePlan).filter_by(intent_id=intent_id_str).first() is None

    # Standalone authorization must succeed
    mandate, mandate_jwt, record = authorize_mandate(
        intent_jwt=intent_jwt,
        cart_jwt=cart_jwt,
        idempotency_key="tx_standalone_allowed",
        user_public_key_pem=hardening_keys["user"]["public_key_pem"],
        merchant_public_key_pem=hardening_keys["merchant_cake"]["public_key_pem"],
        platform_private_key_pem=hardening_keys["platform"]["private_key_pem"],
        db=db_session,
    )
    assert record.mandate_id is not None
    assert record.status == MandateStatus.RESERVED
    assert record.authorized_amount_paise == 50000


# =============================================================================
# FINAL CHECK: execute_plan_leg() fails closed if intent expires_at has passed
# =============================================================================

def test_execute_plan_leg_fails_closed_when_intent_expires_at_passed(hardening_keys, db_session):
    """FINAL CHECK: A mandate MUST NOT execute after authoritative IntentRegistry.expires_at has passed,
    even if IntentRegistry.status has not yet transitioned to EXPIRED."""
    intent, intent_jwt, item, cart, cart_jwt = _create_test_intent_and_cart(
        hardening_keys, db_session, price_paise=50000
    )

    plan_id = uuid4()
    plan, mandates, records = authorize_plan(
        intent_jwt=intent_jwt,
        legs=[{"merchant_id": "merchant_cakehouse_01", "cart_jwt": cart_jwt}],
        user_public_key_pem=hardening_keys["user"]["public_key_pem"],
        platform_private_key_pem=hardening_keys["platform"]["private_key_pem"],
        db=db_session,
        plan_id=plan_id,
        merchant_public_keys={"merchant_cakehouse_01": hardening_keys["merchant_cake"]["public_key_pem"]},
    )
    rec = records[0]
    assert rec.status == MandateStatus.RESERVED

    # Retrieve authoritative IntentRegistry and simulate time passing beyond expires_at
    # while leaving status as ACTIVE (un-transitioned)
    intent_reg = db_session.query(IntentRegistry).filter_by(intent_id=rec.intent_id).first()
    assert intent_reg.status == IntentStatus.ACTIVE
    intent_reg.expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)
    db_session.commit()

    # Attempt leg execution after expires_at has passed
    rzp = RazorpayClient(key_id="rzp_test", key_secret="rzp_secret")
    result = execute_plan_leg(
        mandate_record=rec,
        db=db_session,
        rzp_client=rzp,
        cart_jwt=cart_jwt,
        merchant_private_key_pem=hardening_keys["merchant_cake"]["private_key_pem"],
    )

    # Invariant: Must fail closed, release reservation, and report POLICY_INTENT_EXPIRED
    assert result.status == LegExecutionStatus.RELEASED
    assert result.error_code == "POLICY_INTENT_EXPIRED"
    assert result.released_reservation_paise == 50000
    assert rec.status == MandateStatus.RELEASED
    assert rec.reserved_paise == 0

    # Ensure no Razorpay order was created
    assert rec.razorpay_order_id is None

