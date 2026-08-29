"""Unit tests for MerchantQuote, QuoteStatus, and 7-gate quote verification (Milestone M3)."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest

from app.crypto import compute_cart_hash, issue_cart_jwt
from app.merchant import seed_catalog, sign_cart
from app.merchant_keys import get_merchant_private_key
from app.models import CatalogItem
from app.quote_router import verify_and_classify_quotes
from app.schemas import CartLineItem, MerchantSignedCart, UserIntentCredential
from app.schemas_routing import CandidateQuoteResponse, MerchantQuote, QuoteStatus


@pytest.fixture
def base_intent() -> UserIntentCredential:
    """Fixture providing a standard valid UserIntentCredential."""
    now = datetime.now(timezone.utc)
    return UserIntentCredential(
        user_id="user_test_m3",
        spend_cap_paise=150000,  # ₹1,500.00
        currency="INR",
        allowed_categories=["bakery", "gifting"],
        allowed_merchant_ids=["merchant_cakehouse_01", "merchant_sweetdelight_02"],
        max_transactions=5,
        nonce=uuid4().hex,
        not_before=now - timedelta(minutes=5),
        expires_at=now + timedelta(hours=1),
    )


def test_quote_verification_happy_path_eligible(db_session, base_intent):
    """Valid merchant quote within budget passes all 7 gates as QuoteStatus.ELIGIBLE."""
    seed_catalog(db_session)
    priv = get_merchant_private_key("merchant_cakehouse_01")

    cart, cart_jwt = sign_cart(
        merchant_id="merchant_cakehouse_01",
        line_items_req=[{"sku": "CAKE-CHOC-001", "quantity": 1}],
        merchant_private_key_pem=priv,
        db=db_session,
    )

    quote = MerchantQuote(
        merchant_id="merchant_cakehouse_01",
        cart_jwt=cart_jwt,
        signed_cart=cart,
        total_paise=cart.total_paise,
    )

    classified = verify_and_classify_quotes([quote], base_intent, db=db_session)
    assert len(classified) == 1
    assert classified[0].status == QuoteStatus.ELIGIBLE
    assert classified[0].rejection_reason is None
    assert classified[0].verified_at is not None


def test_quote_verification_unauthorized_merchant_blocked(db_session, base_intent):
    """Quote from merchant not in allowed_merchant_ids is classified as MERCHANT_UNAUTHORIZED."""
    seed_catalog(db_session)
    priv_artisan = get_merchant_private_key("merchant_artisan_03")

    cart, cart_jwt = sign_cart(
        merchant_id="merchant_artisan_03",
        line_items_req=[{"sku": "CAKE-CHOC-001", "quantity": 1}],
        merchant_private_key_pem=priv_artisan,
        db=db_session,
    )

    quote = MerchantQuote(
        merchant_id="merchant_artisan_03",
        cart_jwt=cart_jwt,
        signed_cart=cart,
        total_paise=cart.total_paise,
    )

    classified = verify_and_classify_quotes([quote], base_intent, db=db_session)
    assert classified[0].status == QuoteStatus.MERCHANT_UNAUTHORIZED
    assert "not in authorized merchant allowlist" in classified[0].rejection_reason


def test_quote_verification_spend_cap_exceeded_classified(db_session):
    """Quote exceeding spend_cap_paise is classified as SPEND_CAP_EXCEEDED."""
    seed_catalog(db_session)
    priv = get_merchant_private_key("merchant_cakehouse_01")

    # Intent with tight budget of ₹800 (80000 paise)
    now = datetime.now(timezone.utc)
    tight_intent = UserIntentCredential(
        user_id="user_tight_budget",
        spend_cap_paise=80000,
        currency="INR",
        allowed_categories=["bakery"],
        allowed_merchant_ids=["merchant_cakehouse_01"],
        nonce=uuid4().hex,
        not_before=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
    )

    # Cart total is ₹940 (94000 paise)
    cart, cart_jwt = sign_cart(
        merchant_id="merchant_cakehouse_01",
        line_items_req=[{"sku": "CAKE-CHOC-001", "quantity": 1}],
        merchant_private_key_pem=priv,
        db=db_session,
    )

    quote = MerchantQuote(
        merchant_id="merchant_cakehouse_01",
        cart_jwt=cart_jwt,
        signed_cart=cart,
        total_paise=cart.total_paise,
    )

    classified = verify_and_classify_quotes([quote], tight_intent, db=db_session)
    assert classified[0].status == QuoteStatus.SPEND_CAP_EXCEEDED
    assert "exceeds authorized spend cap" in classified[0].rejection_reason


def test_quote_verification_unknown_merchant_key_unavailable(db_session):
    """Quote from an unrecognized merchant raises fail-closed MERCHANT_KEY_UNAVAILABLE."""
    now = datetime.now(timezone.utc)
    intent = UserIntentCredential(
        user_id="user_test",
        spend_cap_paise=100000,
        currency="INR",
        allowed_categories=["bakery"],
        allowed_merchant_ids=["merchant_rogue_99"],
        nonce=uuid4().hex,
        not_before=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
    )

    fake_cart = MerchantSignedCart(
        cart_id=uuid4(),
        merchant_id="merchant_rogue_99",
        line_items=[
            CartLineItem(sku="SKU-1", name="Cake", category="bakery", unit_price_paise=50000, quantity=1)
        ],
        cart_hash="hash",
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
    )

    quote = MerchantQuote(
        merchant_id="merchant_rogue_99",
        cart_jwt="fake.jwt.token",
        signed_cart=fake_cart,
        total_paise=50000,
    )

    classified = verify_and_classify_quotes([quote], intent)
    assert classified[0].status == QuoteStatus.MERCHANT_KEY_UNAVAILABLE
    assert "No trusted public key registered" in classified[0].rejection_reason


def test_quote_verification_tampered_cart_hash_blocked(db_session, base_intent):
    """Cart with forged content hash fails Gate 3 as CART_HASH_MISMATCH."""
    seed_catalog(db_session)
    priv = get_merchant_private_key("merchant_cakehouse_01")

    cart, cart_jwt = sign_cart(
        merchant_id="merchant_cakehouse_01",
        line_items_req=[{"sku": "CAKE-CHOC-001", "quantity": 1}],
        merchant_private_key_pem=priv,
        db=db_session,
    )

    # Tamper with the in-memory line item without recomputing hash or signing
    tampered_cart = cart.model_copy(deep=True)
    tampered_cart.cart_hash = "0" * 64

    quote = MerchantQuote(
        merchant_id="merchant_cakehouse_01",
        cart_jwt=cart_jwt,
        signed_cart=tampered_cart,
        total_paise=cart.total_paise,
    )

    classified = verify_and_classify_quotes([quote], base_intent, db=db_session)
    assert classified[0].status == QuoteStatus.CART_HASH_MISMATCH
    assert "Canonical cart hash mismatch" in classified[0].rejection_reason


def test_quote_verification_expired_quote_blocked(db_session, base_intent):
    """Expired quote fails Gate 4 as QUOTE_EXPIRED."""
    seed_catalog(db_session)
    priv = get_merchant_private_key("merchant_cakehouse_01")

    # Issue cart with 0-second TTL
    cart, cart_jwt = sign_cart(
        merchant_id="merchant_cakehouse_01",
        line_items_req=[{"sku": "CAKE-CHOC-001", "quantity": 1}],
        merchant_private_key_pem=priv,
        db=db_session,
        ttl_seconds=0,
    )

    quote = MerchantQuote(
        merchant_id="merchant_cakehouse_01",
        cart_jwt=cart_jwt,
        signed_cart=cart,
        total_paise=cart.total_paise,
    )

    # Verify at 1 second in the future
    future_time = cart.expires_at + timedelta(seconds=1)
    classified = verify_and_classify_quotes([quote], base_intent, db=db_session, now=future_time)
    assert classified[0].status == QuoteStatus.QUOTE_EXPIRED


def test_quote_verification_wrong_signature_blocked(db_session, base_intent):
    """Cart signed with Sweet Delight key but claiming CakeHouse identity fails Gate 2 as INVALID_SIGNATURE."""
    seed_catalog(db_session)
    priv_sweet = get_merchant_private_key("merchant_sweetdelight_02")

    # Sign CakeHouse cart using Sweet Delight's private key (forgery simulation)
    now = datetime.now(timezone.utc)
    forged_cart = MerchantSignedCart(
        cart_id=uuid4(),
        merchant_id="merchant_cakehouse_01",
        line_items=[
            CartLineItem(sku="CAKE-CHOC-001", name="Cake", category="bakery", unit_price_paise=94000, quantity=1)
        ],
        cart_hash="",
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    forged_cart.cart_hash = compute_cart_hash(forged_cart)
    forged_jwt = issue_cart_jwt(forged_cart, priv_sweet, kid="merchant_sweetdelight_02:key-1")

    quote = MerchantQuote(
        merchant_id="merchant_cakehouse_01",
        cart_jwt=forged_jwt,
        signed_cart=forged_cart,
        total_paise=forged_cart.total_paise,
    )

    classified = verify_and_classify_quotes([quote], base_intent, db=db_session)
    assert classified[0].status == QuoteStatus.INVALID_SIGNATURE


def test_quote_verification_out_of_stock_blocked(db_session, base_intent):
    """Quote with item marked out of stock in live DB fails Gate 6 as OUT_OF_STOCK."""
    seed_catalog(db_session)
    priv = get_merchant_private_key("merchant_cakehouse_01")

    # Mark SKU as out of stock in database
    db_session.query(CatalogItem).filter_by(
        merchant_id="merchant_cakehouse_01", sku="CAKE-CHOC-001"
    ).update({"in_stock": False})
    db_session.commit()

    cart, cart_jwt = sign_cart(
        merchant_id="merchant_cakehouse_01",
        line_items_req=[{"sku": "CAKE-CHOC-001", "quantity": 1}],
        merchant_private_key_pem=priv,
        db=db_session,
    )

    quote = MerchantQuote(
        merchant_id="merchant_cakehouse_01",
        cart_jwt=cart_jwt,
        signed_cart=cart,
        total_paise=cart.total_paise,
    )

    classified = verify_and_classify_quotes([quote], base_intent, db=db_session)
    assert classified[0].status == QuoteStatus.OUT_OF_STOCK
    assert "out of stock" in classified[0].rejection_reason


def test_quote_verification_immutability_contract(db_session, base_intent):
    """verify_and_classify_quotes preserves input quote immutability (Patch 2)."""
    seed_catalog(db_session)
    priv = get_merchant_private_key("merchant_cakehouse_01")

    cart, cart_jwt = sign_cart(
        merchant_id="merchant_cakehouse_01",
        line_items_req=[{"sku": "CAKE-CHOC-001", "quantity": 1}],
        merchant_private_key_pem=priv,
        db=db_session,
    )

    original_quote = MerchantQuote(
        merchant_id="merchant_cakehouse_01",
        cart_jwt=cart_jwt,
        signed_cart=cart,
        total_paise=cart.total_paise,
        status=QuoteStatus.ELIGIBLE,
        verified_at=None,
    )

    input_list = [original_quote]
    classified = verify_and_classify_quotes(input_list, base_intent, db=db_session)

    # Returned list is a distinct object
    assert classified is not input_list
    assert classified[0] is not original_quote

    # Original quote instance was not modified
    assert original_quote.verified_at is None
    assert classified[0].verified_at is not None


def test_candidate_quote_response_omits_raw_jwt(db_session):
    """CandidateQuoteResponse exposes only safe metadata and omits raw JWTs (ADR-002 / Patch 1)."""
    seed_catalog(db_session)
    priv = get_merchant_private_key("merchant_cakehouse_01")

    cart, cart_jwt = sign_cart(
        merchant_id="merchant_cakehouse_01",
        line_items_req=[{"sku": "CAKE-CHOC-001", "quantity": 1}],
        merchant_private_key_pem=priv,
        db=db_session,
    )

    quote = MerchantQuote(
        merchant_id="merchant_cakehouse_01",
        cart_jwt=cart_jwt,
        signed_cart=cart,
        total_paise=94000,
        status=QuoteStatus.ELIGIBLE,
    )

    # 1. Non-winner projection with delta calculation
    response_runner_up = CandidateQuoteResponse.from_merchant_quote(
        quote=quote,
        is_winner=False,
        winner_total_paise=89000,
    )
    dumped = response_runner_up.model_dump()

    # Verify no raw JWT field exists
    assert "cart_jwt" not in dumped
    assert "jwt" not in dumped

    # Verify safe fields
    assert dumped["merchant_id"] == "merchant_cakehouse_01"
    assert dumped["total_paise"] == 94000
    assert dumped["status"] == QuoteStatus.ELIGIBLE
    assert dumped["is_winner"] is False
    assert dumped["price_delta_paise"] == 5000  # 94000 - 89000
    assert len(dumped["line_items_summary"]) == 1

    # 2. Winner projection
    response_winner = CandidateQuoteResponse.from_merchant_quote(
        quote=quote,
        is_winner=True,
        winner_total_paise=94000,
    )
    assert response_winner.is_winner is True
    assert response_winner.price_delta_paise is None
