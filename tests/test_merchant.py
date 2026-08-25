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
