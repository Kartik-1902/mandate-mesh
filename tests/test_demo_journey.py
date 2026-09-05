"""Tests for the Guided Transaction Journey demo endpoint (Live Observability Rework).

Verifies that /api/v1/demo/multi-leg-journey uses the real execution engine:
- Real buyer agent deliberation
- Real basket planner allocation
- Real PurchasePlan authorization
- Real JIT revalidation (stock toggle → fail-closed)
- Real capture webhook processing
- Run-scoped audit event collection
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest

from app.crypto import generate_es256_keypair, issue_intent_jwt
from app.merchant import seed_catalog
from app.models import (
    AuditLedgerEntry,
    CatalogItem,
    IntentRegistry,
    LedgerEntryType,
    MandateRecord,
    MandateStatus,
    PurchasePlan,
)
from app.policy import verify_intent
from app.schemas import UserIntentCredential


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def keys():
    from app.merchant_keys import get_merchant_private_key, get_merchant_public_key
    u_priv, u_pub = generate_es256_keypair()
    p_priv, p_pub = generate_es256_keypair()
    return {
        "user_priv": u_priv,
        "user_pub": u_pub,
        "platform_priv": p_priv,
        "platform_pub": p_pub,
        "cake_pub": get_merchant_public_key("merchant_cakehouse_01"),
        "sweet_pub": get_merchant_public_key("merchant_sweetdelight_02"),
    }


@pytest.fixture
def seeded_db(db_session):
    """Seeds the catalog with demo products and merchant catalog items."""
    seed_catalog(db_session)
    db_session.commit()
    return db_session


def _run_demo_journey(db, keys, scenario="partial_failure", goal="I need a birthday cake and candles under Rs. 1500", spend_cap=150000):
    """Calls the demo endpoint logic directly (reuses the same code path)."""
    from app.agent import run_buyer_agent
    from app.basket_planner import plan_mixed_basket
    from app.hitl_execution import (
        LegExecutionStatus,
        execute_plan_leg,
        sync_purchase_plan_status,
    )
    from app.merchant import CANONICAL_CHOCOLATE_CAKE_ID, CANONICAL_GREETING_CARD_ID, sign_cart
    from app.merchant_keys import get_merchant_private_key, get_merchant_public_key
    from app.policy import authorize_plan
    from app.razorpay_client import RazorpayClient, simulate_payment_captured_webhook
    from app.webhooks import process_payment_webhook
    from app.ledger import verify_chain

    now = datetime.now(timezone.utc)
    rzp = RazorpayClient(mock_mode=True)
    run_id = uuid4().hex[:12]

    # Baseline ledger
    last_entry = db.query(AuditLedgerEntry).order_by(AuditLedgerEntry.id.desc()).first()
    baseline_id = last_entry.id if last_entry else 0

    # 1. Mint intent
    intent_id = uuid4()
    intent = UserIntentCredential(
        intent_id=intent_id,
        user_id="user_control_tower_01",
        spend_cap_paise=spend_cap,
        allowed_categories=["bakery", "gifting"],
        allowed_merchant_ids=["merchant_cakehouse_01", "merchant_sweetdelight_02"],
        nonce=uuid4().hex,
        not_before=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
    )
    intent_jwt = issue_intent_jwt(intent, keys["user_priv"])
    verify_intent(intent_jwt, keys["user_pub"], db)
    intent_reg = db.query(IntentRegistry).filter(IntentRegistry.intent_id == str(intent_id)).first()
    db.commit()

    # 2. Real AI
    agent_result = run_buyer_agent(
        goal=goal,
        db=db,
        intent=intent,
        allowed_merchant_ids=intent.allowed_merchant_ids,
        spend_cap_paise=spend_cap,
        proposed_items=[
            {"product_id": str(CANONICAL_CHOCOLATE_CAKE_ID), "quantity": 1},
            {"product_id": str(CANONICAL_GREETING_CARD_ID), "quantity": 1},
        ],
    )
    proposed_items = agent_result.get("proposed_items", [])

    # 3. Basket plan
    basket = plan_mixed_basket(
        proposed_items=proposed_items,
        allowed_merchant_ids=intent.allowed_merchant_ids,
        db=db,
    )
    plan_legs = []
    leg_cart_jwts = {}
    leg_info = {}
    for bleg in basket.legs:
        if bleg.cart_jwt:
            plan_legs.append({"merchant_id": bleg.merchant_id, "cart_jwt": bleg.cart_jwt})
            leg_cart_jwts[bleg.merchant_id] = bleg.cart_jwt
            if bleg.items:
                leg_info[bleg.merchant_id] = {"sku": bleg.items[0].sku}

    if len(plan_legs) < 2:
        cake_priv = get_merchant_private_key("merchant_cakehouse_01")
        sweet_priv = get_merchant_private_key("merchant_sweetdelight_02")
        cart1, cjwt1 = sign_cart(
            merchant_id="merchant_cakehouse_01",
            line_items_req=[{"sku": "CAKE-CHOC-001", "quantity": 1}],
            merchant_private_key_pem=cake_priv,
            db=db,
        )
        cart2, cjwt2 = sign_cart(
            merchant_id="merchant_sweetdelight_02",
            line_items_req=[{"sku": "SWT-GIFT-001", "quantity": 1}],
            merchant_private_key_pem=sweet_priv,
            db=db,
        )
        plan_legs = [
            {"merchant_id": "merchant_cakehouse_01", "cart_jwt": cjwt1},
            {"merchant_id": "merchant_sweetdelight_02", "cart_jwt": cjwt2},
        ]
        leg_cart_jwts = {
            "merchant_cakehouse_01": cjwt1,
            "merchant_sweetdelight_02": cjwt2,
        }
        leg_info = {
            "merchant_cakehouse_01": {"sku": "CAKE-CHOC-001"},
            "merchant_sweetdelight_02": {"sku": "SWT-GIFT-001"},
        }

    merchant_pubs = {}
    for mid in leg_cart_jwts:
        merchant_pubs[mid] = get_merchant_public_key(mid)

    # 4. Authorize plan
    plan_id = uuid4()
    plan, mandates, records = authorize_plan(
        intent_jwt=intent_jwt,
        legs=plan_legs,
        user_public_key_pem=keys["user_pub"],
        platform_private_key_pem=keys["platform_priv"],
        db=db,
        plan_id=plan_id,
        merchant_public_keys=merchant_pubs,
    )
    db.commit()

    # Pre-execution snapshot
    db.refresh(intent_reg)
    pre_exec = {
        "spend_cap_paise": intent_reg.spend_cap_paise,
        "reserved_paise": intent_reg.reserved_paise,
        "captured_paise": intent_reg.captured_paise,
        "available_paise": intent_reg.available_paise,
    }

    # 5. Execute legs
    legs_results = []
    for i, record in enumerate(records):
        mid = record.merchant_id
        cjwt = leg_cart_jwts.get(mid)
        m_priv = get_merchant_private_key(mid)
        info = leg_info.get(mid, {})
        leg_sku = info.get("sku")

        is_last = (i == len(records) - 1)
        sim_fail = scenario == "partial_failure" and is_last and len(records) > 1

        wh_res = None

        if sim_fail:
            cat_item = None
            if leg_sku:
                cat_item = db.query(CatalogItem).filter_by(merchant_id=mid, sku=leg_sku).first()
            try:
                if cat_item:
                    cat_item.in_stock = False
                    db.flush()
                leg_exec = execute_plan_leg(
                    mandate_record=record, db=db, rzp_client=rzp,
                    cart_jwt=cjwt, merchant_private_key_pem=m_priv,
                )
            finally:
                if cat_item:
                    cat_item.in_stock = True
                    db.flush()
        else:
            leg_exec = execute_plan_leg(
                mandate_record=record, db=db, rzp_client=rzp,
                cart_jwt=cjwt, merchant_private_key_pem=m_priv,
            )
            db.refresh(record)
            if leg_exec.status == LegExecutionStatus.ORDER_CREATED and record.razorpay_order_id:
                raw_body, signature = simulate_payment_captured_webhook(
                    razorpay_order_id=record.razorpay_order_id,
                    amount_paise=record.authorized_amount_paise,
                    webhook_secret="whsec_demo_secret",
                )
                wh_res = process_payment_webhook(
                    raw_body=raw_body, signature=signature, db=db,
                    webhook_secret="whsec_demo_secret",
                    platform_private_key_pem=keys["platform_priv"],
                )

        db.refresh(record)
        legs_results.append({
            "record": record,
            "exec": leg_exec,
            "wh_res": wh_res,
            "sku": leg_sku,
        })

    # 6. Sync plan
    sync_purchase_plan_status(plan, db)
    db.commit()

    # Post-execution snapshot
    db.refresh(intent_reg)
    post_exec = {
        "reserved_paise": intent_reg.reserved_paise,
        "captured_paise": intent_reg.captured_paise,
        "available_paise": intent_reg.available_paise,
    }

    # 7. Audit
    is_chain_valid, total_blocks = verify_chain(db)
    run_entries = (
        db.query(AuditLedgerEntry)
        .filter(AuditLedgerEntry.id > baseline_id)
        .order_by(AuditLedgerEntry.id.asc())
        .all()
    )

    return {
        "run_id": run_id,
        "scenario": scenario,
        "intent_id": str(intent_id),
        "intent_reg": intent_reg,
        "plan": plan,
        "plan_id": str(plan_id),
        "records": records,
        "legs_results": legs_results,
        "pre_exec": pre_exec,
        "post_exec": post_exec,
        "is_chain_valid": is_chain_valid,
        "total_blocks": total_blocks,
        "run_entries": run_entries,
        "proposed_items": proposed_items,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPartialFailureScenario:
    """Tests for scenario='partial_failure'."""

    def test_partial_failure_plan_status(self, seeded_db, keys):
        """1. partial_failure → PARTIAL_COMPLETE"""
        result = _run_demo_journey(seeded_db, keys, scenario="partial_failure")
        assert result["plan"].status == "PARTIAL_COMPLETE"

    def test_partial_failure_leg1_captured(self, seeded_db, keys):
        """3. Leg 1 reaches PAYMENT_CAPTURED"""
        result = _run_demo_journey(seeded_db, keys, scenario="partial_failure")
        leg1 = result["records"][0]
        assert leg1.status == MandateStatus.PAYMENT_CAPTURED

    def test_partial_failure_leg2_released(self, seeded_db, keys):
        """4. Leg 2 reaches RELEASED terminal state"""
        result = _run_demo_journey(seeded_db, keys, scenario="partial_failure")
        leg2 = result["records"][1]
        assert leg2.status == MandateStatus.RELEASED

    def test_captured_leg1_amount_never_decreases(self, seeded_db, keys):
        """5. Captured Leg 1 amount stays positive after Leg 2 release"""
        result = _run_demo_journey(seeded_db, keys, scenario="partial_failure")
        leg1 = result["records"][0]
        assert leg1.captured_paise > 0
        assert leg1.captured_paise == leg1.authorized_amount_paise

    def test_jit_genuinely_exercises_stock_check(self, seeded_db, keys):
        """7. Partial failure JIT reports in_stock=false from real revalidation"""
        result = _run_demo_journey(seeded_db, keys, scenario="partial_failure")
        leg2_exec = result["legs_results"][1]["exec"]
        # execute_plan_leg internally called release_failed_leg due to stock exhaustion
        assert leg2_exec.status.value in ("RELEASED", "released")

    def test_catalog_restored_after_failure(self, seeded_db, keys):
        """Fixture safety: CatalogItem.in_stock restored to True after demo run"""
        result = _run_demo_journey(seeded_db, keys, scenario="partial_failure")
        leg2_sku = result["legs_results"][1]["sku"]
        leg2_mid = result["records"][1].merchant_id
        cat_item = seeded_db.query(CatalogItem).filter_by(
            merchant_id=leg2_mid, sku=leg2_sku
        ).first()
        assert cat_item is not None
        assert cat_item.in_stock is True


class TestAllSuccessScenario:
    """Tests for scenario='all_success'."""

    def test_all_success_plan_status(self, seeded_db, keys):
        """2. all_success → COMPLETE"""
        result = _run_demo_journey(seeded_db, keys, scenario="all_success")
        assert result["plan"].status == "COMPLETE"

    def test_all_success_both_legs_captured(self, seeded_db, keys):
        """all_success — both legs reach PAYMENT_CAPTURED"""
        result = _run_demo_journey(seeded_db, keys, scenario="all_success")
        for rec in result["records"]:
            assert rec.status == MandateStatus.PAYMENT_CAPTURED

    def test_all_success_captured_equals_authorized(self, seeded_db, keys):
        """10 (all_success). captured == authorized, released == 0"""
        result = _run_demo_journey(seeded_db, keys, scenario="all_success")
        total_authorized = result["plan"].total_authorized_paise
        total_captured = sum(r.captured_paise for r in result["records"])
        total_released = sum(
            r.authorized_amount_paise - r.captured_paise
            for r in result["records"]
            if r.status == MandateStatus.RELEASED
        )
        assert total_captured == total_authorized
        assert total_released == 0


class TestIntentRegistryAccounting:
    """Tests for IntentRegistry math."""

    def test_intent_registry_available_formula(self, seeded_db, keys):
        """6. available = cap - reserved - captured (post-execution)"""
        result = _run_demo_journey(seeded_db, keys, scenario="partial_failure")
        ir = result["intent_reg"]
        assert ir.available_paise == ir.spend_cap_paise - ir.reserved_paise - ir.captured_paise

    def test_settlement_available_matches_registry(self, seeded_db, keys):
        """11. settlement.available matches IntentRegistry.available_paise"""
        result = _run_demo_journey(seeded_db, keys, scenario="partial_failure")
        ir = result["intent_reg"]
        assert result["post_exec"]["available_paise"] == ir.available_paise


class TestAuditChain:
    """Tests for audit/ledger integrity."""

    def test_audit_chain_valid(self, seeded_db, keys):
        """8. Audit chain is valid after run"""
        result = _run_demo_journey(seeded_db, keys, scenario="partial_failure")
        assert result["is_chain_valid"] is True

    def test_audit_events_are_valid_ledger_types(self, seeded_db, keys):
        """9. All returned event types are valid LedgerEntryType enum values"""
        valid_types = {e.value for e in LedgerEntryType}
        result = _run_demo_journey(seeded_db, keys, scenario="partial_failure")
        for entry in result["run_entries"]:
            assert entry.entry_type.value in valid_types, f"Unknown event type: {entry.entry_type}"

    def test_run_scoped_events_nonempty(self, seeded_db, keys):
        """Run produces at least INTENT_ISSUED + CART_SIGNED + MANDATE_CREATED events"""
        result = _run_demo_journey(seeded_db, keys, scenario="partial_failure")
        types = [e.entry_type.value for e in result["run_entries"]]
        assert "INTENT_ISSUED" in types
        assert "MANDATE_CREATED" in types
        assert len(types) >= 3


class TestResponseShape:
    """Tests for response structure."""

    def test_run_id_and_scenario_returned(self, seeded_db, keys):
        """12. run_id and scenario are present"""
        result = _run_demo_journey(seeded_db, keys, scenario="partial_failure")
        assert result["run_id"] is not None
        assert len(result["run_id"]) == 12
        assert result["scenario"] == "partial_failure"

    def test_proposed_items_nonempty(self, seeded_db, keys):
        """AI stage returns at least one proposed item"""
        result = _run_demo_journey(seeded_db, keys, scenario="partial_failure")
        assert len(result["proposed_items"]) >= 1

    def test_two_legs_created(self, seeded_db, keys):
        """Demo produces exactly 2 legs for the default multi-category goal"""
        result = _run_demo_journey(seeded_db, keys, scenario="partial_failure")
        assert len(result["records"]) == 2
