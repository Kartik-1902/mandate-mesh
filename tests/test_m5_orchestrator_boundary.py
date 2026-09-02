"""Milestone M5: Tests for Agent / Commerce Orchestrator Separation and Exactly-One LLM Call."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient

from app import agent as agent_mod
from app.agent import (
    CommerceOrchestrator,
    browse_catalog_node_factory,
    deliberate_and_route_node_factory,
    parse_goal_node,
    run_buyer_agent,
)
from app.api.deps import get_db
from app.crypto import generate_es256_keypair, issue_intent_jwt
from app.main import app
from app.merchant import (
    CANONICAL_CHOCOLATE_CAKE_ID,
    CANONICAL_VANILLA_CAKE_ID,
    seed_catalog,
)
from app.models import CanonicalProduct, CatalogItem
from app.policy import verify_intent
from app.schemas import UserIntentCredential
from app.schemas_routing import OptimizationPolicy, QuoteStatus


@pytest.fixture
def client(db_session):
    """FastAPI TestClient with seeded multi-merchant catalog."""
    seed_catalog(db_session)
    db_session.commit()
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_llm_prompt_strictly_omits_merchant_ids_and_skus(db_session, monkeypatch):
    """Boundary Rule 1 & 2: Neither merchant_id nor merchant-local SKU ever appears in the LLM prompt."""
    seed_catalog(db_session)

    captured_prompts: list[str] = []

    def mock_call_llm(prompt: str, api_key: str, model: str = "") -> str:
        captured_prompts.append(prompt)
        return f'{{"items": [{{"product_id": "{CANONICAL_CHOCOLATE_CAKE_ID}", "quantity": 1}}], "reasoning": "Selected canonical chocolate cake"}}'

    monkeypatch.setattr(agent_mod, "call_gemini_llm", mock_call_llm)
    monkeypatch.setattr(agent_mod.settings, "GEMINI_API_KEY", "test_gemini_api_key")

    res = run_buyer_agent(
        goal="Order a rich chocolate cake under 1500",
        db=db_session,
        allowed_merchant_ids=["merchant_cakehouse_01", "merchant_sweetdelight_02", "merchant_artisan_03"],
    )

    assert len(captured_prompts) == 1
    prompt = captured_prompts[0]

    # Rule 1: No merchant_id in prompt
    assert "merchant_cakehouse_01" not in prompt
    assert "merchant_sweetdelight_02" not in prompt
    assert "merchant_artisan_03" not in prompt

    # Rule 2: No merchant-local SKU in prompt
    assert "CAKE-CHOC-001" not in prompt
    assert "SWT-CHOC-TRF-01" not in prompt
    assert "ART-BELG-CHOC-01" not in prompt
    assert "CAKE-VAN-001" not in prompt


def test_llm_prompt_strictly_omits_authoritative_prices_and_inventory(db_session, monkeypatch):
    """Boundary Rule 3 & 4: Authoritative merchant prices and inventory identity never appear in LLM prompt."""
    seed_catalog(db_session)

    captured_prompts: list[str] = []

    def mock_call_llm(prompt: str, api_key: str, model: str = "") -> str:
        captured_prompts.append(prompt)
        return f'{{"items": [{{"product_id": "{CANONICAL_CHOCOLATE_CAKE_ID}", "quantity": 1}}], "reasoning": "Selected cake"}}'

    monkeypatch.setattr(agent_mod, "call_gemini_llm", mock_call_llm)
    monkeypatch.setattr(agent_mod.settings, "GEMINI_API_KEY", "test_gemini_api_key")

    run_buyer_agent(
        goal="Order a birthday cake",
        db=db_session,
    )

    assert len(captured_prompts) == 1
    prompt = captured_prompts[0]

    # Rule 4: No merchant prices appear in the prompt
    assert "940" not in prompt
    assert "890" not in prompt
    assert "1200" not in prompt
    assert "94000" not in prompt
    assert "89000" not in prompt
    assert "120000" not in prompt
    assert "Rs." not in prompt and "₹" not in prompt


def test_request_path_makes_exactly_one_llm_call(db_session, monkeypatch):
    """Boundary Rule 5: A single natural language request results in EXACTLY ONE LLM invocation."""
    seed_catalog(db_session)

    call_count = 0

    def mock_call_llm(prompt: str, api_key: str, model: str = "") -> str:
        nonlocal call_count
        call_count += 1
        return f'{{"items": [{{"product_id": "{CANONICAL_CHOCOLATE_CAKE_ID}", "quantity": 1}}], "reasoning": "Interpreted cake goal"}}'

    monkeypatch.setattr(agent_mod, "call_gemini_llm", mock_call_llm)
    monkeypatch.setattr(agent_mod.settings, "GEMINI_API_KEY", "test_gemini_api_key")

    # Execute full buyer agent workflow
    res = run_buyer_agent(
        goal="Order a chocolate cake under 1000",
        db=db_session,
        allowed_merchant_ids=["merchant_cakehouse_01", "merchant_sweetdelight_02"],
    )

    # Prove that EXACTLY ONE LLM call occurred during the request
    assert call_count == 1
    assert res["status"] == "COMPLETED"


def test_api_deliberate_makes_exactly_one_llm_call(client, db_session, monkeypatch):
    """Boundary Rule 5 (API): POST /api/v1/agent/deliberate results in EXACTLY ONE LLM call."""
    call_count = 0

    def mock_call_llm(prompt: str, api_key: str, model: str = "") -> str:
        nonlocal call_count
        call_count += 1
        return f'{{"items": [{{"product_id": "{CANONICAL_CHOCOLATE_CAKE_ID}", "quantity": 1}}], "reasoning": "Interpreted cake goal"}}'

    monkeypatch.setattr(agent_mod, "call_gemini_llm", mock_call_llm)
    monkeypatch.setattr(agent_mod.settings, "GEMINI_API_KEY", "test_gemini_api_key")

    payload = {
        "goal": "Buy me a chocolate cake under 1200",
        "allowed_merchant_ids": ["merchant_cakehouse_01", "merchant_sweetdelight_02"],
    }
    response = client.post("/api/v1/agent/deliberate", json=payload)
    assert response.status_code == 200

    # Exactly one LLM call across the entire endpoint execution
    assert call_count == 1


def test_canonical_product_id_is_sufficient_for_deterministic_orchestrator(db_session):
    """Boundary Rule 6: canonical product_id alone is passed from LLM boundary to CommerceOrchestrator."""
    seed_catalog(db_session)

    # Pure canonical proposal: zero prices, zero merchant_ids, zero SKUs
    proposed_items = [{"product_id": str(CANONICAL_CHOCOLATE_CAKE_ID), "quantity": 1}]

    now = datetime.now(timezone.utc)
    intent = UserIntentCredential(
        user_id="user_test_m5",
        spend_cap_paise=150000,
        currency="INR",
        allowed_categories=["bakery"],
        allowed_merchant_ids=["merchant_cakehouse_01", "merchant_sweetdelight_02"],
        nonce=uuid4().hex,
        not_before=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
    )

    orchestrator = CommerceOrchestrator(db=db_session)
    result = orchestrator.orchestrate(
        proposed_items=proposed_items,
        intent=intent,
    )

    assert result["status"] == "COMPLETED"
    assert result["routing_decision"] is not None
    assert result["routing_decision"].winner_merchant_id == "merchant_sweetdelight_02"
    assert result["signed_cart"] is not None
    assert result["cart_jwt"] is not None


def test_merchant_local_sku_resolution_occurs_only_after_llm_boundary(db_session):
    """Boundary Rule 7: Merchant-local SKU resolution occurs only inside CommerceOrchestrator."""
    seed_catalog(db_session)

    # Input items only possess product_id
    proposed_items = [{"product_id": str(CANONICAL_CHOCOLATE_CAKE_ID), "quantity": 1}]
    for item in proposed_items:
        assert "sku" not in item
        assert "merchant_id" not in item

    orchestrator = CommerceOrchestrator(db=db_session)
    result = orchestrator.orchestrate(
        proposed_items=proposed_items,
        allowed_merchant_ids=["merchant_cakehouse_01", "merchant_sweetdelight_02", "merchant_artisan_03"],
        spend_cap_paise=150000,
    )

    # After orchestrator executes, quotes contain resolved merchant-local SKUs
    quotes = {q.merchant_id: q for q in result["all_quotes"]}
    assert quotes["merchant_cakehouse_01"].line_items_summary[0]["sku"] == "CAKE-CHOC-001"
    assert quotes["merchant_sweetdelight_02"].line_items_summary[0]["sku"] == "SWT-CHOC-TRF-01"
    assert quotes["merchant_artisan_03"].line_items_summary[0]["sku"] == "ART-BELG-CHOC-01"


def test_totals_calculated_deterministically_from_authoritative_merchant_quotes(db_session):
    """Boundary Rule 8: Authoritative totals and price savings are calculated deterministically by orchestrator."""
    seed_catalog(db_session)

    proposed_items = [{"product_id": str(CANONICAL_CHOCOLATE_CAKE_ID), "quantity": 1}]
    orchestrator = CommerceOrchestrator(db=db_session)
    result = orchestrator.orchestrate(
        proposed_items=proposed_items,
        allowed_merchant_ids=["merchant_cakehouse_01", "merchant_sweetdelight_02", "merchant_artisan_03"],
        spend_cap_paise=150000,
        policy=OptimizationPolicy.LOWEST_TOTAL_PRICE,
    )

    decision = result["routing_decision"]
    assert decision.winner_merchant_id == "merchant_sweetdelight_02"
    assert decision.winner_quote.total_paise == 89000  # Authoritative Sweet Delight price
    assert decision.price_savings_paise == 5000        # Runner-up CakeHouse (94000) - 89000 = 5000


def test_deterministic_fallback_makes_zero_llm_calls(db_session, monkeypatch):
    """Boundary Verification: When no API key is configured, fallback makes ZERO LLM calls."""
    seed_catalog(db_session)

    call_count = 0

    def mock_call_llm(prompt: str, api_key: str, model: str = "") -> str:
        nonlocal call_count
        call_count += 1
        return ""

    monkeypatch.setattr(agent_mod, "call_gemini_llm", mock_call_llm)
    monkeypatch.setattr(agent_mod.settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(agent_mod.settings, "GOOGLE_API_KEY", "")

    res = run_buyer_agent(
        goal="Order a chocolate cake under 1000",
        db=db_session,
    )

    assert call_count == 0
    assert res["status"] in ("COMPLETED", "REQUIRES_USER_APPROVAL")
    assert res["proposed_items"] is not None
