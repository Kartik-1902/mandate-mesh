"""Milestone M4: Tests for Canonical Product Identity & Resolution."""

from uuid import UUID, uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.agent import (
    browse_catalog_node_factory,
    collect_merchant_quotes,
    deliberate_and_route_node_factory,
    run_buyer_agent,
)
from app.api.deps import get_db
from app.main import app
from app.merchant import (
    CANONICAL_CHOCOLATE_CAKE_ID,
    CANONICAL_GREETING_CARD_ID,
    CANONICAL_MACARONS_ID,
    CANONICAL_VANILLA_CAKE_ID,
    seed_catalog,
)
from app.models import CanonicalProduct, CatalogItem
from app.schemas import UserIntentCredential
from app.schemas_routing import QuoteStatus


@pytest.fixture
def client(db_session):
    """FastAPI TestClient with seeded multi-merchant catalog."""
    seed_catalog(db_session)
    db_session.commit()
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_canonical_product_creation_and_fields(db_session):
    """CanonicalProduct stores universal attributes (name, brand, category, tags, description)."""
    pid = uuid4()
    prod = CanonicalProduct(
        product_id=pid,
        canonical_name="Specialty Pour Over Coffee 250g",
        brand="Blue Tokai",
        category="beverages",
        tags=["coffee", "beans", "roast"],
        description="Freshly roasted medium-dark whole bean coffee.",
    )
    db_session.add(prod)
    db_session.commit()

    queried = db_session.query(CanonicalProduct).filter_by(product_id=pid).first()
    assert queried is not None
    assert queried.canonical_name == "Specialty Pour Over Coffee 250g"
    assert queried.brand == "Blue Tokai"
    assert queried.category == "beverages"
    assert "coffee" in queried.tags
    assert queried.description == "Freshly roasted medium-dark whole bean coffee."


def test_catalog_item_product_id_foreign_key_and_relationship(db_session):
    """CatalogItem.product_id establishes FK relationship to CanonicalProduct."""
    pid = uuid4()
    prod = CanonicalProduct(
        product_id=pid,
        canonical_name="Artisanal Honey Jar 500g",
        category="gourmet",
    )
    db_session.add(prod)
    db_session.flush()

    item = CatalogItem(
        merchant_id="merchant_cakehouse_01",
        sku="CK-HONEY-500",
        product_id=pid,
        name="Raw Forest Honey",
        description="Wild forest organic honey.",
        category="gourmet",
        price_paise=45000,
        in_stock=True,
    )
    db_session.add(item)
    db_session.commit()

    queried_item = db_session.query(CatalogItem).filter_by(sku="CK-HONEY-500").first()
    assert queried_item.product_id == pid
    assert queried_item.product is not None
    assert queried_item.product.canonical_name == "Artisanal Honey Jar 500g"


def test_catalog_item_unmapped_product_id_nullable(db_session):
    """CatalogItem.product_id is permanently nullable for unmapped merchant inventory."""
    item = CatalogItem(
        merchant_id="merchant_cakehouse_01",
        sku="CK-UNMAPPED-999",
        product_id=None,  # Permanently nullable
        name="Custom Merchant Special Item",
        description="Custom bespoke item with no universal platform identity.",
        category="bakery",
        price_paise=100000,
        in_stock=True,
    )
    db_session.add(item)
    db_session.commit()

    queried = db_session.query(CatalogItem).filter_by(sku="CK-UNMAPPED-999").first()
    assert queried is not None
    assert queried.product_id is None
    assert queried.product is None


