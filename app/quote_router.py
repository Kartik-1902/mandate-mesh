"""Deterministic Trust-Aware Multi-Merchant Quote Router (Milestone M3 / ADR-008).

Core Invariants:
1. The LLM proposes candidate product selections; deterministic Python disposes.
2. An unauthorized rupee can never move because of an LLM decision.
3. Immutability Contract (Patch 2): verify_and_classify_quotes treats input quotes
   as immutable and returns fresh classified MerchantQuote instances.
4. Fail-closed key resolution: Unknown merchant identities fail closed without crashing.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence
from sqlalchemy.orm import Session

from app.crypto import compute_cart_hash, verify_cart_jwt
from app.errors import (
    PolicyCartExpired,
    PolicyCartHashMismatch,
    PolicyCartSignatureInvalid,
)
from app.merchant_keys import MerchantKeyNotFound, get_merchant_public_key
from app.models import CatalogItem
from app.schemas import UserIntentCredential
from app.schemas_routing import MerchantQuote, QuoteStatus


def verify_and_classify_quotes(
    quotes: Sequence[MerchantQuote],
    intent: UserIntentCredential,
    db: Session | None = None,
    now: datetime | None = None,
) -> list[MerchantQuote]:
    """Deterministically verifies and classifies candidate merchant quotes against 7 gates.

    Immutability Contract (Patch 2):
    This function does NOT mutate input quotes in-place. It returns a new list of
    MerchantQuote instances with populated status, rejection_reason, and verified_at fields.

    Args:
        quotes: Sequence of candidate merchant quotes.
        intent: UserIntentCredential holding authorized merchants and spend cap.
        db: Optional SQLAlchemy database session for live stock validation.
        now: Optional reference timestamp (defaults to UTC now).

    Returns:
        list[MerchantQuote]: New collection of classified merchant quotes.
    """
    current_time = now or datetime.now(timezone.utc)
    classified: list[MerchantQuote] = []

    for q in quotes:
        status = QuoteStatus.ELIGIBLE
        rejection_reason: str | None = None

        # Gate 1: Merchant Allowlist Authorization
        if q.merchant_id not in intent.allowed_merchant_ids:
            status = QuoteStatus.MERCHANT_UNAUTHORIZED
            rejection_reason = (
                f"Merchant '{q.merchant_id}' is not in authorized merchant allowlist "
                f"{intent.allowed_merchant_ids}"
            )

        # Gate 2: Cryptographic Key Resolution & ES256 Signature Verification
        if status == QuoteStatus.ELIGIBLE:
            try:
                pub_key = get_merchant_public_key(q.merchant_id)
            except MerchantKeyNotFound:
                status = QuoteStatus.MERCHANT_KEY_UNAVAILABLE
                rejection_reason = f"No trusted public key registered for merchant '{q.merchant_id}'"
            except Exception as e:
                status = QuoteStatus.MERCHANT_UNAVAILABLE
                rejection_reason = f"Failed to load merchant key: {e}"

            if status == QuoteStatus.ELIGIBLE:
                try:
                    verify_cart_jwt(q.cart_jwt, pub_key)
                except PolicyCartSignatureInvalid:
                    status = QuoteStatus.INVALID_SIGNATURE
                    rejection_reason = "Cart JWT cryptographic signature is invalid or forged."
                except PolicyCartExpired:
                    status = QuoteStatus.QUOTE_EXPIRED
                    rejection_reason = f"Cart JWT expired at {q.signed_cart.expires_at.isoformat()}."
                except PolicyCartHashMismatch:
                    status = QuoteStatus.CART_HASH_MISMATCH
                    rejection_reason = "Cart JWT payload hash does not match embedded cart_hash."
                except Exception as e:
                    status = QuoteStatus.INVALID_SIGNATURE
                    rejection_reason = f"Cryptographic verification error: {e}"

        # Gate 3: Canonical SHA-256 Cart Hash Integrity
        if status == QuoteStatus.ELIGIBLE:
            computed_hash = compute_cart_hash(q.signed_cart)
            if computed_hash != q.signed_cart.cart_hash:
                status = QuoteStatus.CART_HASH_MISMATCH
                rejection_reason = (
                    f"Canonical cart hash mismatch: computed '{computed_hash}' "
                    f"!= embedded '{q.signed_cart.cart_hash}'."
                )

        # Gate 4: Time Window Expiry (TTL Window)
        if status == QuoteStatus.ELIGIBLE:
            if current_time > q.signed_cart.expires_at:
                status = QuoteStatus.QUOTE_EXPIRED
                rejection_reason = f"Quote expired at {q.signed_cart.expires_at.isoformat()}."

        # Gate 5: Currency Alignment
        if status == QuoteStatus.ELIGIBLE:
            if q.signed_cart.currency != "INR" or q.currency != "INR":
                status = QuoteStatus.CURRENCY_MISMATCH
                rejection_reason = (
                    f"Unsupported cart currency '{q.signed_cart.currency}' (expected 'INR')."
                )

        # Gate 6: Live Catalog Stock Check
        if status == QuoteStatus.ELIGIBLE and db is not None:
            for item in q.signed_cart.line_items:
                catalog_row = (
                    db.query(CatalogItem)
                    .filter_by(merchant_id=q.merchant_id, sku=item.sku)
                    .first()
                )
                if not catalog_row:
                    status = QuoteStatus.OUT_OF_STOCK
                    rejection_reason = (
                        f"Item SKU '{item.sku}' not found in catalog for merchant '{q.merchant_id}'."
                    )
                    break
                elif not catalog_row.in_stock:
                    status = QuoteStatus.OUT_OF_STOCK
                    rejection_reason = (
                        f"Item SKU '{item.sku}' is currently out of stock at merchant '{q.merchant_id}'."
                    )
                    break

        # Gate 7: User Spend Cap Ceiling
        if status == QuoteStatus.ELIGIBLE:
            if q.total_paise > intent.spend_cap_paise:
                status = QuoteStatus.SPEND_CAP_EXCEEDED
                rejection_reason = (
                    f"Quote total of ₹{q.total_paise / 100:.2f} ({q.total_paise} paise) "
                    f"exceeds authorized spend cap of ₹{intent.spend_cap_paise / 100:.2f} "
                    f"({intent.spend_cap_paise} paise)."
                )

        # Return fresh copy ensuring immutability (Patch 2)
        classified.append(
            q.model_copy(
                update={
                    "status": status,
                    "rejection_reason": rejection_reason,
                    "verified_at": current_time,
                }
            )
        )

    return classified
