"""Phase 1: Unit tests for Cryptographic Trust Layer (app/crypto.py)."""

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
import jwt

from app.crypto import (
    canonical_json,
    compute_cart_hash,
    compute_intent_hash,
    compute_mandate_hash,
    generate_es256_keypair,
    hash_object,
    issue_cart_jwt,
    issue_intent_jwt,
    issue_mandate_jwt,
    issue_receipt_jwt,
    sha256_hex,
    verify_cart_jwt,
    verify_intent_jwt,
    verify_mandate_jwt,
    verify_receipt_jwt,
)
from app.errors import (
    PolicyCartExpired,
    PolicyCartHashMismatch,
    PolicyCartSignatureInvalid,
    PolicyIntentExpired,
    PolicyIntentNotYetValid,
    PolicyViolation,
)
from app.schemas import (
    CartLineItem,
    MerchantSignedCart,
    PaymentMandate,
    PaymentReceipt,
    UserIntentCredential,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def user_keys():
    return generate_es256_keypair()


@pytest.fixture
def merchant_keys():
    return generate_es256_keypair()


@pytest.fixture
def platform_keys():
    return generate_es256_keypair()


# =============================================================================
# 1. Canonical Serialization & Hashing Tests
# =============================================================================

def test_canonical_json_deterministic_ordering():
    dict1 = {"b": 2, "a": 1, "c": {"y": 20, "x": 10}}
    dict2 = {"a": 1, "c": {"x": 10, "y": 20}, "b": 2}

    bytes1 = canonical_json(dict1)
    bytes2 = canonical_json(dict2)

    assert bytes1 == bytes2
    assert bytes1 == b'{"a":1,"b":2,"c":{"x":10,"y":20}}'
    assert sha256_hex(bytes1) == sha256_hex(bytes2)


def test_compute_cart_hash_deterministic():
    now = datetime.now(timezone.utc)
    cart_id = uuid4()
    item = CartLineItem(sku="CAKE-01", name="Cake", category="bakery", unit_price_paise=94000, quantity=1)

    cart1 = MerchantSignedCart(
        cart_id=cart_id,
        merchant_id="merchant_01",
        line_items=[item],
        tax_paise=0,
        currency="INR",
        cart_hash="",
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    cart2 = MerchantSignedCart(
        cart_id=cart_id,
        merchant_id="merchant_01",
        line_items=[item],
        tax_paise=0,
        currency="INR",
        cart_hash="arbitrary_ignored_hash",
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
    )

    hash1 = compute_cart_hash(cart1)
    hash2 = compute_cart_hash(cart2)

    assert hash1 == hash2
    assert len(hash1) == 64


def test_compute_intent_hash_deterministic():
    now = datetime.now(timezone.utc)
    intent_id = uuid4()

    intent = UserIntentCredential(
        intent_id=intent_id,
        user_id="user_123",
        spend_cap_paise=150000,
        allowed_categories=["gifting", "bakery"],
        allowed_merchant_ids=["m_02", "m_01"],
        max_transactions=2,
        nonce="nonce_test",
        not_before=now,
        expires_at=now + timedelta(hours=1),
    )

    h1 = compute_intent_hash(intent)
    h2 = compute_intent_hash(intent)

    assert h1 == h2
    assert len(h1) == 64


# =============================================================================
# 2. UserIntentCredential Signing & Verification Tests
# =============================================================================

def test_intent_sign_verify_roundtrip(user_keys):
    priv, pub = user_keys
    now = datetime.now(timezone.utc)

    intent = UserIntentCredential(
        user_id="user_7a1b2c",
        spend_cap_paise=150000,
        allowed_categories=["bakery", "gifting"],
        allowed_merchant_ids=["merchant_cakehouse_01"],
        max_transactions=3,
        nonce="3f9a7c1e8b2d4f6a",
        not_before=now,
        expires_at=now + timedelta(hours=1),
    )

    token = issue_intent_jwt(intent, priv, kid="user_7a1b2c:key-1")
    decoded = verify_intent_jwt(token, pub)

    assert decoded.intent_id == intent.intent_id
    assert decoded.user_id == intent.user_id
    assert decoded.spend_cap_paise == 150000
    assert decoded.max_transactions == 3
    assert decoded.nonce == "3f9a7c1e8b2d4f6a"
    assert decoded.allowed_categories == ["bakery", "gifting"]


def test_intent_tampered_payload_rejected(user_keys):
    priv, pub = user_keys
    now = datetime.now(timezone.utc)

    intent = UserIntentCredential(
        user_id="user_1",
        spend_cap_paise=10000,
        allowed_categories=["bakery"],
        allowed_merchant_ids=["m1"],
        nonce="nonce1",
        not_before=now,
        expires_at=now + timedelta(hours=1),
    )
    token = issue_intent_jwt(intent, priv)

    # Manually tamper with the payload part of the JWT
    header_b64, payload_b64, sig_b64 = token.split(".")
    import base64
    payload_json = base64.urlsafe_b64decode(payload_b64 + "==").decode("utf-8")
    tampered_dict = json.loads(payload_json)
    tampered_dict["spend_cap_paise"] = 99999999  # Attacker increases cap
    tampered_payload_b64 = base64.urlsafe_b64encode(json.dumps(tampered_dict).encode("utf-8")).decode("utf-8").rstrip("=")
    tampered_token = f"{header_b64}.{tampered_payload_b64}.{sig_b64}"

    with pytest.raises(PolicyViolation, match="POLICY_INTENT_SIGNATURE_INVALID"):
        verify_intent_jwt(tampered_token, pub)


def test_intent_wrong_key_rejected(user_keys, merchant_keys):
    user_priv, _ = user_keys
    _, merchant_pub = merchant_keys
    now = datetime.now(timezone.utc)

    intent = UserIntentCredential(
        user_id="user_1",
        spend_cap_paise=10000,
        allowed_categories=["bakery"],
        allowed_merchant_ids=["m1"],
        nonce="nonce1",
        not_before=now,
        expires_at=now + timedelta(hours=1),
    )
    token = issue_intent_jwt(intent, user_priv)

    # Verifying user intent with merchant public key must fail
    with pytest.raises(PolicyViolation, match="POLICY_INTENT_SIGNATURE_INVALID"):
        verify_intent_jwt(token, merchant_pub)


def test_intent_expired_rejected(user_keys):
    priv, pub = user_keys
    now = datetime.now(timezone.utc)

    intent = UserIntentCredential(
        user_id="user_1",
        spend_cap_paise=10000,
        allowed_categories=["bakery"],
        allowed_merchant_ids=["m1"],
        nonce="nonce1",
        not_before=now - timedelta(hours=2),
        expires_at=now - timedelta(hours=1),  # Expired in past
    )
    token = issue_intent_jwt(intent, priv)

    with pytest.raises(PolicyIntentExpired):
        verify_intent_jwt(token, pub)


def test_intent_future_nbf_rejected(user_keys):
    priv, pub = user_keys
    now = datetime.now(timezone.utc)

    intent = UserIntentCredential(
        user_id="user_1",
        spend_cap_paise=10000,
        allowed_categories=["bakery"],
        allowed_merchant_ids=["m1"],
        nonce="nonce1",
        not_before=now + timedelta(hours=1),  # In future
        expires_at=now + timedelta(hours=2),
    )
    token = issue_intent_jwt(intent, priv)

    with pytest.raises(PolicyIntentNotYetValid):
        verify_intent_jwt(token, pub)


# =============================================================================
# 3. MerchantSignedCart Signing & Verification Tests
# =============================================================================

def test_cart_sign_verify_roundtrip(merchant_keys):
    priv, pub = merchant_keys
    now = datetime.now(timezone.utc)

    item = CartLineItem(sku="CAKE-CHOC-001", name="Chocolate Truffle Cake", category="bakery", unit_price_paise=94000, quantity=1)
    cart = MerchantSignedCart(
        merchant_id="merchant_cakehouse_01",
        line_items=[item],
        tax_paise=0,
        currency="INR",
        cart_hash="",
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    cart.cart_hash = compute_cart_hash(cart)

    token = issue_cart_jwt(cart, priv, kid="merchant_cakehouse_01:key-1")
    decoded = verify_cart_jwt(token, pub)

    assert decoded.cart_id == cart.cart_id
    assert decoded.merchant_id == "merchant_cakehouse_01"
    assert decoded.total_paise == 94000
    assert decoded.cart_hash == cart.cart_hash


def test_cart_tampered_hash_blocked(merchant_keys):
    """Attack 3: Altering line items or cart total causes signature and hash verification failure."""
    priv, pub = merchant_keys
    now = datetime.now(timezone.utc)

    item = CartLineItem(sku="CAKE-01", name="Cake", category="bakery", unit_price_paise=94000, quantity=1)
    cart = MerchantSignedCart(
        merchant_id="merchant_01",
        line_items=[item],
        tax_paise=0,
        currency="INR",
        cart_hash="",
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    cart.cart_hash = compute_cart_hash(cart)
    token = issue_cart_jwt(cart, priv)

    header_b64, payload_b64, sig_b64 = token.split(".")
    import base64
    payload_dict = json.loads(base64.urlsafe_b64decode(payload_b64 + "==").decode("utf-8"))
    payload_dict["total_paise"] = 140000  # Tampered total
    tampered_payload_b64 = base64.urlsafe_b64encode(json.dumps(payload_dict).encode("utf-8")).decode("utf-8").rstrip("=")
    tampered_token = f"{header_b64}.{tampered_payload_b64}.{sig_b64}"

    with pytest.raises(PolicyCartSignatureInvalid):
        verify_cart_jwt(tampered_token, pub)


def test_cart_expired_rejected(merchant_keys):
    priv, pub = merchant_keys
    now = datetime.now(timezone.utc)

    item = CartLineItem(sku="CAKE-01", name="Cake", category="bakery", unit_price_paise=94000, quantity=1)
    cart = MerchantSignedCart(
        merchant_id="merchant_01",
        line_items=[item],
        tax_paise=0,
        currency="INR",
        cart_hash="",
        issued_at=now - timedelta(minutes=10),
        expires_at=now - timedelta(minutes=5),  # 5-minute TTL expired
    )
    cart.cart_hash = compute_cart_hash(cart)
    token = issue_cart_jwt(cart, priv)

    with pytest.raises(PolicyCartExpired):
        verify_cart_jwt(token, pub)


# =============================================================================
# 4. PaymentMandate & PaymentReceipt Platform Signing Tests
# =============================================================================

def test_mandate_sign_verify_roundtrip(platform_keys):
    priv, pub = platform_keys
    now = datetime.now(timezone.utc)

    mandate = PaymentMandate(
        intent_id=str(uuid4()),
        intent_hash="intent_hash_123",
        cart_hash="cart_hash_456",
        merchant_id="merchant_01",
        authorized_amount_paise=94000,
        currency="INR",
        created_at=now,
    )

    token = issue_mandate_jwt(mandate, priv, kid="platform:key-1")
    decoded = verify_mandate_jwt(token, pub)

    assert decoded.mandate_id == mandate.mandate_id
    assert decoded.authorized_amount_paise == 94000
    assert decoded.cart_hash == "cart_hash_456"


def test_mandate_jwt_claims_have_no_status_or_razorpay_order_id(platform_keys):
    """Verifies that raw decoded JWT claims for PaymentMandate omit mutable runtime fields."""
    priv, pub = platform_keys
    now = datetime.now(timezone.utc)

    mandate = PaymentMandate(
        intent_id=str(uuid4()),
        intent_hash="intent_hash_123",
        cart_hash="cart_hash_456",
        merchant_id="merchant_01",
        authorized_amount_paise=94000,
        created_at=now,
    )

    token = issue_mandate_jwt(mandate, priv)
    raw_claims = jwt.decode(token, pub, algorithms=["ES256"])

    assert "status" not in raw_claims
    assert "razorpay_order_id" not in raw_claims
    assert "razorpay_payment_id" not in raw_claims


def test_receipt_chains_mandate_id_and_razorpay_ids(platform_keys):
    priv, pub = platform_keys
    now = datetime.now(timezone.utc)
    mandate_id = uuid4()

    receipt = PaymentReceipt(
        mandate_id=mandate_id,
        intent_hash="intent_hash_123",
        cart_hash="cart_hash_456",
        razorpay_order_id="order_QWXYZ789",
        razorpay_payment_id="pay_ABC123",
        amount_captured_paise=94000,
        captured_at=now,
    )

    token = issue_receipt_jwt(receipt, priv, kid="platform:key-1")
    decoded = verify_receipt_jwt(token, pub)

    assert decoded.receipt_id == receipt.receipt_id
    assert decoded.mandate_id == mandate_id
    assert decoded.razorpay_order_id == "order_QWXYZ789"
    assert decoded.razorpay_payment_id == "pay_ABC123"
    assert decoded.amount_captured_paise == 94000
