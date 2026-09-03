"""Milestone M8: Mixed-Merchant HITL and Partial-Failure Handling Integration Tests (ADR-013).

Covers:
1. multi-leg plan approved successfully
2. HITL rejection of one leg
3. quote expires while waiting for HITL
4. expired quote triggers deterministic re-quotation
5. re-quoted amount unchanged → execution proceeds
6. re-quoted amount changed → policy/HITL path required
7. merchant becomes unavailable after deliberation
8. one leg captured + another failed
9. one leg captured + another pending
10. failed-leg reservation released while successful-leg capture remains intact
11. PurchasePlan becomes PARTIAL_COMPLETE
12. fully captured plan becomes the correct completed state
13. all legs failed produces the correct unsuccessful plan state
14. explicit successful/failed/pending item reporting
15. duplicate HITL approval does not execute twice
16. duplicate leg execution is idempotent
17. captured leg is never released as a consequence of another leg failing
18. audit ledger contains the relevant plan/leg outcomes
19. legacy single-mandate flow remains unchanged
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
import pytest

from app.crypto import (
    generate_es256_keypair,
    issue_cart_jwt,
    issue_intent_jwt,
)
from app.hitl_execution import (
    LegExecutionStatus,
    PlanExecutionStatus,
    execute_plan_leg,
    execute_purchase_plan,
    get_plan_execution_report,
    release_failed_leg,
    revalidate_or_requote_leg,
    sync_purchase_plan_status,
)
from app.merchant import seed_catalog, sign_cart
from app.models import (
    AuditLedgerEntry,
    CatalogItem,
    IntentRegistry,
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
def keys():
    """Keypairs for user, platform, and multiple merchants."""
    u_priv, u_pub = generate_es256_keypair()
    m1_priv, m1_pub = generate_es256_keypair()
    m2_priv, m2_pub = generate_es256_keypair()
    p_priv, p_pub = generate_es256_keypair()

    return {
        "user": {"private_key_pem": u_priv, "public_key_pem": u_pub},
        "merchant_cake": {"private_key_pem": m1_priv, "public_key_pem": m1_pub},
        "merchant_sweet": {"private_key_pem": m2_priv, "public_key_pem": m2_pub},
        "platform": {"private_key_pem": p_priv, "public_key_pem": p_pub},
    }


def setup_multi_leg_plan(keys, db, spend_cap_paise=300000, price1=50000, price2=60000):
    """Helper creating an authorized 2-leg PurchasePlan."""
    now = datetime.now(timezone.utc)
    intent = UserIntentCredential(
        intent_id=uuid4(),
        user_id="test_buyer_hitl",
        spend_cap_paise=spend_cap_paise,
        currency="INR",
        allowed_categories=["bakery", "gifting"],
        allowed_merchant_ids=["merchant_cakehouse_01", "merchant_sweetdelight_02"],
        max_transactions=5,
        nonce=f"nonce_{uuid4().hex}",
        not_before=now - timedelta(minutes=5),
        expires_at=now + timedelta(hours=2),
    )
    intent_jwt = issue_intent_jwt(intent, keys["user"]["private_key_pem"])
    verify_intent(intent_jwt, keys["user"]["public_key_pem"], db)

    # Seed catalog items
    item1 = CatalogItem(
        merchant_id="merchant_cakehouse_01",
        sku=f"CAKE-{uuid4().hex[:6]}",
        name="Choc Cake",
        description="Fresh chocolate cake",
        category="bakery",
        price_paise=price1,
        in_stock=True,
    )
    item2 = CatalogItem(
        merchant_id="merchant_sweetdelight_02",
        sku=f"SWT-{uuid4().hex[:6]}",
        name="Sweet Delight Pastry",
        description="Pastry item",
        category="bakery",
        price_paise=price2,
        in_stock=True,
    )
    db.add_all([item1, item2])
    db.commit()

    # Sign carts
    cart1, cjwt1 = sign_cart(
        merchant_id="merchant_cakehouse_01",
        line_items_req=[{"sku": item1.sku, "quantity": 1}],
        merchant_private_key_pem=keys["merchant_cake"]["private_key_pem"],
        db=db,
    )
    cart2, cjwt2 = sign_cart(
        merchant_id="merchant_sweetdelight_02",
        line_items_req=[{"sku": item2.sku, "quantity": 1}],
        merchant_private_key_pem=keys["merchant_sweet"]["private_key_pem"],
        db=db,
    )

    plan_id = uuid4()
    plan, mandates, records = authorize_plan(
        intent_jwt=intent_jwt,
        legs=[
            {"merchant_id": "merchant_cakehouse_01", "cart_jwt": cjwt1},
            {"merchant_id": "merchant_sweetdelight_02", "cart_jwt": cjwt2},
        ],
        user_public_key_pem=keys["user"]["public_key_pem"],
        platform_private_key_pem=keys["platform"]["private_key_pem"],
        db=db,
        plan_id=plan_id,
        merchant_public_keys={
            "merchant_cakehouse_01": keys["merchant_cake"]["public_key_pem"],
            "merchant_sweetdelight_02": keys["merchant_sweet"]["public_key_pem"],
        },
    )

    return plan, records, item1, item2


def test_multi_leg_plan_approved_successfully(db_session, keys):
    """Scenario 1: Multi-leg plan approved via HITL executes all legs to ORDER_CREATED."""
    plan, records, it1, it2 = setup_multi_leg_plan(keys, db_session)

    report = execute_purchase_plan(
        plan=plan,
        db=db_session,
        approved_merchant_ids=None,  # All approved
    )

    assert report.status == PlanExecutionStatus.IN_PROGRESS
    assert len(report.successful_legs) == 2
    assert len(report.failed_legs) == 0
    for leg in report.successful_legs:
        assert leg.status == LegExecutionStatus.ORDER_CREATED
        assert leg.razorpay_order_id is not None


def test_hitl_rejection_of_one_leg_releases_reservation(db_session, keys):
    """Scenario 2 & 10: HITL selective approval executes approved leg and releases rejected leg reservation."""
    # Plan total: ₹500 + ₹600 = ₹1,100 (110,000 paise).
    plan, records, it1, it2 = setup_multi_leg_plan(keys, db_session, price1=50000, price2=60000)

    # Operator approves ONLY CakeHouse; rejects Sweet Delight
    report = execute_purchase_plan(
        plan=plan,
        db=db_session,
        approved_merchant_ids=["merchant_cakehouse_01"],
    )

    assert len(report.successful_legs) == 1
    assert report.successful_legs[0].merchant_id == "merchant_cakehouse_01"
    assert report.successful_legs[0].status == LegExecutionStatus.ORDER_CREATED

    assert len(report.failed_legs) == 1
    assert report.failed_legs[0].merchant_id == "merchant_sweetdelight_02"
    assert report.failed_legs[0].status == LegExecutionStatus.RELEASED
    assert report.failed_legs[0].released_reservation_paise == 60000

    # Verify IntentRegistry reservation released for rejected leg
    intent_reg = db_session.query(IntentRegistry).filter_by(intent_id=plan.intent_id).one()
    assert intent_reg.reserved_paise == 50000  # 110,000 - 60,000


def test_quote_expires_and_deterministic_requotation_succeeds(db_session, keys):
    """Scenario 3 & 4 & 5: Expired quote triggers deterministic re-quotation; price unchanged -> proceeds."""
    plan, records, it1, it2 = setup_multi_leg_plan(keys, db_session)
    rec_cake = next(r for r in records if r.merchant_id == "merchant_cakehouse_01")

    # Manually backdate cart creation time
    rec_cake.created_at = datetime.now(timezone.utc) - timedelta(hours=3)
    db_session.commit()

    # JIT revalidation detects expiry and re-quotes at same price
    is_valid, fresh_cart, fresh_jwt, err = revalidate_or_requote_leg(
        mandate_record=rec_cake,
        db=db_session,
        merchant_private_key_pem=keys["merchant_cake"]["private_key_pem"],
    )

    assert is_valid is True
    assert fresh_cart is not None
    assert fresh_cart.total_paise == rec_cake.authorized_amount_paise

    # Leg executes cleanly
    res = execute_plan_leg(
        mandate_record=rec_cake,
        db=db_session,
        merchant_private_key_pem=keys["merchant_cake"]["private_key_pem"],
    )
    assert res.status == LegExecutionStatus.ORDER_CREATED


def test_requoted_amount_increased_requires_reauthorization(db_session, keys):
    """Scenario 6: If re-quoted price increased beyond authorized amount, HITL re-auth is required."""
    plan, records, it1, it2 = setup_multi_leg_plan(keys, db_session, price1=50000)
    rec_cake = next(r for r in records if r.merchant_id == "merchant_cakehouse_01")

    # Backdate creation so JIT checks expiration
    rec_cake.created_at = datetime.now(timezone.utc) - timedelta(hours=3)
    # Merchant increases item price in catalog from ₹500 to ₹700
    it1.price_paise = 70000
    db_session.commit()

    is_valid, fresh_cart, fresh_jwt, err = revalidate_or_requote_leg(
        mandate_record=rec_cake,
        db=db_session,
        merchant_private_key_pem=keys["merchant_cake"]["private_key_pem"],
    )

    assert is_valid is False
    assert "re-authorization required" in err.lower()

    # Attempting execution yields REQUIRES_REAUTH
    res = execute_plan_leg(
        mandate_record=rec_cake,
        db=db_session,
        merchant_private_key_pem=keys["merchant_cake"]["private_key_pem"],
    )
    assert res.status == LegExecutionStatus.REQUIRES_REAUTH
    assert res.error_code == "PRICE_INCREASE_REQUIRES_REAUTH"


def test_merchant_unavailable_after_deliberation(db_session, keys):
    """Scenario 7: Merchant inventory goes out of stock between deliberation and execution."""
    plan, records, it1, it2 = setup_multi_leg_plan(keys, db_session)
    rec_cake = next(r for r in records if r.merchant_id == "merchant_cakehouse_01")

    # Mark merchant inventory out of stock
    it1.in_stock = False
    db_session.commit()

    res = execute_plan_leg(
        mandate_record=rec_cake,
        db=db_session,
        merchant_private_key_pem=keys["merchant_cake"]["private_key_pem"],
    )

    assert res.status == LegExecutionStatus.RELEASED
    assert res.error_code == "MERCHANT_UNAVAILABLE"
    assert res.released_reservation_paise == rec_cake.authorized_amount_paise


def test_one_leg_captured_while_another_fails_becomes_partial_complete(db_session, keys):
    """Scenario 8 & 11 & 17: One leg captured + another leg failed -> PurchasePlan is PARTIAL_COMPLETE."""
    plan, records, it1, it2 = setup_multi_leg_plan(keys, db_session, price1=50000, price2=60000)
    rec1 = next(r for r in records if r.merchant_id == "merchant_cakehouse_01")
    rec2 = next(r for r in records if r.merchant_id == "merchant_sweetdelight_02")

    # Leg 1: executed and payment captured via webhook
    execute_plan_leg(rec1, db_session)
    webhook_secret = "test_webhook_secret_hitl"
    payload, sig = simulate_payment_captured_webhook(
        razorpay_order_id=rec1.razorpay_order_id,
        amount_paise=50000,
        webhook_secret=webhook_secret,
    )
    process_payment_webhook(
        raw_body=payload,
        signature=sig,
        db=db_session,
        webhook_secret=webhook_secret,
        platform_private_key_pem=keys["platform"]["private_key_pem"],
    )

    # Leg 2: fails execution (out of stock)
    it2.in_stock = False
    db_session.commit()
    execute_plan_leg(rec2, db_session)

    # Verify Leg 1 remains captured and was NEVER released
    rec1_reloaded = db_session.query(MandateRecord).filter_by(mandate_id=rec1.mandate_id).one()
    assert rec1_reloaded.status == MandateStatus.PAYMENT_CAPTURED
    assert rec1_reloaded.captured_paise == 50000

    # Verify Leg 2 is released and its reservation returned
    rec2_reloaded = db_session.query(MandateRecord).filter_by(mandate_id=rec2.mandate_id).one()
    assert rec2_reloaded.status == MandateStatus.RELEASED
    assert rec2_reloaded.reserved_paise == 0

    # 11. Aggregate PurchasePlan status is PARTIAL_COMPLETE
    plan_reloaded = db_session.query(PurchasePlan).filter_by(plan_id=plan.plan_id).one()
    assert plan_reloaded.status == PlanExecutionStatus.PARTIAL_COMPLETE.value

    # Intent accounting: captured = 50,000, reserved = 0
    intent_reg = db_session.query(IntentRegistry).filter_by(intent_id=plan.intent_id).one()
    assert intent_reg.captured_paise == 50000
    assert intent_reg.reserved_paise == 0


def test_one_leg_captured_while_another_pending_is_partial_complete(db_session, keys):
    """Scenario 9: One leg captured + one leg still pending -> PARTIAL_COMPLETE."""
    plan, records, it1, it2 = setup_multi_leg_plan(keys, db_session, price1=50000, price2=60000)
    rec1 = next(r for r in records if r.merchant_id == "merchant_cakehouse_01")
    rec2 = next(r for r in records if r.merchant_id == "merchant_sweetdelight_02")

    # Execute both legs to ORDER_CREATED
    execute_plan_leg(rec1, db_session)
    execute_plan_leg(rec2, db_session)

    # Leg 1 captures via webhook; Leg 2 remains pending at gateway
    webhook_secret = "test_webhook_secret_hitl"
    payload, sig = simulate_payment_captured_webhook(
        razorpay_order_id=rec1.razorpay_order_id,
        amount_paise=50000,
        webhook_secret=webhook_secret,
    )
    process_payment_webhook(
        raw_body=payload,
        signature=sig,
        db=db_session,
        webhook_secret=webhook_secret,
        platform_private_key_pem=keys["platform"]["private_key_pem"],
    )

    status = sync_purchase_plan_status(plan, db_session)
    assert status == PlanExecutionStatus.PARTIAL_COMPLETE


def test_fully_captured_plan_becomes_complete(db_session, keys):
    """Scenario 12: When 100% of legs capture, plan status becomes COMPLETE."""
    plan, records, it1, it2 = setup_multi_leg_plan(keys, db_session, price1=40000, price2=50000)
    rec1 = next(r for r in records if r.merchant_id == "merchant_cakehouse_01")
    rec2 = next(r for r in records if r.merchant_id == "merchant_sweetdelight_02")

    execute_plan_leg(rec1, db_session)
    execute_plan_leg(rec2, db_session)

    webhook_secret = "test_webhook_secret_hitl"
    # Capture Leg 1
    p1, s1 = simulate_payment_captured_webhook(
        razorpay_order_id=rec1.razorpay_order_id,
        amount_paise=40000,
        webhook_secret=webhook_secret,
    )
    process_payment_webhook(p1, s1, db_session, webhook_secret, keys["platform"]["private_key_pem"])

    # Capture Leg 2
    p2, s2 = simulate_payment_captured_webhook(
        razorpay_order_id=rec2.razorpay_order_id,
        amount_paise=50000,
        webhook_secret=webhook_secret,
    )
    process_payment_webhook(p2, s2, db_session, webhook_secret, keys["platform"]["private_key_pem"])

    plan_reloaded = db_session.query(PurchasePlan).filter_by(plan_id=plan.plan_id).one()
    assert plan_reloaded.status == PlanExecutionStatus.COMPLETE.value


def test_all_legs_failed_produces_failed_plan_state(db_session, keys):
    """Scenario 13: All legs rejected/failed marks PurchasePlan as FAILED."""
    plan, records, it1, it2 = setup_multi_leg_plan(keys, db_session)

    # Operator rejects all legs
    report = execute_purchase_plan(
        plan=plan,
        db=db_session,
        approved_merchant_ids=[],  # Reject all
    )

    assert report.status == PlanExecutionStatus.FAILED
    assert len(report.failed_legs) == 2
    assert len(report.successful_legs) == 0

    plan_reloaded = db_session.query(PurchasePlan).filter_by(plan_id=plan.plan_id).one()
    assert plan_reloaded.status == PlanExecutionStatus.FAILED.value


def test_explicit_successful_failed_pending_reporting(db_session, keys):
    """Scenario 14: get_plan_execution_report provides complete deterministic audit breakdown."""
    plan, records, it1, it2 = setup_multi_leg_plan(keys, db_session, price1=30000, price2=40000)
    rec1 = next(r for r in records if r.merchant_id == "merchant_cakehouse_01")
    rec2 = next(r for r in records if r.merchant_id == "merchant_sweetdelight_02")

    execute_plan_leg(rec1, db_session)
    release_failed_leg(rec2, db_session, reason="User rejected Sweet Delight.")

    report = get_plan_execution_report(plan, db_session)

    assert report.total_authorized_paise == 70000
    assert len(report.successful_legs) == 1
    assert report.successful_legs[0].merchant_id == "merchant_cakehouse_01"
    assert len(report.failed_legs) == 1
    assert report.failed_legs[0].merchant_id == "merchant_sweetdelight_02"
    assert report.failed_legs[0].released_reservation_paise == 40000
    assert report.total_released_paise == 40000


def test_duplicate_hitl_approval_and_execution_is_idempotent(db_session, keys):
    """Scenario 15 & 16: Duplicate execution calls are strictly idempotent and do not create new orders."""
    plan, records, it1, it2 = setup_multi_leg_plan(keys, db_session)

    # Initial execution
    report1 = execute_purchase_plan(plan, db_session)
    order_ids_1 = [l.razorpay_order_id for l in report1.successful_legs]

    # Duplicate execution
    report2 = execute_purchase_plan(plan, db_session)
    order_ids_2 = [l.razorpay_order_id for l in report2.successful_legs]

    assert order_ids_1 == order_ids_2
    assert len(report2.successful_legs) == 2


def test_audit_ledger_contains_all_plan_and_leg_outcomes(db_session, keys):
    """Scenario 18: Audit ledger logs all order creations and rejections."""
    plan, records, it1, it2 = setup_multi_leg_plan(keys, db_session)
    rec1 = next(r for r in records if r.merchant_id == "merchant_cakehouse_01")
    rec2 = next(r for r in records if r.merchant_id == "merchant_sweetdelight_02")

    execute_plan_leg(rec1, db_session)
    release_failed_leg(rec2, db_session, reason="Test rejection")

    entries = (
        db_session.query(AuditLedgerEntry)
        .order_by(AuditLedgerEntry.id.asc())
        .all()
    )

    types = [e.entry_type for e in entries]
    assert LedgerEntryType.ORDER_CREATED in types
    assert LedgerEntryType.POLICY_REJECTED in types


def test_legacy_single_mandate_flow_remains_unchanged(db_session, keys):
    """Scenario 19: Legacy single-mandate flow is unaffected by M8 changes."""
    seed_catalog(db_session)
    now = datetime.now(timezone.utc)
    intent = UserIntentCredential(
        intent_id=uuid4(),
        user_id="single_buyer",
        spend_cap_paise=100000,
        currency="INR",
        allowed_categories=["bakery"],
        allowed_merchant_ids=["merchant_cakehouse_01"],
        max_transactions=1,
        nonce=f"nonce_{uuid4().hex}",
        not_before=now - timedelta(minutes=5),
        expires_at=now + timedelta(hours=1),
    )
    jwt_intent = issue_intent_jwt(intent, keys["user"]["private_key_pem"])
    verify_intent(jwt_intent, keys["user"]["public_key_pem"], db_session)

    cart, cjwt = sign_cart(
        merchant_id="merchant_cakehouse_01",
        line_items_req=[{"sku": "CAKE-CHOC-001", "quantity": 1}],
        merchant_private_key_pem=keys["merchant_cake"]["private_key_pem"],
        db=db_session,
    )

    mandate, mjwt, rec = authorize_mandate(
        intent_jwt=jwt_intent,
        cart_jwt=cjwt,
        idempotency_key="tx_single_legacy_m8",
        user_public_key_pem=keys["user"]["public_key_pem"],
        merchant_public_key_pem=keys["merchant_cake"]["public_key_pem"],
        platform_private_key_pem=keys["platform"]["private_key_pem"],
        db=db_session,
    )

    assert rec.plan_id is None
    assert rec.status == MandateStatus.RESERVED
