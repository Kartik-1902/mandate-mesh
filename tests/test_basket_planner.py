"""Milestone M6: Tests for Deterministic Mixed-Basket Planning (ADR-011).

Validates:
1. Single merchant allocation (all items cheapest at one merchant).
2. Same product across multiple merchants (picks lowest price).
3. Different merchant-local SKUs for same canonical product preserved.
4. Mixed basket across multiple merchants (grouped merchant legs).
5. Partial availability fails closed (no partial allocations).
6. Impossible basket returns deterministic infeasibility.
7. Equal total cost / deterministic tie-breaking (lexicographical stability).
8. Unauthorized merchant exclusion (strictly respects allowed_merchant_ids).
9. Stock constraints (out-of-stock items excluded).
10. Grouped merchant legs with authoritative signed carts.
11. Canonical product_id -> merchant-local SKU resolution.
12. Zero financial side effects (no orders, no mandates, no money movement).
13. Spend cap ceiling evaluation.
14. Output stability across repeated runs with identical inputs.
"""

from uuid import UUID, uuid4
import pytest

from app.agent import CommerceOrchestrator
from app.basket_planner import (
    BasketItemRequest,
    BasketPlanStatus,
    MixedBasketPlan,
    plan_mixed_basket,
)
from app.merchant import (
    CANONICAL_CHOCOLATE_CAKE_ID,
    CANONICAL_GREETING_CARD_ID,
    CANONICAL_MACARONS_ID,
    CANONICAL_VANILLA_CAKE_ID,
    seed_catalog,
)
from app.models import AuditLedgerEntry, CanonicalProduct, CatalogItem, MandateRecord


@pytest.fixture(autouse=True)
def setup_catalog(db_session):
    """Seed multi-merchant catalog for testing."""
    seed_catalog(db_session)
    db_session.commit()


def test_plan_mixed_basket_single_merchant_allocation(db_session):
    """Requirement 1: All requested items are cheapest at one merchant -> 1 merchant leg."""
    # Sweet Delight is cheapest for chocolate cake (₹890) and vanilla cake (₹600)
    proposed = [
        {"product_id": CANONICAL_CHOCOLATE_CAKE_ID, "quantity": 1},
        {"product_id": CANONICAL_VANILLA_CAKE_ID, "quantity": 1},
    ]
    allowed = ["merchant_cakehouse_01", "merchant_sweetdelight_02", "merchant_artisan_03"]

    plan: MixedBasketPlan = plan_mixed_basket(
        proposed_items=proposed,
        allowed_merchant_ids=allowed,
        db=db_session,
    )

    assert plan.is_feasible is True
    assert plan.status == BasketPlanStatus.FEASIBLE
    assert len(plan.legs) == 1

    leg = plan.legs[0]
    assert leg.merchant_id == "merchant_sweetdelight_02"
    assert len(leg.items) == 2

    # Check local SKUs are Sweet Delight's SKUs
    skus = {it.sku for it in leg.items}
    assert skus == {"SWT-CHOC-TRF-01", "SWT-VAN-001"}

    # Authoritative total: ₹890 + ₹600 = ₹1,490 (149,000 paise)
    assert leg.total_paise == 149000
    assert plan.total_price_paise == 149000
    assert plan.total_items_count == 2
    assert leg.signed_cart is not None
    assert leg.cart_jwt is not None
    assert leg.signed_cart.total_paise == 149000


def test_plan_mixed_basket_same_product_multiple_merchants(db_session):
    """Requirement 2: Same canonical product across multiple merchants -> lowest price wins."""
    # Chocolate cake is available at:
    # CakeHouse: ₹940
    # Sweet Delight: ₹890
    # Artisan: ₹1,200
    proposed = [{"product_id": CANONICAL_CHOCOLATE_CAKE_ID, "quantity": 2}]
    allowed = ["merchant_cakehouse_01", "merchant_sweetdelight_02", "merchant_artisan_03"]

    plan = plan_mixed_basket(
        proposed_items=proposed,
        allowed_merchant_ids=allowed,
        db=db_session,
    )

    assert plan.is_feasible is True
    assert len(plan.legs) == 1
    leg = plan.legs[0]
    assert leg.merchant_id == "merchant_sweetdelight_02"
    assert leg.items[0].sku == "SWT-CHOC-TRF-01"
    assert leg.items[0].quantity == 2
    assert leg.total_paise == 89000 * 2


