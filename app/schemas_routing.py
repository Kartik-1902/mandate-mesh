"""Pydantic schemas and data models for Multi-Merchant Quote Routing (Milestone M3 / ADR-008).

Defines:
- QuoteStatus: Enumeration of all deterministic verification and classification states.
- MerchantQuote: Internal authoritative representation of a solicited merchant quote.
- CandidateQuoteResponse: Safe external API projection omitting raw JWT credentials.
- RoutingDecision: Structured result of multi-merchant optimization and policy evaluation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, Field

from app.schemas import MerchantSignedCart


class OptimizationPolicy(str, Enum):
    """Policies governing multi-merchant candidate ranking and winner selection."""

    LOWEST_TOTAL_PRICE = "LOWEST_TOTAL_PRICE"
    PREFER_MERCHANT = "PREFER_MERCHANT"
    MAX_ITEM_AVAILABILITY = "MAX_ITEM_AVAILABILITY"


class QuoteStatus(str, Enum):
    """Classification states for solicited merchant quotes."""

    # 1. Eligible for winning selection
    ELIGIBLE = "ELIGIBLE"

    # 2. Financial ceiling exceeded
    SPEND_CAP_EXCEEDED = "SPEND_CAP_EXCEEDED"

    # 3. Policy and authorization violations
    MERCHANT_UNAUTHORIZED = "MERCHANT_UNAUTHORIZED"
    MERCHANT_KEY_UNAVAILABLE = "MERCHANT_KEY_UNAVAILABLE"
    MERCHANT_UNAVAILABLE = "MERCHANT_UNAVAILABLE"
    DISALLOWED_CATEGORY = "DISALLOWED_CATEGORY"
    SKU_UNAVAILABLE = "SKU_UNAVAILABLE"

    # 4. Cryptographic integrity violations
    INVALID_SIGNATURE = "INVALID_SIGNATURE"
    CART_HASH_MISMATCH = "CART_HASH_MISMATCH"
    QUOTE_DATA_MISMATCH = "QUOTE_DATA_MISMATCH"

    # 5. Temporal and inventory constraints
    QUOTE_EXPIRED = "QUOTE_EXPIRED"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"


class MerchantQuote(BaseModel):
    """Internal model for a merchant's signed quote and verification status."""

    merchant_id: str
    cart_jwt: str | None = None
    signed_cart: MerchantSignedCart | None = None
    total_paise: int = 0
    currency: str = "INR"
    status: QuoteStatus = QuoteStatus.ELIGIBLE
    rejection_reason: str | None = None
    verified_at: datetime | None = None
    sku_matches: list[str] = Field(default_factory=list)
    line_items_summary: list[dict[str, Any]] = Field(default_factory=list)


class CandidateQuoteResponse(BaseModel):
    """External API and UI projection of a candidate quote.

    SECURITY INVARIANT:
    Raw JWTs (cart_jwt) are NEVER exposed to external callers or UI panels.
    This schema provides only safe decision and pricing metadata.
    """

    merchant_id: str
    total_paise: int
    status: QuoteStatus
    is_winner: bool = False
    price_delta_paise: int | None = None
    rejection_reason: str | None = None
    line_items_summary: list[dict[str, Any]] = Field(default_factory=list)

    @classmethod
    def from_merchant_quote(
        cls,
        quote: MerchantQuote,
        is_winner: bool = False,
        winner_total_paise: int | None = None,
    ) -> CandidateQuoteResponse:
        """Converts an internal MerchantQuote into a safe external response."""
        price_delta = None
        if not is_winner and winner_total_paise is not None and quote.status == QuoteStatus.ELIGIBLE:
            price_delta = quote.total_paise - winner_total_paise

        summary = quote.line_items_summary
        if not summary and quote.signed_cart and quote.signed_cart.line_items:
            summary = [
                {
                    "sku": li.sku,
                    "name": li.name,
                    "quantity": li.quantity,
                    "unit_price_paise": li.unit_price_paise,
                    "line_total_paise": li.line_total_paise,
                }
                for li in quote.signed_cart.line_items
            ]

        return cls(
            merchant_id=quote.merchant_id,
            total_paise=quote.total_paise,
            status=quote.status,
            is_winner=is_winner,
            price_delta_paise=price_delta,
            rejection_reason=quote.rejection_reason,
            line_items_summary=summary,
        )


class RoutingDecision(BaseModel):
    """Outcome of deterministic multi-merchant quote routing and optimization."""

    winner_merchant_id: str | None = None
    winner_quote: MerchantQuote | None = None
    quotes: list[MerchantQuote] = Field(default_factory=list)
    eligible_quotes: list[MerchantQuote] = Field(default_factory=list)
    excluded_quotes: list[MerchantQuote] = Field(default_factory=list)
    optimization_objective: OptimizationPolicy = OptimizationPolicy.LOWEST_TOTAL_PRICE
    price_savings_paise: int | None = None
    deliberation_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    decision_rationale: str = ""


class RoutingDecisionResponse(BaseModel):
    """Safe external projection of a RoutingDecision omitting raw JWTs.

    SECURITY INVARIANT:
    Internal MerchantQuote objects holding cart_jwt are NEVER serialized to API callers.
    """

    winner_merchant_id: str | None = None
    winner_total_paise: int | None = None
    optimization_objective: OptimizationPolicy = OptimizationPolicy.LOWEST_TOTAL_PRICE
    price_savings_paise: int | None = None
    deliberation_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    decision_rationale: str = ""
    candidate_quotes: list[CandidateQuoteResponse] = Field(default_factory=list)

    @classmethod
    def from_routing_decision(cls, decision: RoutingDecision) -> RoutingDecisionResponse:
        winner_total = decision.winner_quote.total_paise if decision.winner_quote else None
        candidate_projections = [
            CandidateQuoteResponse.from_merchant_quote(
                quote=q,
                is_winner=(decision.winner_merchant_id == q.merchant_id and q.status == QuoteStatus.ELIGIBLE),
                winner_total_paise=winner_total,
            )
            for q in decision.quotes
        ]
        return cls(
            winner_merchant_id=decision.winner_merchant_id,
            winner_total_paise=winner_total,
            optimization_objective=decision.optimization_objective,
            price_savings_paise=decision.price_savings_paise,
            deliberation_timestamp=decision.deliberation_timestamp,
            decision_rationale=decision.decision_rationale,
            candidate_quotes=candidate_projections,
        )
