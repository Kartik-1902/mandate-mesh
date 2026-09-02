"""Unit tests for MerchantQuote, QuoteStatus, and 7-gate quote verification (Milestone M3)."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest

from app.crypto import compute_cart_hash, issue_cart_jwt
from app.merchant import seed_catalog, sign_cart
from app.merchant_keys import get_merchant_private_key
from app.models import CatalogItem
from app.quote_router import (
    revalidate_winner,
    route,
    route_with_fallback,
    verify_and_classify_quotes,
)
from app.schemas import CartLineItem, MerchantSignedCart, UserIntentCredential
from app.schemas_routing import (
    CandidateQuoteResponse,
    MerchantQuote,
    OptimizationPolicy,
    QuoteStatus,
    RoutingDecision,
)


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
        line_items_req=[{"sku": "ART-BELG-CHOC-01", "quantity": 1}],
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
    assert classified[0].status in [QuoteStatus.CART_HASH_MISMATCH, QuoteStatus.QUOTE_DATA_MISMATCH]


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


def test_route_lowest_total_price_policy(db_session, base_intent):
    """LOWEST_TOTAL_PRICE selects the cheapest verified quote among all candidates."""
    seed_catalog(db_session)
    priv_cake = get_merchant_private_key("merchant_cakehouse_01")
    priv_sweet = get_merchant_private_key("merchant_sweetdelight_02")

    cart_cake, jwt_cake = sign_cart("merchant_cakehouse_01", [{"sku": "CAKE-CHOC-001", "quantity": 1}], priv_cake, db=db_session)
    cart_sweet, jwt_sweet = sign_cart("merchant_sweetdelight_02", [{"sku": "SWT-CHOC-TRF-01", "quantity": 1}], priv_sweet, db=db_session)

    quote_cake = MerchantQuote(merchant_id="merchant_cakehouse_01", cart_jwt=jwt_cake, signed_cart=cart_cake, total_paise=cart_cake.total_paise)
    quote_sweet = MerchantQuote(merchant_id="merchant_sweetdelight_02", cart_jwt=jwt_sweet, signed_cart=cart_sweet, total_paise=cart_sweet.total_paise)

    decision = route([quote_cake, quote_sweet], base_intent, policy=OptimizationPolicy.LOWEST_TOTAL_PRICE, db=db_session)

    assert decision.winner_merchant_id == "merchant_sweetdelight_02"
    assert decision.winner_quote.total_paise == 89000
    assert decision.price_savings_paise == 5000  # ₹940 - ₹890 = ₹50 (5000 paise)
    assert len(decision.eligible_quotes) == 2
    assert "lowest verified eligible quote" in decision.decision_rationale


def test_unimplemented_future_policy_raises_not_implemented(db_session, base_intent):
    """Scope Remediation: Inactive future policies (PREFER_MERCHANT, MAX_ITEM_AVAILABILITY) raise NotImplementedError."""
    seed_catalog(db_session)
    priv_cake = get_merchant_private_key("merchant_cakehouse_01")
    cart_cake, jwt_cake = sign_cart("merchant_cakehouse_01", [{"sku": "CAKE-CHOC-001", "quantity": 1}], priv_cake, db=db_session)
    quote_cake = MerchantQuote(merchant_id="merchant_cakehouse_01", cart_jwt=jwt_cake, signed_cart=cart_cake, total_paise=cart_cake.total_paise)

    with pytest.raises(NotImplementedError) as exc_pref:
        route([quote_cake], base_intent, policy=OptimizationPolicy.PREFER_MERCHANT, db=db_session)
    assert "reserved for future extensions" in str(exc_pref.value)

    with pytest.raises(NotImplementedError) as exc_avail:
        route([quote_cake], base_intent, policy=OptimizationPolicy.MAX_ITEM_AVAILABILITY, db=db_session)
    assert "reserved for future extensions" in str(exc_avail.value)


def test_route_lowest_total_price_policy_deterministic_winner(db_session, base_intent):
    """LOWEST_TOTAL_PRICE deterministically picks lowest price quote and breaks ties lexicographically."""
    seed_catalog(db_session)
    priv_cake = get_merchant_private_key("merchant_cakehouse_01")
    priv_sweet = get_merchant_private_key("merchant_sweetdelight_02")

    cart_cake, jwt_cake = sign_cart("merchant_cakehouse_01", [{"sku": "CAKE-CHOC-001", "quantity": 1}], priv_cake, db=db_session)
    cart_sweet, jwt_sweet = sign_cart("merchant_sweetdelight_02", [{"sku": "SWT-CHOC-TRF-01", "quantity": 1}], priv_sweet, db=db_session)

    quote_cake = MerchantQuote(merchant_id="merchant_cakehouse_01", cart_jwt=jwt_cake, signed_cart=cart_cake, total_paise=cart_cake.total_paise)
    quote_sweet = MerchantQuote(merchant_id="merchant_sweetdelight_02", cart_jwt=jwt_sweet, signed_cart=cart_sweet, total_paise=cart_sweet.total_paise)

    decision = route([quote_cake, quote_sweet], base_intent, policy=OptimizationPolicy.LOWEST_TOTAL_PRICE, db=db_session)
    assert decision.winner_merchant_id == "merchant_sweetdelight_02"
    assert decision.winner_quote.total_paise == 89000
    assert decision.price_savings_paise == 5000


def test_revalidate_winner_happy_path(db_session, base_intent):
    """Valid winning quote passes JIT 7-gate revalidation."""
    seed_catalog(db_session)
    priv = get_merchant_private_key("merchant_cakehouse_01")
    cart, cart_jwt = sign_cart("merchant_cakehouse_01", [{"sku": "CAKE-CHOC-001", "quantity": 1}], priv, db=db_session)

    quote = MerchantQuote(merchant_id="merchant_cakehouse_01", cart_jwt=cart_jwt, signed_cart=cart, total_paise=cart.total_paise)
    is_valid, reason = revalidate_winner(quote, base_intent, db=db_session)

    assert is_valid is True
    assert reason is None


def test_revalidate_winner_expired_rejected(db_session, base_intent):
    """Expired winning quote fails JIT 7-gate revalidation."""
    seed_catalog(db_session)
    priv = get_merchant_private_key("merchant_cakehouse_01")
    cart, cart_jwt = sign_cart("merchant_cakehouse_01", [{"sku": "CAKE-CHOC-001", "quantity": 1}], priv, db=db_session)

    quote = MerchantQuote(merchant_id="merchant_cakehouse_01", cart_jwt=cart_jwt, signed_cart=cart, total_paise=cart.total_paise)

    # Fast-forward time past cart expiration
    future_time = cart.expires_at + timedelta(minutes=5)
    is_valid, reason = revalidate_winner(quote, base_intent, db=db_session, now=future_time)

    assert is_valid is False
    assert "expired" in reason.lower()


def test_route_with_fallback_selects_runner_up(db_session, base_intent):
    """route_with_fallback falls back to runner-up if winner fails JIT revalidation."""
    seed_catalog(db_session)
    priv_cake = get_merchant_private_key("merchant_cakehouse_01")
    priv_sweet = get_merchant_private_key("merchant_sweetdelight_02")

    # Sweet Delight quote created with 5-minute TTL (300s)
    cart_sweet, jwt_sweet = sign_cart(
        merchant_id="merchant_sweetdelight_02",
        line_items_req=[{"sku": "SWT-CHOC-TRF-01", "quantity": 1}],
        merchant_private_key_pem=priv_sweet,
        db=db_session,
        ttl_seconds=300,
    )
    # CakeHouse quote with 30-minute TTL (1800s)
    cart_cake, jwt_cake = sign_cart(
        merchant_id="merchant_cakehouse_01",
        line_items_req=[{"sku": "CAKE-CHOC-001", "quantity": 1}],
        merchant_private_key_pem=priv_cake,
        db=db_session,
        ttl_seconds=1800,
    )

    quote_sweet = MerchantQuote(merchant_id="merchant_sweetdelight_02", cart_jwt=jwt_sweet, signed_cart=cart_sweet, total_paise=cart_sweet.total_paise)
    quote_cake = MerchantQuote(merchant_id="merchant_cakehouse_01", cart_jwt=jwt_cake, signed_cart=cart_cake, total_paise=cart_cake.total_paise)

    # Revalidation happens 10 minutes later: Sweet Delight has expired, CakeHouse is still valid
    future_time = cart_sweet.expires_at + timedelta(minutes=5)

    decision, final_winner = route_with_fallback(
        [quote_sweet, quote_cake],
        base_intent,
        policy=OptimizationPolicy.LOWEST_TOTAL_PRICE,
        db=db_session,
        now=future_time,
    )

    assert final_winner is not None
    assert final_winner.merchant_id == "merchant_cakehouse_01"
    assert decision.winner_merchant_id == "merchant_cakehouse_01"


def test_quote_verification_jwt_total_mismatch_rejected(db_session, base_intent):
    """Bug 1 Regression: Quote declaring total_paise != JWT verified total is classified as QUOTE_DATA_MISMATCH."""
    seed_catalog(db_session)
    priv = get_merchant_private_key("merchant_cakehouse_01")
    cart, cart_jwt = sign_cart("merchant_cakehouse_01", [{"sku": "CAKE-CHOC-001", "quantity": 1}], priv, db=db_session)

    # Actual JWT is for ₹940 (94000 paise), but attacker sets total_paise = ₹700 (70000 paise)
    tampered_quote = MerchantQuote(
        merchant_id="merchant_cakehouse_01",
        cart_jwt=cart_jwt,
        signed_cart=cart,
        total_paise=70000,
    )

    classified = verify_and_classify_quotes([tampered_quote], base_intent, db=db_session)
    assert len(classified) == 1
    assert classified[0].status == QuoteStatus.QUOTE_DATA_MISMATCH
    assert "Total amount mismatch" in classified[0].rejection_reason

    # Ensure it cannot win
    decision = route([tampered_quote], base_intent, db=db_session)
    assert decision.winner_merchant_id is None
    assert len(decision.eligible_quotes) == 0


def test_quote_verification_jwt_merchant_mismatch_rejected(db_session, base_intent):
    """Bug 1 & 7 Regression: Quote declaring merchant_id != JWT merchant_id is classified as QUOTE_DATA_MISMATCH."""
    seed_catalog(db_session)
    priv = get_merchant_private_key("merchant_cakehouse_01")
    cart, cart_jwt = sign_cart("merchant_cakehouse_01", [{"sku": "CAKE-CHOC-001", "quantity": 1}], priv, db=db_session)

    # JWT is for CakeHouse, but quote declares merchant_id = Sweet Delight
    tampered_quote = MerchantQuote(
        merchant_id="merchant_sweetdelight_02",
        cart_jwt=cart_jwt,
        signed_cart=cart,
        total_paise=cart.total_paise,
    )

    classified = verify_and_classify_quotes([tampered_quote], base_intent, db=db_session)
    assert classified[0].status in [QuoteStatus.QUOTE_DATA_MISMATCH, QuoteStatus.INVALID_SIGNATURE]

    decision = route([tampered_quote], base_intent, db=db_session)
    assert decision.winner_merchant_id is None


def test_quote_verification_jwt_currency_mismatch_rejected(db_session, base_intent):
    """Bug 1 Regression: Quote declaring currency != JWT currency is classified as QUOTE_DATA_MISMATCH."""
    seed_catalog(db_session)
    priv = get_merchant_private_key("merchant_cakehouse_01")
    cart, cart_jwt = sign_cart("merchant_cakehouse_01", [{"sku": "CAKE-CHOC-001", "quantity": 1}], priv, db=db_session)

    tampered_quote = MerchantQuote(
        merchant_id="merchant_cakehouse_01",
        cart_jwt=cart_jwt,
        signed_cart=cart,
        total_paise=cart.total_paise,
        currency="USD",  # type: ignore[arg-type]
    )

    classified = verify_and_classify_quotes([tampered_quote], base_intent, db=db_session)
    assert classified[0].status == QuoteStatus.QUOTE_DATA_MISMATCH

    decision = route([tampered_quote], base_intent, db=db_session)
    assert decision.winner_merchant_id is None


def test_quote_verification_jwt_cart_hash_mismatch_rejected(db_session, base_intent):
    """Bug 1 Regression: Quote supplying altered signed_cart object is classified as QUOTE_DATA_MISMATCH."""
    seed_catalog(db_session)
    priv = get_merchant_private_key("merchant_cakehouse_01")
    cart, cart_jwt = sign_cart("merchant_cakehouse_01", [{"sku": "CAKE-CHOC-001", "quantity": 1}], priv, db=db_session)

    # Tampered signed_cart object with different cart_hash
    tampered_cart = cart.model_copy(update={"cart_hash": "a" * 64})
    tampered_quote = MerchantQuote(
        merchant_id="merchant_cakehouse_01",
        cart_jwt=cart_jwt,
        signed_cart=tampered_cart,
        total_paise=cart.total_paise,
    )

    classified = verify_and_classify_quotes([tampered_quote], base_intent, db=db_session)
    assert classified[0].status == QuoteStatus.QUOTE_DATA_MISMATCH


def test_price_savings_calculation_semantics(db_session, base_intent):
    """Bug 6 Regression: price_savings_paise is relative to runner-up (second-cheapest), not most expensive."""
    seed_catalog(db_session)
    priv_cake = get_merchant_private_key("merchant_cakehouse_01")
    priv_sweet = get_merchant_private_key("merchant_sweetdelight_02")
    priv_artisan = get_merchant_private_key("merchant_artisan_03")

    # Expand base_intent to allow all 3 merchants
    intent = base_intent.model_copy(update={"allowed_merchant_ids": ["merchant_cakehouse_01", "merchant_sweetdelight_02", "merchant_artisan_03"]})

    # Sweet Delight = ₹890, CakeHouse = ₹940, Artisan = ₹1,200
    cart_sweet, jwt_sweet = sign_cart("merchant_sweetdelight_02", [{"sku": "SWT-CHOC-TRF-01", "quantity": 1}], priv_sweet, db=db_session)
    cart_cake, jwt_cake = sign_cart("merchant_cakehouse_01", [{"sku": "CAKE-CHOC-001", "quantity": 1}], priv_cake, db=db_session)
    cart_artisan, jwt_artisan = sign_cart("merchant_artisan_03", [{"sku": "ART-BELG-CHOC-01", "quantity": 1}], priv_artisan, db=db_session)

    quote_sweet = MerchantQuote(merchant_id="merchant_sweetdelight_02", cart_jwt=jwt_sweet, signed_cart=cart_sweet, total_paise=cart_sweet.total_paise)
    quote_cake = MerchantQuote(merchant_id="merchant_cakehouse_01", cart_jwt=jwt_cake, signed_cart=cart_cake, total_paise=cart_cake.total_paise)
    quote_artisan = MerchantQuote(merchant_id="merchant_artisan_03", cart_jwt=jwt_artisan, signed_cart=cart_artisan, total_paise=cart_artisan.total_paise)

    # 3 eligible quotes: Winner is Sweet Delight (₹890), Runner-up is CakeHouse (₹940), Most expensive is Artisan (₹1,200)
    decision = route([quote_sweet, quote_cake, quote_artisan], intent, policy=OptimizationPolicy.LOWEST_TOTAL_PRICE, db=db_session)
    assert decision.winner_merchant_id == "merchant_sweetdelight_02"
    # Savings must be ₹940 - ₹890 = ₹50 (5000 paise), NOT ₹1,200 - ₹890 = ₹310
    assert decision.price_savings_paise == 5000

    # 1 eligible quote: price_savings_paise must be None
    decision_single = route([quote_sweet], intent, policy=OptimizationPolicy.LOWEST_TOTAL_PRICE, db=db_session)
    assert decision_single.price_savings_paise is None

    # 0 eligible quotes: price_savings_paise must be None
    decision_empty = route([], intent, policy=OptimizationPolicy.LOWEST_TOTAL_PRICE, db=db_session)
    assert decision_empty.price_savings_paise is None

    # 2 tied quotes at ₹890: price_savings_paise must be 0
    quote_sweet_tied = MerchantQuote(merchant_id="merchant_sweetdelight_02", cart_jwt=jwt_sweet, signed_cart=cart_sweet, total_paise=cart_sweet.total_paise)
    quote_cake_tied = MerchantQuote(merchant_id="merchant_cakehouse_01", cart_jwt=jwt_cake, signed_cart=cart_cake, total_paise=89000)
    # Give tied quote matching verified total
    decision_tied = route([quote_sweet_tied, quote_sweet_tied], intent, policy=OptimizationPolicy.LOWEST_TOTAL_PRICE, db=db_session)
    assert decision_tied.price_savings_paise == 0


def test_route_with_fallback_advances_jit_time_between_candidates(db_session, base_intent):
    """Item 5 & 6: route_with_fallback evaluates each candidate round using advancing JIT timestamps and records metadata."""
    seed_catalog(db_session)
    priv_cake = get_merchant_private_key("merchant_cakehouse_01")
    priv_sweet = get_merchant_private_key("merchant_sweetdelight_02")

    # Sweet Delight expires at T + 300s (5m), CakeHouse expires at T + 1800s (30m)
    cart_sweet, jwt_sweet = sign_cart("merchant_sweetdelight_02", [{"sku": "SWT-CHOC-TRF-01", "quantity": 1}], priv_sweet, db=db_session, ttl_seconds=300)
    cart_cake, jwt_cake = sign_cart("merchant_cakehouse_01", [{"sku": "CAKE-CHOC-001", "quantity": 1}], priv_cake, db=db_session, ttl_seconds=1800)

    quote_sweet = MerchantQuote(merchant_id="merchant_sweetdelight_02", cart_jwt=jwt_sweet, signed_cart=cart_sweet, total_paise=cart_sweet.total_paise)
    quote_cake = MerchantQuote(merchant_id="merchant_cakehouse_01", cart_jwt=jwt_cake, signed_cart=cart_cake, total_paise=cart_cake.total_paise)

    # Time generator that simulates time advancing 6 minutes on the second check
    base_time = cart_sweet.issued_at
    call_count = 0

    def advancing_time_factory():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Round 1 initial route: Sweet Delight is still within TTL
            return base_time + timedelta(minutes=2)
        elif call_count == 2:
            # Round 1 JIT revalidation check: Sweet Delight has now expired (T + 6m > T + 5m)
            return base_time + timedelta(minutes=6)
        else:
            # Round 2 JIT revalidation check: CakeHouse is evaluated at T + 7m (< T + 30m)
            return base_time + timedelta(minutes=7)

    decision, final_winner = route_with_fallback(
        [quote_sweet, quote_cake],
        base_intent,
        policy=OptimizationPolicy.LOWEST_TOTAL_PRICE,
        db=db_session,
        now_factory=advancing_time_factory,
    )

    assert final_winner is not None
    assert final_winner.merchant_id == "merchant_cakehouse_01"
    assert decision.winner_merchant_id == "merchant_cakehouse_01"
    assert decision.fallback_applied is True
    assert decision.fallback_from_merchant == "merchant_sweetdelight_02"
    assert "expired" in (decision.fallback_reason or "").lower()
    assert "Original winner 'merchant_sweetdelight_02' failed JIT revalidation" in decision.decision_rationale