def test_unique_merchant_sku_constraint_preserved(db_session):
    """Composite unique constraint UNIQUE(merchant_id, sku) remains strictly enforced."""
    item1 = CatalogItem(
        merchant_id="merchant_cakehouse_01",
        sku="UNIQUE-TEST-01",
        name="Item 1",
        description="Desc",
        category="bakery",
        price_paise=10000,
    )
    db_session.add(item1)
    db_session.commit()

    # Same merchant, duplicate SKU must fail
    item2 = CatalogItem(
        merchant_id="merchant_cakehouse_01",
        sku="UNIQUE-TEST-01",
        name="Item 2",
        description="Desc",
        category="bakery",
        price_paise=20000,
    )
    db_session.add(item2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    # Different merchant, same SKU must succeed
    item3 = CatalogItem(
        merchant_id="merchant_sweetdelight_02",
        sku="UNIQUE-TEST-01",
        name="Item 3",
        description="Desc",
        category="bakery",
        price_paise=30000,
    )
    db_session.add(item3)
    db_session.commit()
    assert item3.id is not None


def test_same_canonical_product_different_merchant_skus(db_session):
    """At least one canonical product uses deliberately DIFFERENT SKUs across merchants in demo data."""
    seed_catalog(db_session)

    # Query all catalog items linked to the canonical chocolate cake
    choc_items = (
        db_session.query(CatalogItem)
        .filter_by(product_id=CANONICAL_CHOCOLATE_CAKE_ID)
        .all()
    )
    assert len(choc_items) == 3

    sku_by_merchant = {item.merchant_id: item.sku for item in choc_items}
    # Verify each merchant has a distinct merchant-local SKU
    assert sku_by_merchant["merchant_cakehouse_01"] == "CAKE-CHOC-001"
    assert sku_by_merchant["merchant_sweetdelight_02"] == "SWT-CHOC-TRF-01"
    assert sku_by_merchant["merchant_artisan_03"] == "ART-BELG-CHOC-01"

    # Verify they are all distinct strings
    assert len(set(sku_by_merchant.values())) == 3


def test_collect_merchant_quotes_resolves_canonical_product_id(db_session):
    """collect_merchant_quotes accepts product_id and resolves merchant-local SKUs internally."""
    seed_catalog(db_session)

    merchants = ["merchant_cakehouse_01", "merchant_sweetdelight_02", "merchant_artisan_03"]
    proposed_products = [{"product_id": CANONICAL_CHOCOLATE_CAKE_ID, "quantity": 1}]

    quotes = collect_merchant_quotes(db_session, merchants, proposed_products)
    assert len(quotes) == 3

    # All 3 merchants should return ELIGIBLE quotes with their own local SKUs
    for q in quotes:
        assert q.status == QuoteStatus.ELIGIBLE
        assert len(q.line_items_summary) == 1

    quote_by_merchant = {q.merchant_id: q for q in quotes}
    assert quote_by_merchant["merchant_cakehouse_01"].line_items_summary[0]["sku"] == "CAKE-CHOC-001"
    assert quote_by_merchant["merchant_cakehouse_01"].total_paise == 94000

    assert quote_by_merchant["merchant_sweetdelight_02"].line_items_summary[0]["sku"] == "SWT-CHOC-TRF-01"
    assert quote_by_merchant["merchant_sweetdelight_02"].total_paise == 89000

    assert quote_by_merchant["merchant_artisan_03"].line_items_summary[0]["sku"] == "ART-BELG-CHOC-01"
    assert quote_by_merchant["merchant_artisan_03"].total_paise == 120000


def test_collect_merchant_quotes_handles_unoffered_canonical_product(db_session):
    """If a merchant does not carry a canonical product, collect_merchant_quotes yields SKU_UNAVAILABLE for that merchant."""
    seed_catalog(db_session)

    merchants = ["merchant_cakehouse_01", "merchant_sweetdelight_02", "merchant_artisan_03"]
    # Macarons are only linked at Artisan
    proposed = [{"product_id": CANONICAL_MACARONS_ID, "quantity": 1}]

    quotes = collect_merchant_quotes(db_session, merchants, proposed)
    status_map = {q.merchant_id: q.status for q in quotes}

    assert status_map["merchant_cakehouse_01"] == QuoteStatus.SKU_UNAVAILABLE
    assert status_map["merchant_sweetdelight_02"] == QuoteStatus.SKU_UNAVAILABLE
    assert status_map["merchant_artisan_03"] == QuoteStatus.ELIGIBLE


def test_llm_prompt_blindness_to_skus_and_merchants(db_session, monkeypatch):
    """The deliberation prompt presented to the LLM must contain NO merchant_id or merchant-local SKU."""
    seed_catalog(db_session)

    captured_prompts: list[str] = []

    def mock_call_llm(prompt: str, api_key: str, model: str = "") -> str:
        captured_prompts.append(prompt)
        # Return valid JSON selecting the canonical chocolate cake
        return f'{{"items": [{{"product_id": "{CANONICAL_CHOCOLATE_CAKE_ID}", "quantity": 1}}], "reasoning": "Selected canonical truffle cake"}}'

    import app.agent
    monkeypatch.setattr(app.agent, "call_gemini_llm", mock_call_llm)
    monkeypatch.setattr(app.agent.settings, "GEMINI_API_KEY", "fake_test_key")

    browse_node = browse_catalog_node_factory(db_session)
    state = {
        "goal": "Order a 1kg chocolate truffle cake",
        "parsed_intent": {"category": "bakery", "keywords": ["chocolate", "cake"]},
        "allowed_merchant_ids": ["merchant_cakehouse_01", "merchant_sweetdelight_02"],
        "spend_cap_paise": 150000,
    }
    state.update(browse_node(state))

    deliberate_node = deliberate_and_route_node_factory(db_session)
    deliberate_node(state)

    assert len(captured_prompts) == 1
    llm_prompt = captured_prompts[0]

    # Assert that merchant IDs and merchant-local SKUs are strictly absent from the prompt
    assert "merchant_cakehouse_01" not in llm_prompt
    assert "merchant_sweetdelight_02" not in llm_prompt
    assert "merchant_artisan_03" not in llm_prompt
    assert "CAKE-CHOC-001" not in llm_prompt
    assert "SWT-CHOC-TRF-01" not in llm_prompt
    assert "ART-BELG-CHOC-01" not in llm_prompt

    # Assert that canonical attributes ARE present
    assert "Chocolate Truffle Cake (1kg)" in llm_prompt
    assert str(CANONICAL_CHOCOLATE_CAKE_ID) in llm_prompt
    assert "CakeHouse Artisans" in llm_prompt or "Sweet Delights" in llm_prompt


def test_canonical_products_api_endpoint(client, db_session):
    """GET /api/v1/products lists all canonical products with search and category filters."""
    response = client.get("/api/v1/products")
    assert response.status_code == 200
    products = response.json()
    assert len(products) >= 4

    p_names = {p["canonical_name"] for p in products}
    assert "Chocolate Truffle Cake (1kg)" in p_names
    assert "Classic Vanilla Bean Cake (1kg)" in p_names

    # Filter by category
    cat_res = client.get("/api/v1/products?category=gifting")
    assert cat_res.status_code == 200
    gifting_prods = cat_res.json()
    assert all(p["category"] == "gifting" for p in gifting_prods)

    # Search by query
    search_res = client.get("/api/v1/products?query=truffle")
    assert search_res.status_code == 200
    search_prods = search_res.json()
    assert len(search_prods) == 1
    assert search_prods[0]["canonical_name"] == "Chocolate Truffle Cake (1kg)"


def test_deleting_canonical_product_does_not_delete_catalog_item(db_session):
    """Regression Test: Deleting a CanonicalProduct must NOT cascade-delete CatalogItem (no delete-orphan)."""
    pid = uuid4()
    prod = CanonicalProduct(
        product_id=pid,
        canonical_name="Temporary Canonical Good",
        category="bakery",
    )
    db_session.add(prod)
    db_session.flush()

    item = CatalogItem(
        merchant_id="merchant_cakehouse_01",
        sku="CK-PERSISTENT-01",
        product_id=pid,
        name="Merchant Persistent Inventory Item",
        description="Must survive canonical deletion.",
        category="bakery",
        price_paise=50000,
        in_stock=True,
    )
    db_session.add(item)
    db_session.commit()

    # Unlink canonical product and delete
    item.product_id = None
    db_session.delete(prod)
    db_session.commit()

    # CatalogItem MUST still exist in database
    survived = db_session.query(CatalogItem).filter_by(sku="CK-PERSISTENT-01").first()
    assert survived is not None
    assert survived.name == "Merchant Persistent Inventory Item"
    assert survived.product_id is None

