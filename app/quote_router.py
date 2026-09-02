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
from typing import Any, Sequence
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
from app.schemas_routing import (
    MerchantQuote,
    OptimizationPolicy,
    QuoteStatus,
    RoutingDecision,
)


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
        status = q.status
        rejection_reason = q.rejection_reason
        verified_cart = None
        effective_cart = q.signed_cart
        effective_total = q.total_paise

        # If already classified as failed prior to verification (e.g. SKU_UNAVAILABLE or MERCHANT_KEY_UNAVAILABLE)
        if status != QuoteStatus.ELIGIBLE:
            classified.append(
                q.model_copy(
                    update={
                        "status": status,
                        "rejection_reason": rejection_reason,
                        "verified_at": current_time,
                    }
                )
            )
            continue

        # Gate 1: Merchant Allowlist Authorization
        if q.merchant_id not in intent.allowed_merchant_ids:
            status = QuoteStatus.MERCHANT_UNAUTHORIZED
            rejection_reason = (
                f"Merchant '{q.merchant_id}' is not in authorized merchant allowlist "
                f"{intent.allowed_merchant_ids}"
            )

        # Gate 2: Cryptographic Key Resolution & ES256 Signature Verification
        if status == QuoteStatus.ELIGIBLE:
            if not q.cart_jwt:
                status = QuoteStatus.INVALID_SIGNATURE
                rejection_reason = "Missing Cart JWT."
            else:
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
                        verified_cart = verify_cart_jwt(q.cart_jwt, pub_key)
                    except PolicyCartSignatureInvalid:
                        status = QuoteStatus.INVALID_SIGNATURE
                        rejection_reason = "Cart JWT cryptographic signature is invalid or forged."
                    except PolicyCartExpired:
                        status = QuoteStatus.QUOTE_EXPIRED
                        rejection_reason = f"Cart JWT expired."
                    except PolicyCartHashMismatch:
                        status = QuoteStatus.CART_HASH_MISMATCH
                        rejection_reason = "Cart JWT payload hash does not match embedded cart_hash."
                    except Exception as e:
                        status = QuoteStatus.INVALID_SIGNATURE
                        rejection_reason = f"Cryptographic verification error: {e}"

        # Gate 2.5: Authoritative Field Validation & Anti-Split-Trust Enforcement (Bug 1 & Bug 7)
        if status == QuoteStatus.ELIGIBLE:
            if verified_cart is None:
                status = QuoteStatus.INVALID_SIGNATURE
                rejection_reason = "Cart JWT could not be verified."
            elif verified_cart.merchant_id != q.merchant_id:
                status = QuoteStatus.QUOTE_DATA_MISMATCH
                rejection_reason = (
                    f"Merchant identity mismatch: JWT contains '{verified_cart.merchant_id}' "
                    f"but quote declared '{q.merchant_id}'."
                )
            elif verified_cart.total_paise != q.total_paise:
                status = QuoteStatus.QUOTE_DATA_MISMATCH
                rejection_reason = (
                    f"Total amount mismatch: JWT contains ₹{verified_cart.total_paise / 100:.2f} "
                    f"({verified_cart.total_paise} paise) but quote declared ₹{q.total_paise / 100:.2f} "
                    f"({q.total_paise} paise)."
                )
            elif verified_cart.currency != q.currency:
                status = QuoteStatus.QUOTE_DATA_MISMATCH
                rejection_reason = (
                    f"Currency mismatch: JWT contains '{verified_cart.currency}' "
                    f"but quote declared '{q.currency}'."
                )
            elif q.signed_cart and verified_cart.cart_hash != q.signed_cart.cart_hash:
                status = QuoteStatus.QUOTE_DATA_MISMATCH
                rejection_reason = "Supplied signed_cart hash does not match verified JWT cart hash."

            if status == QuoteStatus.ELIGIBLE and verified_cart is not None:
                # Authoritative fields strictly derived from cryptographically verified cart
                effective_cart = verified_cart
                effective_total = verified_cart.total_paise

        # Gate 3: Canonical SHA-256 Cart Hash Integrity
        if status == QuoteStatus.ELIGIBLE:
            if effective_cart is None:
                status = QuoteStatus.CART_HASH_MISMATCH
                rejection_reason = "Missing cart data for hash validation."
            else:
                computed_hash = compute_cart_hash(effective_cart)
                if computed_hash != effective_cart.cart_hash:
                    status = QuoteStatus.CART_HASH_MISMATCH
                    rejection_reason = (
                        f"Canonical cart hash mismatch: computed '{computed_hash}' "
                        f"!= embedded '{effective_cart.cart_hash}'."
                    )

        # Gate 4: Time Window Expiry (TTL Window)
        if status == QuoteStatus.ELIGIBLE and effective_cart is not None:
            if current_time > effective_cart.expires_at:
                status = QuoteStatus.QUOTE_EXPIRED
                rejection_reason = f"Quote expired at {effective_cart.expires_at.isoformat()}."

        # Gate 5: Currency Alignment
        if status == QuoteStatus.ELIGIBLE and effective_cart is not None:
            if effective_cart.currency != "INR" or q.currency != "INR":
                status = QuoteStatus.CURRENCY_MISMATCH
                rejection_reason = (
                    f"Unsupported cart currency '{effective_cart.currency}' (expected 'INR')."
                )

        # Gate 6: Live Catalog Stock Check
        if status == QuoteStatus.ELIGIBLE and effective_cart is not None and db is not None:
            for item in effective_cart.line_items:
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
            if effective_total > intent.spend_cap_paise:
                status = QuoteStatus.SPEND_CAP_EXCEEDED
                rejection_reason = (
                    f"Quote total of ₹{effective_total / 100:.2f} ({effective_total} paise) "
                    f"exceeds authorized spend cap of ₹{intent.spend_cap_paise / 100:.2f} "
                    f"({intent.spend_cap_paise} paise)."
                )

        # Return fresh copy ensuring immutability (Patch 2) and authoritative verified data
        classified.append(
            q.model_copy(
                update={
                    "signed_cart": effective_cart,
                    "total_paise": effective_total,
                    "status": status,
                    "rejection_reason": rejection_reason,
                    "verified_at": current_time,
                }
            )
        )

    return classified