def test_plan_mixed_basket_different_merchant_skus_preserved_locally(db_session):
    """Requirement 3: Canonical product resolves to distinct merchant-local SKUs per leg."""
    # When CakeHouse is the only allowed merchant:
    plan_cakehouse = plan_mixed_basket(
        proposed_items=[{"product_id": CANONICAL_CHOCOLATE_CAKE_ID, "quantity": 1}],
        allowed_merchant_ids=["merchant_cakehouse_01"],
        db=db_session,
    )
    assert plan_cakehouse.legs[0].items[0].sku == "CAKE-CHOC-001"

    # When Sweet Delight is the only allowed merchant:
    plan_sweet = plan_mixed_basket(
        proposed_items=[{"product_id": CANONICAL_CHOCOLATE_CAKE_ID, "quantity": 1}],
        allowed_merchant_ids=["merchant_sweetdelight_02"],
        db=db_session,
    )
    assert plan_sweet.legs[0].items[0].sku == "SWT-CHOC-TRF-01"

    # When Artisan is the only allowed merchant:
    plan_artisan = plan_mixed_basket(
        proposed_items=[{"product_id": CANONICAL_CHOCOLATE_CAKE_ID, "quantity": 1}],
        allowed_merchant_ids=["merchant_artisan_03"],
        db=db_session,
    )
    assert plan_artisan.legs[0].items[0].sku == "ART-BELG-CHOC-01"


def test_plan_mixed_basket_across_multiple_merchants_grouped_legs(db_session):
    """Requirement 4: Mixed basket across multiple merchants produces grouped merchant legs."""
    # Chocolate cake is cheapest at Sweet Delight (₹890).
    # Macarons are ONLY offered at Artisan (₹650).
    proposed = [
        {"product_id": CANONICAL_CHOCOLATE_CAKE_ID, "quantity": 1},
        {"product_id": CANONICAL_MACARONS_ID, "quantity": 1},
    ]
    allowed = ["merchant_cakehouse_01", "merchant_sweetdelight_02", "merchant_artisan_03"]

    plan = plan_mixed_basket(
        proposed_items=proposed,
        allowed_merchant_ids=allowed,
        db=db_session,
    )

    assert plan.is_feasible is True
    assert plan.status == BasketPlanStatus.FEASIBLE
    assert len(plan.legs) == 2

    legs_by_mid = {leg.merchant_id: leg for leg in plan.legs}
    assert "merchant_sweetdelight_02" in legs_by_mid
    assert "merchant_artisan_03" in legs_by_mid

    # Leg 1: Sweet Delight
    leg_sweet = legs_by_mid["merchant_sweetdelight_02"]
    assert len(leg_sweet.items) == 1
    assert leg_sweet.items[0].sku == "SWT-CHOC-TRF-01"
    assert leg_sweet.total_paise == 89000

    # Leg 2: Artisan
    leg_artisan = legs_by_mid["merchant_artisan_03"]
    assert len(leg_artisan.items) == 1
    assert leg_artisan.items[0].sku == "BAKE-MAC-001"
    assert leg_artisan.total_paise == 65000

    # Overall plan
    assert plan.total_price_paise == 89000 + 65000
    assert plan.total_items_count == 2


