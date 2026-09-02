"""Deterministic Mixed-Basket Planner (Milestone M6 / ADR-011).

================================================================================
ARCHITECTURAL CORRECTNESS INVARIANT (B-REQ-7 / Milestone M6):
================================================================================
The greedy, independent per-product allocation algorithm implemented in this module
is mathematically guaranteed to produce the global LOWEST_TOTAL_PRICE allocation
IF AND ONLY IF the commerce network satisfies ALL of the following conditions:
  1. ZERO delivery / shipping fees per merchant leg (no fixed marginal leg cost).
  2. ZERO minimum order value (MOV) thresholds per merchant leg.
  3. ZERO volume discounts or quantity-tiered pricing across line items.
  4. ZERO multi-item bundle pricing or cross-SKU promotional discounts.
  5. Completely independent pricing across merchants (no cross-item pricing dependencies).

WARNING TO FUTURE IMPLEMENTERS:
If delivery fees (e.g. ₹50 per merchant delivery), minimum order thresholds (e.g. ₹500
minimum per merchant), volume tiers, or bundle discounts are ever introduced, this
independent greedy per-product allocation CEASES to be optimal. Under those pricing
interactions, finding the lowest total price allocation is NP-hard (formally equivalent
to the Set Cover / Uncapacitated Facility Location problem) and will require combinatorial
mixed-integer linear programming (MILP) or branch-and-bound optimization rather than
greedy per-item selection.
================================================================================

Core Principles:
1. Product Identity: Operates on canonical product_id (Universal Product Identity).
2. Merchant Isolation: Resolves merchant-local SKUs through CatalogItem.product_id.
   SKUs never leak across merchant boundaries.
3. Authoritative Quote Data: Every allocated leg generates an authoritative
   cryptographically signed MerchantSignedCart with ES256 signature.
4. Deterministic Tie-Breaking: Stable tie-breaking rule:
     (unit_price_paise ASC, merchant_id ASC, sku ASC)
   Guarantees reproducible allocations independent of database row ordering.
5. Infeasibility Fail-Closed: If any requested product cannot be satisfied by an
   authorized, in-stock merchant, the entire basket is declared INFEASIBLE.
   No partial basket authorizations or partial orders are emitted.
6. Zero Financial Authority: Planning only. Does NOT create Razorpay orders,
   does NOT authorize mandates, does NOT capture payments.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Sequence
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.merchant import sign_cart
from app.merchant_keys import MerchantKeyNotFound, get_merchant_private_key
from app.models import CatalogItem
from app.schemas import MerchantSignedCart
from app.schemas_routing import MerchantQuote, OptimizationPolicy, QuoteStatus


class BasketPlanStatus(str, Enum):
    """Feasibility classification for a mixed-basket plan."""

    FEASIBLE = "FEASIBLE"
    INFEASIBLE = "INFEASIBLE"
    SPEND_CAP_EXCEEDED = "SPEND_CAP_EXCEEDED"


class BasketItemRequest(BaseModel):
    """A requested line item specifying canonical product identity and quantity."""

    product_id: UUID
    quantity: int = Field(default=1, ge=1)


class BasketLegItem(BaseModel):
    """An allocated line item within a specific merchant leg."""

    product_id: UUID
    sku: str
    name: str
    quantity: int = Field(ge=1)
    unit_price_paise: int = Field(ge=0)
    line_total_paise: int = Field(ge=0)


class BasketLeg(BaseModel):
    """An execution leg grouping all items allocated to a single merchant."""

    leg_id: str
    merchant_id: str
    items: list[BasketLegItem]
    total_paise: int = Field(ge=0)
    signed_cart: MerchantSignedCart | None = None
    cart_jwt: str | None = None
    quote: MerchantQuote | None = None


class MixedBasketPlan(BaseModel):
    """Deterministic mixed-basket allocation plan.

    SECURITY INVARIANT:
    This model represents a pure commercial plan. It does NOT authorize funds,
    create payment mandates, or execute payment gateways.
    """

    plan_id: UUID = Field(default_factory=uuid4)
    is_feasible: bool
    status: BasketPlanStatus
    legs: list[BasketLeg] = Field(default_factory=list)
    total_items_count: int = 0
    total_price_paise: int = 0
    currency: str = "INR"
    spend_cap_paise: int | None = None
    spend_cap_exceeded: bool = False
    overspend_paise: int = 0
    unavailable_product_ids: list[UUID] = Field(default_factory=list)
    rejection_reason: str | None = None
    optimization_policy: OptimizationPolicy = OptimizationPolicy.LOWEST_TOTAL_PRICE
    decision_rationale: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def plan_mixed_basket(
    proposed_items: Sequence[dict[str, Any] | BasketItemRequest],
    allowed_merchant_ids: Sequence[str],
    db: Session,
    spend_cap_paise: int | None = None,
    policy: OptimizationPolicy = OptimizationPolicy.LOWEST_TOTAL_PRICE,
    key_override_pem: bytes | str | Path | None = None,
) -> MixedBasketPlan:
    """Deterministically allocates canonical product items to allowed merchants.

    Optimization Objective:
        LOWEST_TOTAL_PRICE under the documented correctness condition (no delivery fees,
        no minimum order thresholds, no bundle pricing).

    Deterministic Tie-Breaking Rule:
        When multiple candidate merchants offer an item at equal lowest unit price:
          1. Lowest unit_price_paise (ASC)
          2. Lexicographical merchant_id (ASC)
          3. Lexicographical sku (ASC)

    Returns:
        MixedBasketPlan: Structured plan with grouped execution legs or explicit infeasibility.
    """
    if policy != OptimizationPolicy.LOWEST_TOTAL_PRICE:
        raise NotImplementedError(
            f"Optimization policy '{policy.value}' is not implemented for mixed-basket planning. "
            f"Only '{OptimizationPolicy.LOWEST_TOTAL_PRICE.value}' is currently supported."
        )

    # 1. Parse and aggregate item requests by canonical product_id
    aggregated_requests: dict[UUID, int] = {}
    for it in proposed_items:
        if isinstance(it, BasketItemRequest):
            pid = it.product_id
            qty = it.quantity
        elif isinstance(it, dict):
            raw_pid = it.get("product_id")
            if not raw_pid:
                raise ValueError("Each proposed item must specify 'product_id'.")
            pid = UUID(str(raw_pid)) if not isinstance(raw_pid, UUID) else raw_pid
            qty = max(1, int(it.get("quantity", 1)))
        else:
            raise ValueError(f"Unsupported item proposal type: {type(it)}")

        aggregated_requests[pid] = aggregated_requests.get(pid, 0) + qty

    if not aggregated_requests:
        return MixedBasketPlan(
            plan_id=uuid4(),
            is_feasible=False,
            status=BasketPlanStatus.INFEASIBLE,
            legs=[],
            total_items_count=0,
            total_price_paise=0,
            rejection_reason="No items in basket proposal.",
            decision_rationale="Basket proposal is empty.",
            optimization_policy=policy,
        )

    deduped_merchants = [m for m in dict.fromkeys(allowed_merchant_ids) if m]
    if not deduped_merchants:
        return MixedBasketPlan(
            plan_id=uuid4(),
            is_feasible=False,
            status=BasketPlanStatus.INFEASIBLE,
            legs=[],
            total_items_count=0,
            total_price_paise=0,
            unavailable_product_ids=list(aggregated_requests.keys()),
            rejection_reason="No merchants authorized in allowlist.",
            decision_rationale="Allowed merchant list is empty.",
            optimization_policy=policy,
        )

    # 2. Batch query in-stock merchant catalog items for requested products from allowed merchants
    requested_pids = list(aggregated_requests.keys())
    catalog_rows = (
        db.query(CatalogItem)
        .filter(
            CatalogItem.product_id.in_(requested_pids),
            CatalogItem.merchant_id.in_(deduped_merchants),
            CatalogItem.in_stock == True,
        )
        .all()
    )

    # Index matching items by product_id
    candidates_by_pid: dict[UUID, list[CatalogItem]] = {pid: [] for pid in requested_pids}
    for row in catalog_rows:
        if row.product_id in candidates_by_pid:
            # Verify signing key exists for merchant to guarantee quote authority
            try:
                if not (key_override_pem and len(deduped_merchants) == 1):
                    get_merchant_private_key(row.merchant_id)
                candidates_by_pid[row.product_id].append(row)
            except MerchantKeyNotFound:
                # Disqualify candidate merchant without trusted key
                continue
            except Exception:
                continue

    # 3. Check for partial availability / impossible basket
    unavailable_pids: list[UUID] = []
    for pid in requested_pids:
        if not candidates_by_pid[pid]:
            unavailable_pids.append(pid)

    if unavailable_pids:
        pids_str = ", ".join(str(p) for p in sorted(unavailable_pids, key=str))
        return MixedBasketPlan(
            plan_id=uuid4(),
            is_feasible=False,
            status=BasketPlanStatus.INFEASIBLE,
            legs=[],
            total_items_count=0,
            total_price_paise=0,
            unavailable_product_ids=unavailable_pids,
            rejection_reason=(
                f"The following {len(unavailable_pids)} canonical item(s) cannot be satisfied by any "
                f"authorized, in-stock merchant: [{pids_str}]."
            ),
            decision_rationale="Basket is infeasible due to missing inventory, out-of-stock items, or unauthorized merchants.",
            optimization_policy=policy,
        )

    # 4. Deterministic Allocation & Stable Tie-Breaking
    # Tie-break key: (price_paise ASC, merchant_id ASC, sku ASC)
    merchant_allocations: dict[str, list[tuple[CatalogItem, int]]] = {}
    for pid, qty in aggregated_requests.items():
        candidates = candidates_by_pid[pid]
        best_candidate = min(
            candidates,
            key=lambda row: (row.price_paise, row.merchant_id, row.sku),
        )
        merchant_allocations.setdefault(best_candidate.merchant_id, []).append((best_candidate, qty))

    # 5. Group allocated products into execution legs and generate authoritative signed quotes
    legs: list[BasketLeg] = []
    for mid in sorted(merchant_allocations.keys()):
        allocated_items = merchant_allocations[mid]

        leg_items: list[BasketLegItem] = []
        line_items_req: list[dict[str, Any]] = []

        for row, qty in allocated_items:
            line_total = row.price_paise * qty
            leg_items.append(
                BasketLegItem(
                    product_id=row.product_id,
                    sku=row.sku,
                    name=row.name,
                    quantity=qty,
                    unit_price_paise=row.price_paise,
                    line_total_paise=line_total,
                )
            )
            line_items_req.append({"sku": row.sku, "quantity": qty})

        # Deterministic sorting within leg
        leg_items.sort(key=lambda it: (it.sku, str(it.product_id)))
        line_items_req.sort(key=lambda it: it["sku"])

        priv_key = (
            key_override_pem
            if (key_override_pem and len(merchant_allocations) == 1)
            else get_merchant_private_key(mid)
        )

        signed_cart, cart_jwt = sign_cart(
            merchant_id=mid,
            line_items_req=line_items_req,
            merchant_private_key_pem=priv_key,
            db=db,
        )

        quote = MerchantQuote(
            merchant_id=mid,
            cart_jwt=cart_jwt,
            signed_cart=signed_cart,
            total_paise=signed_cart.total_paise,
            status=QuoteStatus.ELIGIBLE,
            line_items_summary=[
                {
                    "sku": li.sku,
                    "name": li.name,
                    "quantity": li.quantity,
                    "unit_price_paise": li.unit_price_paise,
                    "line_total_paise": li.line_total_paise,
                }
                for li in signed_cart.line_items
            ],
        )

        legs.append(
            BasketLeg(
                leg_id=f"leg_{mid}_{uuid4().hex[:8]}",
                merchant_id=mid,
                items=leg_items,
                total_paise=signed_cart.total_paise,
                signed_cart=signed_cart,
                cart_jwt=cart_jwt,
                quote=quote,
            )
        )

    # 6. Compute total price and validate spend cap
    total_price_paise = sum(leg.total_paise for leg in legs)
    total_items_count = sum(sum(it.quantity for it in leg.items) for leg in legs)

    spend_cap_exceeded = False
    overspend_paise = 0
    status = BasketPlanStatus.FEASIBLE
    rejection_reason = None

    if spend_cap_paise is not None and total_price_paise > spend_cap_paise:
        spend_cap_exceeded = True
        overspend_paise = total_price_paise - spend_cap_paise
        status = BasketPlanStatus.SPEND_CAP_EXCEEDED
        rejection_reason = (
            f"Total plan cost of ₹{total_price_paise / 100:.2f} ({total_price_paise} paise) "
            f"exceeds spend cap of ₹{spend_cap_paise / 100:.2f} ({spend_cap_paise} paise) "
            f"by ₹{overspend_paise / 100:.2f} ({overspend_paise} paise)."
        )

    leg_descriptions = ", ".join(
        f"{leg.merchant_id} ({len(leg.items)} item(s), ₹{leg.total_paise / 100:.2f})"
        for leg in legs
    )
    rationale = (
        f"Constructed {len(legs)} execution leg(s) across {leg_descriptions}. "
        f"Total: ₹{total_price_paise / 100:.2f} under LOWEST_TOTAL_PRICE policy."
    )

    return MixedBasketPlan(
        plan_id=uuid4(),
        is_feasible=(not spend_cap_exceeded),
        status=status,
        legs=legs,
        total_items_count=total_items_count,
        total_price_paise=total_price_paise,
        currency="INR",
        spend_cap_paise=spend_cap_paise,
        spend_cap_exceeded=spend_cap_exceeded,
        overspend_paise=overspend_paise,
        unavailable_product_ids=[],
        rejection_reason=rejection_reason,
        optimization_policy=policy,
        decision_rationale=rationale,
    )
