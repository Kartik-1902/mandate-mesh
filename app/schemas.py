"""Pydantic schemas and cryptographic payload models."""

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4
from pydantic import BaseModel, Field, field_validator


class UserIntentCredential(BaseModel):
    """User-signed spending authorization credential."""
    intent_id: UUID = Field(default_factory=uuid4)
    user_id: str
    spend_cap_paise: int = Field(gt=0, description="Hard spend ceiling in paise")
    currency: Literal["INR"] = "INR"
    allowed_categories: list[str] = Field(min_length=1)
    allowed_merchant_ids: list[str] = Field(min_length=1)
    max_transactions: int = Field(default=1, ge=1)
    nonce: str = Field(
        description="JWT-issuance nonce. Proves freshness and prevents replay across intents."
    )
    not_before: datetime
    expires_at: datetime

    @field_validator("expires_at")
    @classmethod
    def _validate_window(cls, v: datetime, info) -> datetime:
        nb = info.data.get("not_before")
        if nb and v <= nb:
            raise ValueError("expires_at must be strictly after not_before")
        return v


class CartLineItem(BaseModel):
    """Item within a merchant-signed cart."""
    sku: str
    name: str
    category: str
    unit_price_paise: int = Field(gt=0)
    quantity: int = Field(gt=0)

    @property
    def line_total_paise(self) -> int:
        return self.unit_price_paise * self.quantity


class MerchantSignedCart(BaseModel):
    """Merchant-priced and signed cart quote."""
    cart_id: UUID = Field(default_factory=uuid4)
    merchant_id: str
    line_items: list[CartLineItem] = Field(min_length=1)
    tax_paise: int = Field(default=0, ge=0)
    currency: Literal["INR"] = "INR"
    cart_hash: str = Field(
        description="SHA-256 content hash computed over line items, tax, total, and merchant_id"
    )
    issued_at: datetime
    expires_at: datetime

    @property
    def subtotal_paise(self) -> int:
        return sum(li.line_total_paise for li in self.line_items)

    @property
    def total_paise(self) -> int:
        return self.subtotal_paise + self.tax_paise


class PaymentMandate(BaseModel):
    """IMMUTABLE cryptographic authorization snapshot.
    Signed once by the platform key; never re-signed.
    Mutable runtime fields (status, razorpay_order_id) live in MandateRecord."""
    mandate_id: UUID = Field(default_factory=uuid4)
    intent_id: str = Field(description="Intent this mandate was authorized under")
    intent_hash: str = Field(description="Canonical SHA-256 hash of UserIntentCredential")
    cart_hash: str = Field(description="Must match MerchantSignedCart.cart_hash")
    merchant_id: str
    authorized_amount_paise: int = Field(gt=0)
    currency: Literal["INR"] = "INR"
    created_at: datetime


class PaymentReceipt(BaseModel):
    """Platform-signed receipt confirming successful payment capture."""
    receipt_id: UUID = Field(default_factory=uuid4)
    mandate_id: UUID
    intent_hash: str
    cart_hash: str
    razorpay_order_id: str
    razorpay_payment_id: str
    amount_captured_paise: int = Field(gt=0)
    captured_at: datetime
    currency: Literal["INR"] = "INR"
