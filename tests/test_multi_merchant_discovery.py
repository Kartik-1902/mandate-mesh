"""Milestone M4: Tests for Pre-Agent Intent & Multi-Merchant Discovery."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient

from app.agent import (
    browse_catalog_tool,
    collect_merchant_quotes,
    propose_cart_tool,
    run_buyer_agent,
)
from app.crypto import issue_intent_jwt
from app.main import app
from app.merchant import seed_catalog
from app.merchant_keys import get_merchant_public_key, get_merchant_private_key
from app.policy import verify_intent
from app.schemas import UserIntentCredential
from app.schemas_routing import QuoteStatus


from app.api.deps import get_db


@pytest.fixture
def client(db_session):
    """FastAPI TestClient with seeded multi-merchant catalog."""
    seed_catalog(db_session)
    db_session.commit()
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_browse_catalog_tool_returns_merchant_ids(db_session):
    """browse_catalog_tool() returns items labeled with merchant_id."""
    seed_catalog(db_session)

    all_items = browse_catalog_tool(db_session)
    assert len(all_items) == 14

    # Check merchant_id field is present
    merchant_ids = {it["merchant_id"] for it in all_items}
    assert merchant_ids == {"merchant_cakehouse_01", "merchant_sweetdelight_02", "merchant_artisan_03"}

    # Test merchant filtering
    sweet_items = browse_catalog_tool(db_session, merchant_id="merchant_sweetdelight_02")
    assert len(sweet_items) == 5
    assert all(it["merchant_id"] == "merchant_sweetdelight_02" for it in sweet_items)


def test_collect_merchant_quotes_queries_all_merchants(db_session):
    """collect_merchant_quotes() collects signed carts from all 3 merchants."""
    seed_catalog(db_session)

    merchants = ["merchant_cakehouse_01", "merchant_sweetdelight_02", "merchant_artisan_03"]
    req = [{"sku": "CAKE-CHOC-001", "quantity": 1}]

    quotes = collect_merchant_quotes(db_session, merchants, req)
    assert len(quotes) == 3

    price_map = {q.merchant_id: q.total_paise for q in quotes}
    assert price_map["merchant_sweetdelight_02"] == 89000  # ₹890.00
    assert price_map["merchant_cakehouse_01"] == 94000     # ₹940.00
    assert price_map["merchant_artisan_03"] == 120000     # ₹1,200.00


def test_collect_merchant_quotes_handles_missing_sku_gracefully(db_session):
    """Bug 2: If a SKU is missing at some merchants, collect_merchant_quotes preserves structured SKU_UNAVAILABLE status."""
    seed_catalog(db_session)

    merchants = ["merchant_cakehouse_01", "merchant_sweetdelight_02", "merchant_artisan_03"]
    # BAKE-MAC-001 is only in Artisan catalog
    req = [{"sku": "BAKE-MAC-001", "quantity": 1}]

    quotes = collect_merchant_quotes(db_session, merchants, req)
    assert len(quotes) == 3

    status_map = {q.merchant_id: q.status for q in quotes}
    assert status_map["merchant_cakehouse_01"] == QuoteStatus.SKU_UNAVAILABLE
    assert status_map["merchant_sweetdelight_02"] == QuoteStatus.SKU_UNAVAILABLE
    assert status_map["merchant_artisan_03"] == QuoteStatus.ELIGIBLE

    artisan_quote = next(q for q in quotes if q.merchant_id == "merchant_artisan_03")
    assert artisan_quote.total_paise == 65000


def test_collect_merchant_quotes_preserves_missing_key_failure(db_session):
    """Bug 2: Unregistered merchant key produces structured MERCHANT_KEY_UNAVAILABLE outcome without crashing."""
    seed_catalog(db_session)
    merchants = ["merchant_cakehouse_01", "unknown_merchant_999"]
    req = [{"sku": "CAKE-CHOC-001", "quantity": 1}]

    quotes = collect_merchant_quotes(db_session, merchants, req)
    assert len(quotes) == 2

    unknown_quote = next(q for q in quotes if q.merchant_id == "unknown_merchant_999")
    assert unknown_quote.status == QuoteStatus.MERCHANT_KEY_UNAVAILABLE
    assert "No trusted signing key" in unknown_quote.rejection_reason

    valid_quote = next(q for q in quotes if q.merchant_id == "merchant_cakehouse_01")
    assert valid_quote.status == QuoteStatus.ELIGIBLE


def test_browse_catalog_tool_scoped_at_db_query(db_session):
    """Bug 5: browse_catalog_tool with merchant_ids filters at the database level."""
    seed_catalog(db_session)

    allowed = ["merchant_cakehouse_01", "merchant_sweetdelight_02"]
    items = browse_catalog_tool(db_session, merchant_ids=allowed)

    found_merchants = {it["merchant_id"] for it in items}
    assert "merchant_artisan_03" not in found_merchants
    assert found_merchants == {"merchant_cakehouse_01", "merchant_sweetdelight_02"}


def test_run_buyer_agent_multi_merchant_routing(db_session):
    """run_buyer_agent() routes chocolate cake goal to Sweet Delight (cheapest)."""
    seed_catalog(db_session)

    now = datetime.now(timezone.utc)
    intent = UserIntentCredential(
        user_id="user_test_buyer",
        spend_cap_paise=150000,
        currency="INR",
        allowed_categories=["bakery"],
        allowed_merchant_ids=["merchant_cakehouse_01", "merchant_sweetdelight_02", "merchant_artisan_03"],
        nonce=uuid4().hex,
        not_before=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
    )

    state = run_buyer_agent(
        goal="Order a 1kg chocolate truffle cake",
        db=db_session,
        intent=intent,
    )

    assert state["status"] == "COMPLETED"
    assert state["routing_decision"] is not None
    assert state["routing_decision"].winner_merchant_id == "merchant_sweetdelight_02"
    assert state["routing_decision"].winner_quote.total_paise == 89000
    assert state["signed_cart"].total_paise == 89000
    assert state["cart_jwt"] is not None


def test_deliberate_api_multi_merchant_discovery_and_order_creation(client, db_session):
    """POST /api/v1/agent/deliberate queries candidate merchants, selects winner, and authorizes mandate."""
    payload = {
        "goal": "Order a 1kg chocolate truffle cake",
        "spend_cap_paise": 150000,
        "allowed_merchant_ids": [
            "merchant_cakehouse_01",
            "merchant_sweetdelight_02",
            "merchant_artisan_03",
        ],
    }

    response = client.post("/api/v1/agent/deliberate", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "COMPLETED"
    assert data["routing_decision"]["winner_merchant_id"] == "merchant_sweetdelight_02"
    assert data["mandate"] is not None
    assert data["mandate"]["status"] == "ORDER_CREATED"
    assert data["razorpay_order_id"] is not None
    assert len(data["candidate_quotes"]) == 3

    # Verify candidate quotes safely omit JWT and show delta
    winner_quote = next(q for q in data["candidate_quotes"] if q["is_winner"])
    assert winner_quote["merchant_id"] == "merchant_sweetdelight_02"
    assert winner_quote["total_paise"] == 89000

    runner_up = next(q for q in data["candidate_quotes"] if q["merchant_id"] == "merchant_cakehouse_01")
    assert runner_up["price_delta_paise"] == 5000  # 94000 - 89000


def test_deliberate_api_single_merchant_backward_compatibility(client, db_session):
    """POST /api/v1/agent/deliberate with single merchant_id targets only that merchant."""
    payload = {
        "goal": "Order a 1kg chocolate truffle cake",
        "merchant_id": "merchant_cakehouse_01",
    }

    response = client.post("/api/v1/agent/deliberate", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "COMPLETED"
    assert data["routing_decision"]["winner_merchant_id"] == "merchant_cakehouse_01"
    assert data["mandate"]["authorized_amount_paise"] == 94000
    assert len(data["candidate_quotes"]) == 1


def test_deliberate_api_does_not_leak_raw_jwts_in_routing_decision(client, db_session):
    """Bug 3 Regression: Recursively proves routing_decision and candidate_quotes never leak raw cart JWTs."""
    payload = {
        "goal": "Order a 1kg chocolate truffle cake",
        "spend_cap_paise": 150000,
        "allowed_merchant_ids": [
            "merchant_cakehouse_01",
            "merchant_sweetdelight_02",
            "merchant_artisan_03",
        ],
    }

    response = client.post("/api/v1/agent/deliberate", json=payload)
    assert response.status_code == 200
    data = response.json()

    routing_decision_json = data["routing_decision"]
    assert routing_decision_json is not None

    def assert_no_jwt_leaks(obj, path=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                new_path = f"{path}.{k}" if path else k
                assert k not in ["cart_jwt", "jwt", "private_key", "merchant_private_key"], f"Found leaked key '{k}' at {new_path}"
                assert_no_jwt_leaks(v, new_path)
        elif isinstance(obj, list):
            for i, it in enumerate(obj):
                assert_no_jwt_leaks(it, f"{path}[{i}]")

    # Assert no JWT fields inside routing_decision
    assert_no_jwt_leaks(routing_decision_json, "routing_decision")
    assert_no_jwt_leaks(data["candidate_quotes"], "candidate_quotes")
