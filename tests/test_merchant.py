"""Phase 2: Tests for Authoritative Merchant Catalog & Cart Signing (app/merchant.py)."""

import pytest
from app.crypto import generate_es256_keypair, verify_cart_jwt
from app.errors import CatalogSkuNotFound
from app.merchant import seed_catalog, sign_cart


@pytest.fixture
def merchant_keys():
    return generate_es256_keypair()


def test_merchant_sign_cart_prices_authoritatively_from_catalog(db_session, merchant_keys):
    """Verifies that line items are authoritatively priced against the database catalog."""
    priv, pub = merchant_keys
    seed_catalog(db_session, merchant_id="merchant_cakehouse_01")

    # Agent supplies only SKU and quantity (no price)
    req = [
        {"sku": "CAKE-CHOC-001", "quantity": 1},
        {"sku": "GIFT-CARD-001", "quantity": 2},
    ]

    cart_model, cart_jwt = sign_cart(
        merchant_id="merchant_cakehouse_01",
        line_items_req=req,
        merchant_private_key_pem=priv,
        db=db_session,
    )

    # 1 * 94000 + 2 * 25000 = 94000 + 50000 = 144000 paise (₹1,440.00)
    assert cart_model.total_paise == 144000
    assert len(cart_model.line_items) == 2
    assert cart_model.line_items[0].unit_price_paise == 94000
    assert cart_model.line_items[1].unit_price_paise == 25000

    # Decodes and verifies properly against merchant public key
    decoded = verify_cart_jwt(cart_jwt, pub)
    assert decoded.total_paise == 144000
    assert decoded.cart_hash == cart_model.cart_hash


def test_merchant_sign_cart_nonexistent_sku_raises_404(db_session, merchant_keys):
    """Attack 2: Agent attempts prompt injection by requesting a hallucinated or malicious SKU."""
    priv, _ = merchant_keys
    seed_catalog(db_session, merchant_id="merchant_cakehouse_01")

    req = [
        {"sku": "NON-EXISTENT-SKU-999", "quantity": 1},
    ]

    with pytest.raises(CatalogSkuNotFound, match="Requested SKU 'NON-EXISTENT-SKU-999' does not exist"):
        sign_cart(
            merchant_id="merchant_cakehouse_01",
            line_items_req=req,
            merchant_private_key_pem=priv,
            db=db_session,
        )


def test_seed_catalog_multi_merchant_isolation(db_session):
    """seed_catalog() seeds all 3 demo merchants with independent inventories."""
    from app.models import CatalogItem

    seeded = seed_catalog(db_session)
    assert len(seeded) == 14  # 5 + 5 + 4 items

    cake_items = db_session.query(CatalogItem).filter_by(merchant_id="merchant_cakehouse_01").all()
    sweet_items = db_session.query(CatalogItem).filter_by(merchant_id="merchant_sweetdelight_02").all()
    artisan_items = db_session.query(CatalogItem).filter_by(merchant_id="merchant_artisan_03").all()

    assert len(cake_items) == 5
    assert len(sweet_items) == 5
    assert len(artisan_items) == 4


def test_sign_cart_merchant_catalog_pricing_isolation(db_session):
    """Each merchant authoritatively prices the exact same SKU (CAKE-CHOC-001) from their own catalog."""
    from app.merchant_keys import get_merchant_private_key

    seed_catalog(db_session)

    # 1. CakeHouse prices at ₹940.00
    priv_cake = get_merchant_private_key("merchant_cakehouse_01")
    cart_cake, _ = sign_cart(
        merchant_id="merchant_cakehouse_01",
        line_items_req=[{"sku": "CAKE-CHOC-001", "quantity": 1}],
        merchant_private_key_pem=priv_cake,
        db=db_session,
    )
    assert cart_cake.total_paise == 94000

    # 2. Sweet Delight prices competitively at ₹890.00
    priv_sweet = get_merchant_private_key("merchant_sweetdelight_02")
    cart_sweet, _ = sign_cart(
        merchant_id="merchant_sweetdelight_02",
        line_items_req=[{"sku": "CAKE-CHOC-001", "quantity": 1}],
        merchant_private_key_pem=priv_sweet,
        db=db_session,
    )
    assert cart_sweet.total_paise == 89000

    # 3. Artisan prices at premium ₹1,200.00
    priv_artisan = get_merchant_private_key("merchant_artisan_03")
    cart_artisan, _ = sign_cart(
        merchant_id="merchant_artisan_03",
        line_items_req=[{"sku": "CAKE-CHOC-001", "quantity": 1}],
        merchant_private_key_pem=priv_artisan,
        db=db_session,
    )
    assert cart_artisan.total_paise == 120000