def test_plan_mixed_basket_partial_availability_fails_closed(db_session):
    """Requirement 5: If one item is unavailable across all merchants, basket fails closed."""
    nonexistent_pid = uuid4()
    proposed = [
        {"product_id": CANONICAL_CHOCOLATE_CAKE_ID, "quantity": 1},
        {"product_id": nonexistent_pid, "quantity": 1},
    ]
    allowed = ["merchant_cakehouse_01", "merchant_sweetdelight_02"]

    plan = plan_mixed_basket(
        proposed_items=proposed,
        allowed_merchant_ids=allowed,
        db=db_session,
    )

    assert plan.is_feasible is False
    assert plan.status == BasketPlanStatus.INFEASIBLE
    assert len(plan.legs) == 0
    assert nonexistent_pid in plan.unavailable_product_ids
    assert CANONICAL_CHOCOLATE_CAKE_ID not in plan.unavailable_product_ids
    assert "cannot be satisfied" in plan.rejection_reason


def test_plan_mixed_basket_impossible_basket(db_session):
    """Requirement 6: An impossible basket returns deterministic infeasible result."""
    proposed = [
        {"product_id": uuid4(), "quantity": 1},
        {"product_id": uuid4(), "quantity": 2},
    ]
    plan = plan_mixed_basket(
        proposed_items=proposed,
        allowed_merchant_ids=["merchant_cakehouse_01"],
        db=db_session,
    )

    assert plan.is_feasible is False
    assert plan.status == BasketPlanStatus.INFEASIBLE
    assert len(plan.legs) == 0
    assert len(plan.unavailable_product_ids) == 2


def test_plan_mixed_basket_deterministic_tie_breaking_equal_cost(db_session):
    """Requirement 7: Equal cost choices resolve deterministically via stable tie-breaking."""
    # Create a new canonical product offered at identical prices by CakeHouse and Sweet Delight
    equal_pid = uuid4()
    prod = CanonicalProduct(
        product_id=equal_pid,
        canonical_name="Equal Price Item",
        description="Equal Price Description",
        category="bakery",
    )
    db_session.add(prod)

    item_cakehouse = CatalogItem(
        merchant_id="merchant_cakehouse_01",
        sku="EQUAL-CH-01",
        product_id=equal_pid,
        name="Equal Price Item",
        description="Equal Price Description",
        category="bakery",
        price_paise=50000,  # ₹500
        in_stock=True,
    )
    item_sweet = CatalogItem(
        merchant_id="merchant_sweetdelight_02",
        sku="EQUAL-SW-01",
        product_id=equal_pid,
        name="Equal Price Item",
        description="Equal Price Description",
        category="bakery",
        price_paise=50000,  # ₹500 (Exact same price)
        in_stock=True,
    )
    db_session.add_all([item_cakehouse, item_sweet])
    db_session.commit()

    # Stable tie-break rule: (price_paise ASC, merchant_id ASC, sku ASC)
    # "merchant_cakehouse_01" < "merchant_sweetdelight_02", so CakeHouse must win every time
    for _ in range(10):
        plan = plan_mixed_basket(
            proposed_items=[{"product_id": equal_pid, "quantity": 1}],
            allowed_merchant_ids=["merchant_cakehouse_01", "merchant_sweetdelight_02"],
            db=db_session,
        )
        assert plan.is_feasible is True
        assert len(plan.legs) == 1
        assert plan.legs[0].merchant_id == "merchant_cakehouse_01"
        assert plan.legs[0].items[0].sku == "EQUAL-CH-01"


def test_plan_mixed_basket_unauthorized_merchant_exclusion(db_session):
    """Requirement 8: Merchants not in allowed_merchant_ids are never allocated."""
    # Sweet Delight has lowest price for chocolate cake (₹890 vs CakeHouse ₹940).
    # If Sweet Delight is omitted from allowlist, CakeHouse must win.
    plan = plan_mixed_basket(
        proposed_items=[{"product_id": CANONICAL_CHOCOLATE_CAKE_ID, "quantity": 1}],
        allowed_merchant_ids=["merchant_cakehouse_01", "merchant_artisan_03"],
        db=db_session,
    )

    assert plan.is_feasible is True
    assert len(plan.legs) == 1
    assert plan.legs[0].merchant_id == "merchant_cakehouse_01"
    assert plan.legs[0].items[0].sku == "CAKE-CHOC-001"


