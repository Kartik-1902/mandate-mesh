"""Phase 0: Tests for Pydantic schemas, validation invariants, and error hierarchy."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from pydantic import ValidationError

from app.schemas import (
    UserIntentCredential,
    CartLineItem,
    MerchantSignedCart,
    PaymentMandate,
    PaymentReceipt,
)
from app.errors import (
    PolicyViolation,
    PolicySpendCapExceeded,
    PolicyCategoryNotAllowed,
    PolicyMerchantNotAllowed,
    PolicyIntentExpired,
    PolicyIntentNotYetValid,
    PolicyTransactionLimitReached,
    PolicyReplayDetected,
    PolicyCartExpired,
    PolicyCartSignatureInvalid,
    PolicyCartHashMismatch,
    CatalogSkuNotFound,
)


# =============================================================================
# UserIntentCredential Tests
# =============================================================================

def test_user_intent_valid_instantiation():
    now = datetime.now(timezone.utc)
    intent = UserIntentCredential(
        user_id="user_123",
        spend_cap_paise=150000,
        allowed_categories=["bakery", "gifting"],
        allowed_merchant_ids=["merchant_cakehouse_01"],
        max_transactions=3,
        nonce="test_nonce_abc123",
        not_before=now,
        expires_at=now + timedelta(hours=1),
    )
    assert intent.spend_cap_paise == 150000
    assert intent.currency == "INR"
    assert intent.max_transactions == 3
    assert intent.nonce == "test_nonce_abc123"


def test_user_intent_invalid_spend_cap_rejected():
    now = datetime.now(timezone.utc)
    with pytest.raises(ValidationError):
        UserIntentCredential(
            user_id="user_123",
            spend_cap_paise=0,  # Must be > 0
            allowed_categories=["bakery"],
            allowed_merchant_ids=["merchant_01"],
            nonce="nonce_123",
            not_before=now,
            expires_at=now + timedelta(hours=1),
        )


def test_user_intent_invalid_time_window_rejected():
    now = datetime.now(timezone.utc)
    with pytest.raises(ValidationError, match="expires_at must be strictly after not_before"):
        UserIntentCredential(
            user_id="user_123",
            spend_cap_paise=10000,
            allowed_categories=["bakery"],
            allowed_merchant_ids=["merchant_01"],
            nonce="nonce_123",
            not_before=now + timedelta(hours=1),
            expires_at=now,  # expires before not_before
        )


def test_user_intent_empty_categories_or_merchants_rejected():
    now = datetime.now(timezone.utc)
    with pytest.raises(ValidationError):
        UserIntentCredential(
            user_id="user_123",
            spend_cap_paise=10000,
            allowed_categories=[],  # min_length=1
            allowed_merchant_ids=["merchant_01"],
            nonce="nonce_123",
            not_before=now,
            expires_at=now + timedelta(hours=1),
        )


# =============================================================================
# Cart Schemas Tests
# =============================================================================

def test_cart_line_item_math():
    item = CartLineItem(
        sku="CAKE-CHOC-001",
        name="Chocolate Truffle Cake (1kg)",
        category="bakery",
        unit_price_paise=94000,
        quantity=2,
    )
    assert item.line_total_paise == 188000


def test_merchant_signed_cart_totals():
    now = datetime.now(timezone.utc)
    item1 = CartLineItem(sku="SKU1", name="Cake", category="bakery", unit_price_paise=50000, quantity=1)
    item2 = CartLineItem(sku="SKU2", name="Candle", category="gifting", unit_price_paise=10000, quantity=2)

    cart = MerchantSignedCart(
        merchant_id="merchant_01",
        line_items=[item1, item2],
        tax_paise=5000,
        currency="INR",
        cart_hash="sha256_mock_hash",
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    assert cart.subtotal_paise == 70000
    assert cart.total_paise == 75000


# =============================================================================
# PaymentMandate & PaymentReceipt Invariant Tests
# =============================================================================

def test_mandate_schema_has_no_status_or_razorpay_fields():
    """PaymentMandate JWT is an immutable authorization credential.
    Mutable runtime state (status, order IDs) must NOT exist on the schema."""
    field_names = PaymentMandate.model_fields.keys()
    assert "status" not in field_names
    assert "razorpay_order_id" not in field_names
    assert "razorpay_payment_id" not in field_names

    now = datetime.now(timezone.utc)
    mandate = PaymentMandate(
        intent_id=str(uuid4()),
        intent_hash="intent_hash_abc",
        cart_hash="cart_hash_def",
        merchant_id="merchant_01",
        authorized_amount_paise=94000,
        created_at=now,
    )
    assert mandate.authorized_amount_paise == 94000
    assert mandate.currency == "INR"


def test_payment_receipt_instantiation():
    now = datetime.now(timezone.utc)
    receipt = PaymentReceipt(
        mandate_id=uuid4(),
        intent_hash="intent_hash_abc",
        cart_hash="cart_hash_def",
        razorpay_order_id="order_12345",
        razorpay_payment_id="pay_67890",
        amount_captured_paise=94000,
        captured_at=now,
    )
    assert receipt.amount_captured_paise == 94000
    assert receipt.razorpay_order_id == "order_12345"


# =============================================================================
# Error Hierarchy Tests
# =============================================================================

def test_policy_violation_error_hierarchy():
    err = PolicySpendCapExceeded("Cart total exceeds spend cap", details={"spend_cap_paise": 150000})
    assert isinstance(err, PolicyViolation)
    assert err.code == "POLICY_SPEND_CAP_EXCEEDED"
    assert err.http_status == 403
    assert err.to_dict()["error_code"] == "POLICY_SPEND_CAP_EXCEEDED"
    assert err.to_dict()["spend_cap_paise"] == 150000

    err_cat = PolicyCategoryNotAllowed("Category not permitted")
    assert err_cat.http_status == 403
    assert err_cat.code == "POLICY_CATEGORY_NOT_ALLOWED"

    err_replay = PolicyReplayDetected("Transaction already processed")
    assert err_replay.http_status == 409
    assert err_replay.code == "POLICY_REPLAY_DETECTED"

    err_sku = CatalogSkuNotFound("FAKE-SKU")
    assert err_sku.http_status == 404
    assert err_sku.code == "CATALOG_SKU_NOT_FOUND"