def route(
    quotes: Sequence[MerchantQuote],
    intent: UserIntentCredential,
    policy: OptimizationPolicy = OptimizationPolicy.LOWEST_TOTAL_PRICE,
    preferred_merchant_id: str | None = None,
    db: Session | None = None,
    now: datetime | None = None,
) -> RoutingDecision:
    """Deterministically ranks verified quotes according to optimization policy and selects winner."""
    # Scope Remediation: Only LOWEST_TOTAL_PRICE is active in the current sprint
    if policy != OptimizationPolicy.LOWEST_TOTAL_PRICE:
        raise NotImplementedError(
            f"Optimization policy '{policy.value}' is reserved for future extensions and not active in the current sprint. "
            f"Only '{OptimizationPolicy.LOWEST_TOTAL_PRICE.value}' is supported."
        )

    current_time = now or datetime.now(timezone.utc)
    classified_quotes = verify_and_classify_quotes(quotes, intent, db=db, now=current_time)

    eligible_quotes = [q for q in classified_quotes if q.status == QuoteStatus.ELIGIBLE]
    excluded_quotes = [q for q in classified_quotes if q.status != QuoteStatus.ELIGIBLE]

    winner_quote: MerchantQuote | None = None
    rationale = ""

    if eligible_quotes:
        winner_quote = min(eligible_quotes, key=lambda q: (q.total_paise, q.merchant_id))
        rationale = (
            f"Selected {winner_quote.merchant_id} at ₹{winner_quote.total_paise / 100:.2f} "
            f"(lowest verified eligible quote)."
        )

    # Price savings is relative to the second-lowest (runner-up) quote
    price_savings_paise: int | None = None
    if winner_quote and len(eligible_quotes) > 1:
        sorted_by_price = sorted(eligible_quotes, key=lambda q: (q.total_paise, q.merchant_id))
        runner_up = sorted_by_price[1]
        price_savings_paise = runner_up.total_paise - winner_quote.total_paise

    if not winner_quote:
        rationale = "No eligible quote within policy and budget boundaries."

    return RoutingDecision(
        winner_merchant_id=winner_quote.merchant_id if winner_quote else None,
        winner_quote=winner_quote,
        quotes=classified_quotes,
        eligible_quotes=eligible_quotes,
        excluded_quotes=excluded_quotes,
        optimization_objective=policy,
        price_savings_paise=price_savings_paise,
        deliberation_timestamp=current_time,
        decision_rationale=rationale,
    )