def test_plan_mixed_basket_stock_constraints(db_session):
    """Requirement 9: Out-of-stock items are strictly excluded from allocation."""
    # Mark Sweet Delight's chocolate cake out of stock
    sweet_item = (
        db_session.query(CatalogItem)
        .filter_by(merchant_id="merchant_sweetdelight_02", sku="SWT-CHOC-TRF-01")
        .first()
    )
    sweet_item.in_stock = False
    db_session.commit()

    # Even though Sweet Delight is cheaper, planner must fall back to CakeHouse
    plan = plan_mixed_basket(
        proposed_items=[{"product_id": CANONICAL_CHOCOLATE_CAKE_ID, "quantity": 1}],
        allowed_merchant_ids=["merchant_cakehouse_01", "merchant_sweetdelight_02"],
        db=db_session,
    )

    assert plan.is_feasible is True
    assert plan.legs[0].merchant_id == "merchant_cakehouse_01"


def test_plan_mixed_basket_no_financial_authorization_side_effects(db_session):
    """Requirement 10: Mixed-basket planning emits ZERO financial, order, or mandate side effects."""
    from app.models import LedgerEntryType

    initial_mandates = db_session.query(MandateRecord).count()

    proposed = [
        {"product_id": CANONICAL_CHOCOLATE_CAKE_ID, "quantity": 1},
        {"product_id": CANONICAL_MACARONS_ID, "quantity": 2},
    ]
    allowed = ["merchant_cakehouse_01", "merchant_sweetdelight_02", "merchant_artisan_03"]

    plan = plan_mixed_basket(
        proposed_items=proposed,
        allowed_merchant_ids=allowed,
        db=db_session,
    )

    assert plan.is_feasible is True
    # Verify zero database mutations on financial mandate entities
    assert db_session.query(MandateRecord).count() == initial_mandates

    # Verify zero payment or mandate authorization ledger events were created
    mandate_ledger_entries = (
        db_session.query(AuditLedgerEntry)
        .filter(
            AuditLedgerEntry.entry_type.in_([
                LedgerEntryType.MANDATE_CREATED,
                LedgerEntryType.ORDER_CREATED,
                LedgerEntryType.PAYMENT_CAPTURED,
            ])
        )
        .count()
    )
    assert mandate_ledger_entries == 0


def test_m6_commercial_plan_is_feasible_regardless_of_spend_cap(db_session):
    """Requirement 1 & 2 & 3: A commercially feasible basket remains a valid M6 plan and calculates correct total."""
    # Chocolate cake (₹890) + Macarons (₹650) = ₹1,540 (154,000 paise)
    proposed = [
        {"product_id": CANONICAL_CHOCOLATE_CAKE_ID, "quantity": 1},
        {"product_id": CANONICAL_MACARONS_ID, "quantity": 1},
    ]
    allowed = ["merchant_sweetdelight_02", "merchant_artisan_03"]

    # M6 MixedBasketPlanner executes pure commercial planning
    plan = plan_mixed_basket(
        proposed_items=proposed,
        allowed_merchant_ids=allowed,
        db=db_session,
    )

    # 1. Commercial feasibility is True
    assert plan.is_feasible is True
    assert plan.status == BasketPlanStatus.FEASIBLE

    # 2. M6 correctly computes authoritative plan total
    assert plan.total_price_paise == 154000
    assert len(plan.legs) == 2


