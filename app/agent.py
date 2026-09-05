"""LangGraph Buyer Agent for Mandate Mesh with Multi-Merchant Routing Support.

Enforces:
- Structural tool parameter constraints (ADR-001): `propose_cart` tool accepts `{items: list[{sku, quantity}]}`.
  It structurally lacks `price`, `amount`, `total`, or `discount` parameters.
- Multi-Merchant Discovery (ADR-008): Queries candidate merchants and collects signed quotes.
- Pre-Agent Intent & Spend Cap Enforcement: Operates within pre-minted UserIntentCredential boundaries.
- Prices are retrieved authoritatively from the database catalog during cart signing for each merchant and line item.
- Authoritative merchant summation: calculates subtotal and total across all requested line items.
- Prompt injection in goals or catalog descriptions cannot override authoritative pricing.
- Complete separation between agent selection tools and payment authorization/execution.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, TypedDict
from uuid import UUID, uuid4
import httpx
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from langgraph.graph import StateGraph, START, END

from app.config import settings
from app.errors import CatalogSkuNotFound
from app.merchant import seed_catalog, sign_cart
from app.merchant_keys import (
    MerchantKeyNotFound,
    get_merchant_private_key,
    list_known_merchant_ids,
)
from app.models import CanonicalProduct, CatalogItem
from app.quote_router import route, verify_and_classify_quotes
from app.schemas import MerchantSignedCart, UserIntentCredential
from app.schemas_routing import (
    MerchantQuote,
    OptimizationPolicy,
    QuoteStatus,
    RoutingDecision,
)


# =============================================================================
# 0. Live Gemini LLM Calling (Dual Mode)
# =============================================================================

def call_gemini_llm(prompt: str, api_key: str, model: str = "gemini-3.5-flash-lite") -> str | None:
    """Calls Gemini REST API using httpx for autonomous deliberation."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [
            {
                "parts": [{"text": prompt}]
            }
        ]
    }
    try:
        with httpx.Client(timeout=20.0) as client:
            resp = client.post(url, headers=headers, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts:
                        return parts[0].get("text", "")
    except Exception:
        pass
    return None


# =============================================================================
# 1. Tool Input Schema Definitions (Zero Financial Fields Invariant)
# =============================================================================

class BrowseCatalogInput(BaseModel):
    """Filter parameters for browsing the merchant catalog."""
    category: str | None = Field(default=None, description="Product category filter (e.g. 'bakery', 'gifting')")
    query: str | None = Field(default=None, description="Free-text search query across item names and descriptions")
    merchant_id: str | None = Field(default=None, description="Specific merchant ID to filter catalog items")


class CartItemProposal(BaseModel):
    """Proposal for a single line item within a cart.

    CRITICAL ARCHITECTURAL BOUNDARY:
    This schema structurally omits any 'price', 'amount', 'total', or 'unit_price' fields.
    """
    sku: str = Field(..., description="The catalog item SKU identifier")
    quantity: int = Field(1, ge=1, description="Quantity to purchase (must be >= 1)")


class ProposeCartInput(BaseModel):
    """Proposal to checkout one or more catalog SKUs.

    CRITICAL ARCHITECTURAL BOUNDARY:
    This schema structurally omits any 'price', 'amount', 'total', or 'discount' fields.
    The agent can only specify what SKUs it desires and in what quantities.
    """
    items: list[CartItemProposal] = Field(
        min_length=1,
        description="List of catalog item SKUs and quantities to order",
    )


# =============================================================================
# 2. Agent Tool Functions & Multi-Merchant Solicitation
# =============================================================================

def browse_catalog_tool(
    db: Session,
    category: str | None = None,
    query: str | None = None,
    merchant_id: str | None = None,
    merchant_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Tool: Queries active items from the merchant catalog with merchant metadata scoped at DB query."""
    q = db.query(CatalogItem).filter(CatalogItem.in_stock.is_(True))
    if category:
        q = q.filter(CatalogItem.category.ilike(f"%{category}%"))
    if merchant_id:
        q = q.filter(CatalogItem.merchant_id == merchant_id)
    elif merchant_ids is not None:
        q = q.filter(CatalogItem.merchant_id.in_(merchant_ids))

    items = q.all()
    results: list[dict[str, Any]] = []

    for item in items:
        if query:
            q_lower = query.lower()
            if q_lower not in item.name.lower() and q_lower not in (item.description or "").lower():
                continue

        results.append({
            "merchant_id": item.merchant_id,
            "sku": item.sku,
            "name": item.name,
            "category": item.category,
            "description": item.description,
            "in_stock": item.in_stock,
            "price_paise": item.price_paise,
        })

    return results


def propose_cart_tool(
    db: Session,
    merchant_private_key_pem: bytes | str | Path | None = None,
    sku: str | None = None,
    quantity: int = 1,
    items: list[dict[str, Any]] | None = None,
    merchant_id: str = "merchant_cakehouse_01",
) -> tuple[MerchantSignedCart, str]:
    """Tool: Submits proposed SKUs and quantities to a merchant for authoritative pricing, totaling, and signing."""
    line_items_req: list[dict[str, Any]] = []
    if items:
        line_items_req = [{"sku": it["sku"], "quantity": int(it.get("quantity", 1))} for it in items]
    elif sku:
        line_items_req = [{"sku": sku, "quantity": quantity}]
    else:
        raise ValueError("Either 'items' or 'sku' must be provided.")

    # Verify all SKUs exist in the specific merchant's catalog before signing
    for req in line_items_req:
        it_row = (
            db.query(CatalogItem)
            .filter_by(merchant_id=merchant_id, sku=req["sku"])
            .first()
        )
        if not it_row:
            raise CatalogSkuNotFound(req["sku"])

    key_pem = merchant_private_key_pem or get_merchant_private_key(merchant_id)

    return sign_cart(
        merchant_id=merchant_id,
        line_items_req=line_items_req,
        merchant_private_key_pem=key_pem,
        db=db,
    )


def collect_merchant_quotes(
    db: Session,
    allowed_merchant_ids: list[str],
    proposed_items: list[dict[str, Any]],
    key_override_pem: bytes | str | Path | None = None,
) -> list[MerchantQuote]:
    """Solicits and signs carts from all authorized candidate merchants, resolving canonical product IDs to merchant-local SKUs."""
    quotes: list[MerchantQuote] = []

    for mid in allowed_merchant_ids:
        try:
            priv_pem = (
                key_override_pem
                if (key_override_pem and len(allowed_merchant_ids) == 1)
                else get_merchant_private_key(mid)
            )
        except MerchantKeyNotFound:
            quotes.append(
                MerchantQuote(
                    merchant_id=mid,
                    status=QuoteStatus.MERCHANT_KEY_UNAVAILABLE,
                    rejection_reason=f"No trusted signing key registered for merchant '{mid}'.",
                )
            )
            continue
        except Exception as e:
            quotes.append(
                MerchantQuote(
                    merchant_id=mid,
                    status=QuoteStatus.MERCHANT_UNAVAILABLE,
                    rejection_reason=f"Merchant signing key error: {e}",
                )
            )
            continue

        try:
            # Resolve product_id (canonical identity) to merchant-local SKU
            line_items_req: list[dict[str, Any]] = []
            for item_req in proposed_items:
                qty = max(1, int(item_req.get("quantity", 1)))
                if "product_id" in item_req and item_req["product_id"]:
                    pid = item_req["product_id"]
                    if isinstance(pid, str):
                        try:
                            pid = UUID(pid)
                        except ValueError:
                            pass
                    catalog_item = (
                        db.query(CatalogItem)
                        .filter_by(merchant_id=mid, product_id=pid)
                        .first()
                    )
                    if not catalog_item:
                        raise CatalogSkuNotFound(f"Product '{pid}' not offered by merchant '{mid}'")
                    line_items_req.append({"sku": catalog_item.sku, "quantity": qty})
                elif "sku" in item_req:
                    # Backward compatibility for direct SKU queries
                    sku = item_req["sku"]
                    catalog_item = (
                        db.query(CatalogItem)
                        .filter_by(merchant_id=mid, sku=sku)
                        .first()
                    )
                    if not catalog_item:
                        raise CatalogSkuNotFound(sku)
                    line_items_req.append({"sku": sku, "quantity": qty})
                else:
                    raise ValueError("Each proposed item must specify either 'product_id' or 'sku'")

            signed_cart, cart_jwt = sign_cart(
                merchant_id=mid,
                line_items_req=line_items_req,
                merchant_private_key_pem=priv_pem,
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
            quotes.append(quote)
        except CatalogSkuNotFound as e:
            quotes.append(
                MerchantQuote(
                    merchant_id=mid,
                    status=QuoteStatus.SKU_UNAVAILABLE,
                    rejection_reason=f"Requested SKU/product not found in merchant catalog: {e}",
                )
            )
        except Exception as e:
            quotes.append(
                MerchantQuote(
                    merchant_id=mid,
                    status=QuoteStatus.MERCHANT_UNAVAILABLE,
                    rejection_reason=f"Merchant quote solicitation failed: {e}",
                )
            )

    return quotes


# Static Tool Registry for boundary introspection
AGENT_TOOLS: list[dict[str, Any]] = [
    {
        "name": "browse_catalog",
        "description": "Browse active merchant catalog items by category, search keyword, and merchant ID.",
        "args_schema": BrowseCatalogInput,
        "callable": browse_catalog_tool,
    },
    {
        "name": "propose_cart",
        "description": "Propose an order of one or multiple catalog SKUs and quantities for authoritative merchant pricing and signing.",
        "args_schema": ProposeCartInput,
        "callable": propose_cart_tool,
    },
]


# =============================================================================
# 3. LangGraph State & Node Definitions
# =============================================================================

class BuyerAgentState(TypedDict):
    """LangGraph agent state throughout the purchase deliberation."""
    goal: str
    parsed_intent: dict[str, Any]
    catalog_candidates: list[dict[str, Any]]
    proposed_items: list[dict[str, Any]]
    selected_sku: str | None
    quantity: int
    spend_cap_paise: int
    allowed_merchant_ids: list[str]
    intent: UserIntentCredential | None
    all_quotes: list[MerchantQuote]
    routing_decision: RoutingDecision | None
    cart_jwt: str | None
    signed_cart: MerchantSignedCart | None
    llm_reasoning: str | None
    status: str  # "COMPLETED", "REQUIRES_USER_APPROVAL", "ERROR"
    escalation_details: dict[str, Any] | None
    error: str | None


def parse_goal_node(state: BuyerAgentState) -> dict[str, Any]:
    """Node 1: Deterministic natural language purchase goal parser.

    Extracts keywords, category, and budget ceiling from user goal without LLM invocation.
    Per Milestone M5 boundary, the request flow uses exactly ONE LLM call during deliberate_and_route.
    """
    goal_text = state.get("goal", "")

    parsed: dict[str, Any] = {
        "keywords": [],
        "category": "bakery",
        "max_budget_paise": None,
    }

    # Deterministic NLP regex extraction
    range_match = re.search(r"between\s*(?:rs\.?|inr|₹)?\s*(\d+)\s*(?:to|and|-)\s*(?:rs\.?|inr|₹)?\s*(\d+)", goal_text, re.IGNORECASE)
    if range_match:
        parsed["max_budget_paise"] = int(range_match.group(2)) * 100
    else:
        budget_match = re.search(
            r"(?:under|below|max|budget|within|up to|upto|less than|at price|at|price|for|around|costing)\s*(?:rs\.?|inr|₹)?\s*(\d+)",
            goal_text,
            re.IGNORECASE,
        )
        if not budget_match:
            budget_match = re.search(r"(?:rs\.?|inr|₹)\s*(\d+)", goal_text, re.IGNORECASE)
        if budget_match:
            parsed["max_budget_paise"] = int(budget_match.group(1)) * 100

    words = [w.strip(",.!?\"'") for w in goal_text.split()]
    stop_words = {"order", "want", "please", "under", "with", "from", "between", "around", "about", "some", "like", "price", "buy"}
    meaningful_words = [w for w in words if len(w) > 2 and not w.isdigit() and w.lower() not in stop_words]
    parsed["keywords"] = meaningful_words

    has_bakery = any(any(k.lower().startswith(root) for root in ["cake", "pastr", "baker", "bread"]) for k in words)
    has_gifting = any(any(k.lower().startswith(root) for root in ["card", "gift", "candle", "greet"]) for k in words)
    has_electronics = any(any(k.lower().startswith(root) for root in ["headphone", "tech", "electron", "power"]) for k in words)

    matched_categories = sum([has_bakery, has_gifting, has_electronics])

    if matched_categories > 1:
        # Cross-category query: do not restrict catalog to a single category
        parsed["category"] = None
    elif has_bakery:
        parsed["category"] = "bakery"
    elif has_gifting:
        parsed["category"] = "gifting"
    elif has_electronics:
        parsed["category"] = "electronics"
    else:
        parsed["category"] = None

    return {"parsed_intent": parsed}


def browse_catalog_node_factory(db: Session) -> Callable[[BuyerAgentState], dict[str, Any]]:
    """Node 2 Factory: Queries canonical products matching parsed intent."""
    def browse_catalog_node(state: BuyerAgentState) -> dict[str, Any]:
        intent = state.get("parsed_intent", {})
        keywords = intent.get("keywords", [])
        category = intent.get("category")

        # Query CanonicalProduct table
        q = db.query(CanonicalProduct)
        if category:
            q = q.filter(CanonicalProduct.category.ilike(f"%{category}%"))

        canonical_prods = q.all()
        if not canonical_prods:
            seed_catalog(db)
            q = db.query(CanonicalProduct)
            if category:
                q = q.filter(CanonicalProduct.category.ilike(f"%{category}%"))
            canonical_prods = q.all()

        # Filter and score by keywords and category
        matching_candidates: list[dict[str, Any]] = []
        for prod in canonical_prods:
            prod_text = f"{prod.canonical_name} {prod.description or ''} {prod.brand or ''} {prod.category}".lower()
            kw_score = sum(1 for kw in keywords if kw.lower() in prod_text)
            cat_bonus = 2 if category and prod.category.lower() == category.lower() else 0
            total_score = kw_score + cat_bonus
            if not keywords or total_score > 0:
                min_price = min((it.price_paise for it in prod.catalog_items if it.in_stock), default=999999999)
                matching_candidates.append({
                    "product_id": str(prod.product_id),
                    "canonical_name": prod.canonical_name,
                    "brand": prod.brand,
                    "category": prod.category,
                    "description": prod.description,
                    "tags": prod.tags,
                    "match_score": total_score,
                    "min_price_paise": min_price,
                })

        # Sort primarily by match score descending, secondarily by min price ascending
        matching_candidates.sort(key=lambda x: (-x["match_score"], x["min_price_paise"]))

        return {"catalog_candidates": matching_candidates}

    return browse_catalog_node


# =============================================================================
# 3. Deterministic Commerce Orchestrator (Milestone M5)
# =============================================================================

class CommerceOrchestrator:
    """Deterministic Commerce Orchestrator.

    Strict Architectural Boundary (M5):
      - The LLM proposes canonical items; deterministic Python executes commerce logic.
      - The LLM never touches prices, quotes, merchant discovery, or SKU mapping.
    
    Responsibilities owned by CommerceOrchestrator:
      1. Canonical product to merchant inventory lookup
      2. Merchant discovery across candidate merchants
      3. Merchant-local SKU resolution (via CatalogItem.product_id)
      4. Authoritative pricing & cryptographic quote solicitation
      5. 7-gate cryptographic and policy verification
      6. Basket allocation, totals calculation, and price savings
      7. Policy authorization and escalation detection
    """

    def __init__(
        self,
        db: Session,
        merchant_private_key_pem: bytes | str | Path | None = None,
    ):
        self.db = db
        self.merchant_private_key_pem = merchant_private_key_pem

    def orchestrate(
        self,
        proposed_items: list[dict[str, Any]],
        intent: UserIntentCredential | None = None,
        allowed_merchant_ids: list[str] | None = None,
        spend_cap_paise: int = 150000,
        policy: OptimizationPolicy = OptimizationPolicy.LOWEST_TOTAL_PRICE,
    ) -> dict[str, Any]:
        """Executes deterministic commerce logic from proposed canonical products."""
        merchants = allowed_merchant_ids or (intent.allowed_merchant_ids if intent else list_known_merchant_ids())
        cap = intent.spend_cap_paise if intent else spend_cap_paise

        # 1. Merchant discovery & merchant-local SKU resolution + authoritative quote collection
        solicited_quotes = collect_merchant_quotes(
            db=self.db,
            allowed_merchant_ids=merchants,
            proposed_items=proposed_items,
            key_override_pem=self.merchant_private_key_pem,
        )

        # 2. Deterministic 7-Gate Verification & Optimization Routing
        intent_obj = intent
        if not intent_obj:
            now = datetime.now(timezone.utc)
            intent_obj = UserIntentCredential(
                user_id="user_agent_deliberation",
                spend_cap_paise=cap,
                currency="INR",
                allowed_categories=["bakery", "gifting", "electronics"],
                allowed_merchant_ids=merchants,
                nonce=f"nonce_agent_{uuid4().hex}",
                not_before=now - timedelta(minutes=5),
                expires_at=now + timedelta(hours=1),
            )

        decision = route(
            quotes=solicited_quotes,
            intent=intent_obj,
            policy=policy,
            db=self.db,
        )
        verified_quotes = decision.quotes
        winner_quote = decision.winner_quote

        # 3. Deterministic budget evaluation and escalation detection
        priced_quotes = [q for q in verified_quotes if q.signed_cart and q.total_paise > 0]
        escalation_details = None
        cheapest_quote = None

        if winner_quote:
            status = "COMPLETED"
            active_quote = winner_quote
        elif priced_quotes:
            status = "REQUIRES_USER_APPROVAL"
            cheapest_quote = min(priced_quotes, key=lambda q: q.total_paise)
            overspend_paise = max(0, cheapest_quote.total_paise - cap)
            escalation_details = {
                "suggested_total_paise": cheapest_quote.total_paise,
                "current_budget_paise": cap,
                "overspend_paise": overspend_paise,
                "message": (
                    f"Lowest quote from {cheapest_quote.merchant_id} is Rs. {cheapest_quote.total_paise / 100:.2f}, "
                    f"which exceeds your Rs. {cap / 100:.2f} budget by Rs. {overspend_paise / 100:.2f}. "
                    f"User re-authorization required."
                ),
            }
            active_quote = cheapest_quote
        else:
            status = "NO_CANDIDATE_MATCH"
            active_quote = None

        selected_sku = (
            active_quote.signed_cart.line_items[0].sku
            if (active_quote and active_quote.signed_cart and active_quote.signed_cart.line_items)
            else None
        )

        return {
            "selected_sku": selected_sku,
            "signed_cart": active_quote.signed_cart if active_quote else None,
            "cart_jwt": active_quote.cart_jwt if active_quote else None,
            "all_quotes": verified_quotes,
            "routing_decision": decision,
            "status": status,
            "escalation_details": escalation_details,
        }

    def plan_basket(
        self,
        proposed_items: Sequence[dict[str, Any]],
        allowed_merchant_ids: Sequence[str] | None = None,
        policy: OptimizationPolicy = OptimizationPolicy.LOWEST_TOTAL_PRICE,
    ):
        """Invokes M6 deterministic mixed-basket planner to produce a commercial plan and authoritative total."""
        from app.basket_planner import plan_mixed_basket

        merchants = allowed_merchant_ids or list_known_merchant_ids()
        return plan_mixed_basket(
            proposed_items=proposed_items,
            allowed_merchant_ids=merchants,
            db=self.db,
            policy=policy,
            key_override_pem=self.merchant_private_key_pem,
        )

    def evaluate_basket_authorization(
        self,
        plan,
        intent: UserIntentCredential | None = None,
        spend_cap_paise: int | None = None,
    ) -> dict[str, Any]:
        """M5 deterministic policy layer: evaluates spend cap authorization on an M6 commercial plan.

        Flow:
          canonical product selections
                  ↓
          M6 deterministic mixed-basket planner (computes allocations + authoritative total)
                  ↓
          M5 deterministic policy / spend-cap evaluation
                  ↓
          authorized / requires approval / rejected
        """
        if not plan.is_feasible:
            return {
                "status": "REJECTED",
                "is_authorized": False,
                "plan": plan,
                "spend_cap_paise": intent.spend_cap_paise if intent else spend_cap_paise,
                "total_price_paise": plan.total_price_paise,
                "overspend_paise": 0,
                "rejection_reason": plan.rejection_reason or "Basket is commercially infeasible.",
                "escalation_details": None,
            }

        cap = (
            intent.spend_cap_paise
            if intent is not None
            else (spend_cap_paise if spend_cap_paise is not None else 150000)
        )

        if plan.total_price_paise <= cap:
            return {
                "status": "AUTHORIZED",
                "is_authorized": True,
                "plan": plan,
                "spend_cap_paise": cap,
                "total_price_paise": plan.total_price_paise,
                "overspend_paise": 0,
                "rejection_reason": None,
                "escalation_details": None,
            }
        else:
            overspend_paise = plan.total_price_paise - cap
            escalation_details = {
                "suggested_total_paise": plan.total_price_paise,
                "current_budget_paise": cap,
                "overspend_paise": overspend_paise,
                "message": (
                    f"Mixed-basket plan total of Rs. {plan.total_price_paise / 100:.2f} "
                    f"exceeds your Rs. {cap / 100:.2f} budget by Rs. {overspend_paise / 100:.2f}. "
                    f"User re-authorization required."
                ),
            }
            return {
                "status": "REQUIRES_USER_APPROVAL",
                "is_authorized": False,
                "plan": plan,
                "spend_cap_paise": cap,
                "total_price_paise": plan.total_price_paise,
                "overspend_paise": overspend_paise,
                "rejection_reason": escalation_details["message"],
                "escalation_details": escalation_details,
            }

    def plan_and_evaluate_basket(
        self,
        proposed_items: Sequence[dict[str, Any]],
        intent: UserIntentCredential | None = None,
        allowed_merchant_ids: Sequence[str] | None = None,
        spend_cap_paise: int | None = None,
        policy: OptimizationPolicy = OptimizationPolicy.LOWEST_TOTAL_PRICE,
    ) -> dict[str, Any]:
        """Full M6 -> M5 pipeline: plans commercially (M6), then evaluates policy authorization (M5)."""
        merchants = allowed_merchant_ids or (intent.allowed_merchant_ids if intent else list_known_merchant_ids())
        plan = self.plan_basket(
            proposed_items=proposed_items,
            allowed_merchant_ids=merchants,
            policy=policy,
        )
        return self.evaluate_basket_authorization(
            plan=plan,
            intent=intent,
            spend_cap_paise=spend_cap_paise,
        )


def deliberate_and_route_node_factory(
    db: Session,
    merchant_private_key_pem: bytes | str | Path | None = None,
) -> Callable[[BuyerAgentState], dict[str, Any]]:
    """Node 3 Factory: Selects canonical items via exactly one LLM call, then delegates to CommerceOrchestrator."""
    orchestrator = CommerceOrchestrator(db=db, merchant_private_key_pem=merchant_private_key_pem)

    def deliberate_and_route_node(state: BuyerAgentState) -> dict[str, Any]:
        candidates = state.get("catalog_candidates", [])
        if not candidates:
            return {
                "error": "No catalog items matched purchase criteria.",
                "status": "NO_CANDIDATE_MATCH",
                "escalation_details": None,
                "all_quotes": [],
                "routing_decision": None,
            }

        goal = state.get("goal", "")
        api_key = settings.GEMINI_API_KEY or settings.GOOGLE_API_KEY
        proposed_items: list[dict[str, Any]] = []
        llm_reasoning = None

        parsed_intent = state.get("parsed_intent", {})
        max_budget = parsed_intent.get("max_budget_paise")
        spend_cap = max_budget if max_budget is not None else state.get("spend_cap_paise", 150000)

        # 1. Live Gemini Deliberation: EXACTLY ONE LLM call for intent & canonical product selection
        # (LLM Blindness: Only Canonical Product Attributes; strictly NO merchant_id, SKU, or prices)
        if api_key and candidates:
            catalog_summary = "\n".join([
                f"- Product ID: {c['product_id']} | Name: {c['canonical_name']} | Brand: {c.get('brand') or 'N/A'} | Category: {c['category']} | Description: {c.get('description') or ''}"
                for c in candidates
            ])
            prompt = (
                f"You are an autonomous shopping agent for Mandate Mesh.\n"
                f"User Goal: '{goal}'\n\n"
                f"Available Canonical Products:\n{catalog_summary}\n\n"
                f"Instructions:\n"
                f"- Analyze the user goal. If the user asks for multiple items, select all matching product IDs and specify their quantities.\n"
                f"- If the user asks for a single item, select the single best product ID that matches the user's budget and category.\n"
                f"- If no item is strictly within budget, select the item that matches the specific requested product type and keywords.\n"
                f"- Respond ONLY with a JSON object in this exact format:\n"
                f'{{"items": [{{"product_id": "PRODUCT-UUID", "quantity": 1}}], "reasoning": "1 sentence explanation"}}\n'
            )
            llm_response = call_gemini_llm(prompt, api_key)
            if llm_response:
                try:
                    clean_json = re.sub(r"^```(?:json)?\s*|\s*```$", "", llm_response.strip(), flags=re.MULTILINE)
                    llm_choice = json.loads(clean_json)
                    valid_pids = {c["product_id"] for c in candidates}
                    if isinstance(llm_choice.get("items"), list) and len(llm_choice["items"]) > 0:
                        for it in llm_choice["items"]:
                            pid = it.get("product_id")
                            if pid in valid_pids:
                                proposed_items.append({
                                    "product_id": pid,
                                    "quantity": max(1, int(it.get("quantity", 1))),
                                })
                        llm_reasoning = llm_choice.get("reasoning")
                except Exception:
                    pass

        # 2. Deterministic Fallback Heuristic (Zero LLM calls)
        if not proposed_items:
            if state.get("proposed_items"):
                proposed_items = state["proposed_items"]
            else:
                cat = parsed_intent.get("category")
                eligible_candidates = [c for c in candidates if not cat or c["category"].lower() == cat.lower()] or candidates
                max_score = max((c.get("match_score", 0) for c in eligible_candidates), default=0)
                best_candidates = [c for c in eligible_candidates if c.get("match_score", 0) == max_score] or eligible_candidates
                chosen = best_candidates[0]
                qty = state.get("quantity", 1)
                proposed_items = [{"product_id": chosen["product_id"], "quantity": qty}]

        primary_qty = proposed_items[0]["quantity"] if proposed_items else 1
        allowed_merchants = state.get("allowed_merchant_ids") or list_known_merchant_ids()

        # 3. Hand off to Deterministic Commerce Orchestrator
        orchestration_result = orchestrator.orchestrate(
            proposed_items=proposed_items,
            intent=state.get("intent"),
            allowed_merchant_ids=allowed_merchants,
            spend_cap_paise=spend_cap,
        )

        return {
            "proposed_items": proposed_items,
            "selected_sku": orchestration_result["selected_sku"],
            "quantity": primary_qty,
            "signed_cart": orchestration_result["signed_cart"],
            "cart_jwt": orchestration_result["cart_jwt"],
            "all_quotes": orchestration_result["all_quotes"],
            "routing_decision": orchestration_result["routing_decision"],
            "llm_reasoning": llm_reasoning,
            "status": orchestration_result["status"],
            "escalation_details": orchestration_result["escalation_details"],
            "error": None,
        }

    return deliberate_and_route_node



# =============================================================================
# 4. LangGraph Buyer Agent Assembler & Runner
# =============================================================================

def build_buyer_agent_graph(
    db: Session,
    merchant_private_key_pem: bytes | str | Path | None = None,
):
    """Constructs and compiles the 3-node LangGraph Buyer Agent."""
    workflow = StateGraph(BuyerAgentState)

    workflow.add_node("parse_goal", parse_goal_node)
    workflow.add_node("browse_catalog", browse_catalog_node_factory(db))
    workflow.add_node("deliberate_and_route", deliberate_and_route_node_factory(db, merchant_private_key_pem))

    workflow.add_edge(START, "parse_goal")
    workflow.add_edge("parse_goal", "browse_catalog")
    workflow.add_edge("browse_catalog", "deliberate_and_route")
    workflow.add_edge("deliberate_and_route", END)

    return workflow.compile()


def run_buyer_agent(
    goal: str,
    db: Session,
    intent: UserIntentCredential | None = None,
    merchant_private_key_pem: bytes | str | Path | None = None,
    merchant_id: str = "merchant_cakehouse_01",
    allowed_merchant_ids: list[str] | None = None,
    spend_cap_paise: int = 150000,
    quantity: int = 1,
    proposed_items: list[dict[str, Any]] | None = None,
) -> BuyerAgentState:
    """Executes the buyer agent workflow with multi-merchant quote discovery.

    Args:
        goal: Natural language purchase goal from the user.
        db: SQLAlchemy database session.
        intent: Pre-minted UserIntentCredential.
        merchant_private_key_pem: Optional key override.
        merchant_id: Single merchant target (for backward compatibility).
        allowed_merchant_ids: List of candidate merchants to solicit.
        spend_cap_paise: Spending limit in paise.
        quantity: Desired quantity for single item default.
        proposed_items: Optional explicit list of items `[{"sku": str, "quantity": int}]`.

    Returns:
        BuyerAgentState: Final state containing all_quotes, routing_decision, signed_cart, cart_jwt, and status.
    """
    app = build_buyer_agent_graph(db, merchant_private_key_pem)

    merchants = allowed_merchant_ids
    if intent:
        merchants = intent.allowed_merchant_ids
        spend_cap_paise = intent.spend_cap_paise
    elif not merchants:
        merchants = [merchant_id]

    initial_state: BuyerAgentState = {
        "goal": goal,
        "parsed_intent": {},
        "catalog_candidates": [],
        "proposed_items": proposed_items or [],
        "selected_sku": None,
        "quantity": quantity,
        "spend_cap_paise": spend_cap_paise,
        "allowed_merchant_ids": merchants,
        "intent": intent,
        "all_quotes": [],
        "routing_decision": None,
        "cart_jwt": None,
        "signed_cart": None,
        "llm_reasoning": None,
        "status": "COMPLETED",
        "escalation_details": None,
        "error": None,
    }

    final_state = app.invoke(initial_state)
    return final_state