def revalidate_winner(
    winner_quote: MerchantQuote,
    intent: UserIntentCredential,
    db: Session | None = None,
    now: datetime | None = None,
) -> tuple[bool, str | None]:
    """Runs just-in-time 7-gate verification on a winning quote immediately prior to mandate signing."""
    current_time = now or datetime.now(timezone.utc)
    reverified = verify_and_classify_quotes([winner_quote], intent, db=db, now=current_time)
    if not reverified or reverified[0].status != QuoteStatus.ELIGIBLE:
        reason = reverified[0].rejection_reason if reverified else "Quote verification failed."
        return False, reason
    return True, None


def route_with_fallback(
    quotes: Sequence[MerchantQuote],
    intent: UserIntentCredential,
    policy: OptimizationPolicy = OptimizationPolicy.LOWEST_TOTAL_PRICE,
    preferred_merchant_id: str | None = None,
    db: Session | None = None,
    now: datetime | None = None,
    now_factory: Any = None,
) -> tuple[RoutingDecision, MerchantQuote | None]:
    """Routes quotes and validates winner; if winner fails JIT revalidation, falls back to runner-up.

    Uses fresh current timestamps on each candidate evaluation round to ensure true JIT revalidation.
    """
    get_time = now_factory or (lambda: now or datetime.now(timezone.utc))
    remaining_pool = list(quotes)

    fallback_applied = False
    fallback_from_merchant: str | None = None
    fallback_reason: str | None = None

    while remaining_pool:
        round_time = get_time()
        decision = route(
            quotes=remaining_pool,
            intent=intent,
            policy=policy,
            preferred_merchant_id=preferred_merchant_id,
            db=db,
            now=round_time,
        )
        if not decision.winner_quote:
            if fallback_applied:
                decision.fallback_applied = True
                decision.fallback_from_merchant = fallback_from_merchant
                decision.fallback_reason = fallback_reason
            return decision, None

        jit_reval_time = get_time()
        is_valid, reason = revalidate_winner(decision.winner_quote, intent, db=db, now=jit_reval_time)
        if is_valid:
            if fallback_applied:
                decision.fallback_applied = True
                decision.fallback_from_merchant = fallback_from_merchant
                decision.fallback_reason = fallback_reason
                decision.decision_rationale = (
                    f"Original winner '{fallback_from_merchant}' failed JIT revalidation ({fallback_reason}). "
                    f"Fell back to runner-up {decision.winner_quote.merchant_id} at ₹{decision.winner_quote.total_paise / 100:.2f}."
                )
            return decision, decision.winner_quote

        # Winner failed JIT revalidation; record metadata and fallback to remaining candidates
        fallback_applied = True
        fallback_from_merchant = decision.winner_quote.merchant_id
        fallback_reason = reason or "JIT_REVALIDATION_FAILED"
        remaining_pool = [q for q in remaining_pool if q.merchant_id != decision.winner_quote.merchant_id]

    # No candidates survived revalidation
    empty_decision = route(
        quotes=quotes,
        intent=intent,
        policy=policy,
        preferred_merchant_id=preferred_merchant_id,
        db=db,
        now=get_time(),
    )
    if fallback_applied:
        empty_decision.fallback_applied = True
        empty_decision.fallback_from_merchant = fallback_from_merchant
        empty_decision.fallback_reason = fallback_reason
        empty_decision.decision_rationale = (
            f"All candidate quotes failed JIT revalidation (last failed: '{fallback_from_merchant}' due to {fallback_reason})."
        )
    return empty_decision, None