def test_m5_policy_layer_handles_spend_cap_authorization_and_escalation(db_session):
    """Requirement 4: Spend-cap authorization is strictly handled by the deterministic M5 policy layer."""
    orchestrator = CommerceOrchestrator(db=db_session)
    proposed = [
        {"product_id": CANONICAL_CHOCOLATE_CAKE_ID, "quantity": 1},
        {"product_id": CANONICAL_MACARONS_ID, "quantity": 1},
    ]
    allowed = ["merchant_sweetdelight_02", "merchant_artisan_03"]

    # M6 produces valid commercial plan with total ₹1,540 (154,000 paise)
    plan = orchestrator.plan_basket(
        proposed_items=proposed,
        allowed_merchant_ids=allowed,
    )
    assert plan.is_feasible is True
    assert plan.total_price_paise == 154000

    # Scenario A: Spend cap ₹2,000 (200,000 paise) -> AUTHORIZED by M5 policy layer
    decision_auth = orchestrator.evaluate_basket_authorization(
        plan=plan,
        spend_cap_paise=200000,
    )
    assert decision_auth["status"] == "AUTHORIZED"
    assert decision_auth["is_authorized"] is True
    assert decision_auth["overspend_paise"] == 0
    assert decision_auth["escalation_details"] is None

    # Scenario B: Spend cap ₹1,000 (100,000 paise) -> REQUIRES_USER_APPROVAL by M5 policy layer
    decision_escalate = orchestrator.evaluate_basket_authorization(
        plan=plan,
        spend_cap_paise=100000,
    )
    assert decision_escalate["status"] == "REQUIRES_USER_APPROVAL"
    assert decision_escalate["is_authorized"] is False
    assert decision_escalate["overspend_paise"] == 54000  # 154,000 - 100,000
    assert decision_escalate["escalation_details"] is not None
    assert decision_escalate["escalation_details"]["overspend_paise"] == 54000
    assert "exceeds your Rs. 1000.00 budget by Rs. 540.00" in decision_escalate["escalation_details"]["message"]

    # Combined helper pipeline test
    combined_result = orchestrator.plan_and_evaluate_basket(
        proposed_items=proposed,
        allowed_merchant_ids=allowed,
        spend_cap_paise=100000,
    )
    assert combined_result["status"] == "REQUIRES_USER_APPROVAL"
    assert combined_result["plan"].is_feasible is True


def test_plan_mixed_basket_output_stability_across_repeated_runs(db_session):
    """Stability: Repeated invocations with identical inputs produce identical allocations."""
    proposed = [
        {"product_id": CANONICAL_CHOCOLATE_CAKE_ID, "quantity": 1},
        {"product_id": CANONICAL_VANILLA_CAKE_ID, "quantity": 2},
        {"product_id": CANONICAL_MACARONS_ID, "quantity": 1},
    ]
    allowed = ["merchant_cakehouse_01", "merchant_sweetdelight_02", "merchant_artisan_03"]

    baseline_plan = plan_mixed_basket(
        proposed_items=proposed,
        allowed_merchant_ids=allowed,
        db=db_session,
    )

    for _ in range(10):
        repeat_plan = plan_mixed_basket(
            proposed_items=proposed,
            allowed_merchant_ids=allowed,
            db=db_session,
        )
        assert repeat_plan.total_price_paise == baseline_plan.total_price_paise
        assert len(repeat_plan.legs) == len(baseline_plan.legs)
        for i in range(len(baseline_plan.legs)):
            assert repeat_plan.legs[i].merchant_id == baseline_plan.legs[i].merchant_id
            assert repeat_plan.legs[i].total_paise == baseline_plan.legs[i].total_paise
            assert [it.sku for it in repeat_plan.legs[i].items] == [it.sku for it in baseline_plan.legs[i].items]


def test_commerce_orchestrator_plan_basket_integration(db_session):
    """Integration with CommerceOrchestrator."""
    orchestrator = CommerceOrchestrator(db=db_session)
    proposed = [
        {"product_id": CANONICAL_CHOCOLATE_CAKE_ID, "quantity": 1},
        {"product_id": CANONICAL_MACARONS_ID, "quantity": 1},
    ]

    plan = orchestrator.plan_basket(
        proposed_items=proposed,
        allowed_merchant_ids=["merchant_cakehouse_01", "merchant_sweetdelight_02", "merchant_artisan_03"],
    )

    assert plan.is_feasible is True
    assert plan.status == BasketPlanStatus.FEASIBLE
    assert len(plan.legs) == 2
    assert plan.total_price_paise == 89000 + 65000
