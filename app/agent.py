"""LangGraph Buyer Agent for Mandate Mesh with Multi-Item Cart Support.

Enforces:
- Structural tool parameter constraints (ADR-001): `propose_cart` tool accepts `{items: list[{sku, quantity}]}`.
  It structurally lacks `price`, `amount`, `total`, or `discount` parameters.
- Prices are retrieved authoritatively from the database catalog during cart signing for each line item.
- Authoritative merchant summation: calculates subtotal and total across all requested line items.
- Prompt injection in goals or catalog descriptions cannot override authoritative pricing.
- Complete separation between agent selection tools and payment authorization/execution.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, TypedDict
import httpx
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from langgraph.graph import StateGraph, START, END

from app.config import settings
from app.errors import CatalogSkuNotFound
from app.merchant import sign_cart
from app.models import CatalogItem
from app.schemas import MerchantSignedCart


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
# 1. Structural Tool Input Schemas (Zero Price Parameters)
# =============================================================================

class BrowseCatalogInput(BaseModel):
    """Filter criteria for browsing the authoritative merchant catalog."""
    category: str | None = Field(None, description="Product category to filter by (e.g. bakery, electronics)")
    query: str | None = Field(None, description="Search keyword for item name or description")


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
# 2. Agent Tool Functions & Tool Registry
# =============================================================================

def browse_catalog_tool(
    db: Session,
    category: str | None = None,
    query: str | None = None,
) -> list[dict[str, Any]]:
    """Tool: Queries active items from the merchant catalog."""
    q = db.query(CatalogItem).filter(CatalogItem.in_stock.is_(True))
    if category:
        q = q.filter(CatalogItem.category.ilike(f"%{category}%"))

    items = q.all()
    results: list[dict[str, Any]] = []

    for item in items:
        if query:
            q_lower = query.lower()
            if q_lower not in item.name.lower() and q_lower not in (item.description or "").lower():
                continue

        results.append({
            "sku": item.sku,
            "name": item.name,
            "category": item.category,
            "description": item.description,
            "in_stock": item.in_stock,
            # Note: Display price in catalog is informational for browsing;
            # the cart signing endpoint strictly fetches the authoritative price from DB.
            "price_paise": item.price_paise,
        })

    return results


def propose_cart_tool(
    db: Session,
    merchant_private_key_pem: bytes | str | Path,
    sku: str | None = None,
    quantity: int = 1,
    items: list[dict[str, Any]] | None = None,
    merchant_id: str = "merchant_cakehouse_01",
) -> tuple[MerchantSignedCart, str]:
    """Tool: Submits proposed SKUs and quantities to the merchant for authoritative pricing, totaling, and signing.

    Accepts either a single (sku, quantity) pair or a list of items `[{"sku": str, "quantity": int}]`.

    Returns:
        tuple[MerchantSignedCart, str]: The signed cart model and signed cart JWT.
    """
    line_items_req: list[dict[str, Any]] = []
    if items:
        line_items_req = [{"sku": it["sku"], "quantity": int(it.get("quantity", 1))} for it in items]
    elif sku:
        line_items_req = [{"sku": sku, "quantity": quantity}]
    else:
        raise ValueError("Either 'items' or 'sku' must be provided.")

    # Verify all SKUs exist in catalog before signing
    for req in line_items_req:
        it_row = db.query(CatalogItem).filter_by(sku=req["sku"]).first()
        if not it_row:
            raise CatalogSkuNotFound(req["sku"])

    return sign_cart(
        merchant_id=merchant_id,
        line_items_req=line_items_req,
        merchant_private_key_pem=merchant_private_key_pem,
        db=db,
    )


# Static Tool Registry for boundary introspection
AGENT_TOOLS: list[dict[str, Any]] = [
    {
        "name": "browse_catalog",
        "description": "Browse active merchant catalog items by category and search keyword.",
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
    selected_sku: str | None  # Primary selected SKU for single-item backwards compatibility
    quantity: int
    cart_jwt: str | None
    signed_cart: MerchantSignedCart | None
    llm_reasoning: str | None
    status: str  # "COMPLETED", "REQUIRES_USER_APPROVAL", "ERROR"
    escalation_details: dict[str, Any] | None
    error: str | None


def parse_goal_node(state: BuyerAgentState) -> dict[str, Any]:
    """Node 1: Parses natural language goal into structured purchase criteria."""
    goal_text = state.get("goal", "")
    api_key = settings.GEMINI_API_KEY or settings.GOOGLE_API_KEY

    parsed: dict[str, Any] = {
        "keywords": [],
        "category": "bakery",  # Default category
        "max_budget_paise": None,
    }

    # 1. Live Gemini Parsing if API Key configured
    if api_key:
        prompt = (
            f"You are an e-commerce purchasing intent parser for Mandate Mesh.\n"
            f"User Goal: '{goal_text}'\n\n"
            f"Extract search keywords and category. Known merchant categories: 'bakery', 'gifting'. If unsure, set category to null.\n"
            f"Respond ONLY with a JSON object in this exact format (no markdown, no other text):\n"
            f'{{"category": "bakery", "keywords": ["keyword1", "keyword2"], "max_budget_paise": 150000}}\n'
            f"Note: 1 Rupee = 100 paise. If no budget is specified, set max_budget_paise to null."
        )
        llm_response = call_gemini_llm(prompt, api_key)
        if llm_response:
            try:
                clean_json = re.sub(r"^```(?:json)?\s*|\s*```$", "", llm_response.strip(), flags=re.MULTILINE)
                llm_parsed = json.loads(clean_json)
                if isinstance(llm_parsed, dict):
                    if llm_parsed.get("category"):
                        parsed["category"] = str(llm_parsed["category"]).lower()
                    if isinstance(llm_parsed.get("keywords"), list):
                        parsed["keywords"] = [str(k) for k in llm_parsed["keywords"]]
                    if llm_parsed.get("max_budget_paise"):
                        parsed["max_budget_paise"] = int(llm_parsed["max_budget_paise"])
                    return {"parsed_intent": parsed}
            except Exception:
                pass

    # 2. Heuristic fallback (offline / CI)
    # Range pattern: e.g. "between 700 to 1000" or "between Rs. 700 and Rs. 1000"
    range_match = re.search(r"between\s*(?:rs\.?|inr)?\s*(\d+)\s*(?:to|and|-)\s*(?:rs\.?|inr)?\s*(\d+)", goal_text, re.IGNORECASE)
    if range_match:
        parsed["max_budget_paise"] = int(range_match.group(2)) * 100
    else:
        # Single ceiling pattern: e.g. "under Rs. 1500", "budget 800", "within 1000"
        budget_match = re.search(r"(?:under|below|max|budget|within|up to|upto|less than)\s*(?:rs\.?|inr)?\s*(\d+)", goal_text, re.IGNORECASE)
        if budget_match:
            parsed["max_budget_paise"] = int(budget_match.group(1)) * 100

    words = [w.strip(",.!?\"'") for w in goal_text.split()]
    stop_words = {"order", "want", "please", "under", "with", "from", "between", "around", "about", "some", "like"}
    meaningful_words = [w for w in words if len(w) > 2 and not w.isdigit() and w.lower() not in stop_words]
    parsed["keywords"] = meaningful_words

    if any(k.lower() in ["cake", "pastry", "bakery", "bread"] for k in words):
        parsed["category"] = "bakery"
    elif any(k.lower() in ["card", "gift", "candle", "greeting"] for k in words):
        parsed["category"] = "gifting"
    else:
        parsed["category"] = None

    return {"parsed_intent": parsed}


def browse_catalog_node_factory(db: Session) -> Callable[[BuyerAgentState], dict[str, Any]]:
    """Node 2 Factory: Queries merchant catalog matching parsed intent."""
    def browse_catalog_node(state: BuyerAgentState) -> dict[str, Any]:
        intent = state.get("parsed_intent", {})
        keywords = intent.get("keywords", [])

        # Retrieve active in-stock merchant items
        items = browse_catalog_tool(db=db)

        # Filter and score by keywords
        matching_candidates: list[dict[str, Any]] = []
        for item in items:
            item_text = f"{item['name']} {item['description']} {item['category']}".lower()
            score = sum(1 for kw in keywords if kw.lower() in item_text)
            matching_candidates.append({**item, "match_score": score})

        # Sort by match score descending
        matching_candidates.sort(key=lambda x: x["match_score"], reverse=True)

        return {"catalog_candidates": matching_candidates}

    return browse_catalog_node


def select_and_propose_node_factory(
    db: Session,
    merchant_private_key_pem: bytes | str | Path,
    merchant_id: str = "merchant_cakehouse_01",
) -> Callable[[BuyerAgentState], dict[str, Any]]:
    """Node 3 Factory: Selects SKUs (single or multiple) and submits propose_cart tool call."""
    def select_and_propose_node(state: BuyerAgentState) -> dict[str, Any]:
        candidates = state.get("catalog_candidates", [])
        if not candidates:
            return {
                "error": "No catalog items matched purchase criteria.",
                "status": "ERROR",
                "escalation_details": None,
            }

        goal = state.get("goal", "")
        api_key = settings.GEMINI_API_KEY or settings.GOOGLE_API_KEY
        proposed_items: list[dict[str, Any]] = []
        llm_reasoning = None

        # 1. Live Gemini Deliberation if API Key configured (Multi-Item & Single-Item aware)
        if api_key and candidates:
            catalog_summary = "\n".join([
                f"- SKU: {c['sku']} | Name: {c['name']} | Category: {c['category']} | Description: {c['description']} | Price: Rs. {c['price_paise']/100:.2f}"
                for c in candidates
            ])
            prompt = (
                f"You are an autonomous shopping agent for Mandate Mesh.\n"
                f"User Goal: '{goal}'\n\n"
                f"Available Catalog Items:\n{catalog_summary}\n\n"
                f"Instructions:\n"
                f"- Analyze the user goal. If the user asks for multiple items (e.g. 1 cake and 2 breads), select all matching SKUs and specify their quantities.\n"
                f"- If the user asks for a single item, select the single best SKU.\n"
                f"- Respond ONLY with a JSON object in this exact format (no other text):\n"
                f'{{"items": [{{"sku": "SKU-CODE", "quantity": 1}}], "reasoning": "1 sentence explanation of why these items fulfill the goal"}}\n'
            )
            llm_response = call_gemini_llm(prompt, api_key)
            if llm_response:
                try:
                    clean_json = re.sub(r"^```(?:json)?\s*|\s*```$", "", llm_response.strip(), flags=re.MULTILINE)
                    llm_choice = json.loads(clean_json)
                    valid_skus = {c["sku"] for c in candidates}
                    if isinstance(llm_choice.get("items"), list) and len(llm_choice["items"]) > 0:
                        for it in llm_choice["items"]:
                            if it.get("sku") in valid_skus:
                                proposed_items.append({
                                    "sku": it["sku"],
                                    "quantity": max(1, int(it.get("quantity", 1))),
                                })
                        llm_reasoning = llm_choice.get("reasoning")
                except Exception:
                    pass

        # 2. Fallback heuristic (Single or multi selection from state)
        if not proposed_items:
            # Check if state already specified proposed items
            if state.get("proposed_items"):
                proposed_items = state["proposed_items"]
            else:
                # Default to top candidate
                chosen = candidates[0]
                qty = state.get("quantity", 1)
                proposed_items = [{"sku": chosen["sku"], "quantity": qty}]

        primary_sku = proposed_items[0]["sku"]
        primary_qty = proposed_items[0]["quantity"]

        try:
            signed_cart, cart_jwt = propose_cart_tool(
                db=db,
                items=proposed_items,
                merchant_private_key_pem=merchant_private_key_pem,
                merchant_id=merchant_id,
            )

            # Human-in-the-Loop Budget Escalation Evaluation
            parsed_intent = state.get("parsed_intent", {})
            max_budget_paise = parsed_intent.get("max_budget_paise")
            status = "COMPLETED"
            escalation_details = None

            if max_budget_paise is not None and signed_cart.total_paise > max_budget_paise:
                status = "REQUIRES_USER_APPROVAL"
                overspend_paise = signed_cart.total_paise - max_budget_paise
                escalation_details = {
                    "suggested_total_paise": signed_cart.total_paise,
                    "current_budget_paise": max_budget_paise,
                    "overspend_paise": overspend_paise,
                    "message": (
                        f"Matching item costs Rs. {signed_cart.total_paise / 100:.2f}, which is "
                        f"Rs. {overspend_paise / 100:.2f} over your Rs. {max_budget_paise / 100:.2f} budget. "
                        f"User re-authorization required."
                    ),
                }

            return {
                "proposed_items": proposed_items,
                "selected_sku": primary_sku,
                "quantity": primary_qty,
                "signed_cart": signed_cart,
                "cart_jwt": cart_jwt,
                "llm_reasoning": llm_reasoning,
                "status": status,
                "escalation_details": escalation_details,
                "error": None,
            }
        except Exception as e:
            return {
                "error": f"Cart proposal failed: {e}",
                "status": "ERROR",
                "escalation_details": None,
            }

    return select_and_propose_node


# =============================================================================
# 4. LangGraph Buyer Agent Assembler & Runner
# =============================================================================

def build_buyer_agent_graph(
    db: Session,
    merchant_private_key_pem: bytes | str | Path,
    merchant_id: str = "merchant_cakehouse_01",
):
    """Constructs and compiles the 3-node LangGraph Buyer Agent."""
    workflow = StateGraph(BuyerAgentState)

    workflow.add_node("parse_goal", parse_goal_node)
    workflow.add_node("browse_catalog", browse_catalog_node_factory(db))
    workflow.add_node("select_and_propose", select_and_propose_node_factory(db, merchant_private_key_pem, merchant_id))

    workflow.add_edge(START, "parse_goal")
    workflow.add_edge("parse_goal", "browse_catalog")
    workflow.add_edge("browse_catalog", "select_and_propose")
    workflow.add_edge("select_and_propose", END)

    return workflow.compile()


def run_buyer_agent(
    goal: str,
    db: Session,
    merchant_private_key_pem: bytes | str | Path,
    merchant_id: str = "merchant_cakehouse_01",
    quantity: int = 1,
    proposed_items: list[dict[str, Any]] | None = None,
) -> BuyerAgentState:
    """Executes the buyer agent workflow to produce an authoritative signed cart JWT.

    Args:
        goal: Natural language purchase goal from the user.
        db: SQLAlchemy database session.
        merchant_private_key_pem: Merchant private key for signing cart.
        merchant_id: Target merchant identifier.
        quantity: Desired quantity for single item default (defaults to 1).
        proposed_items: Optional explicit list of items `[{"sku": str, "quantity": int}]`.

    Returns:
        BuyerAgentState: Final state containing proposed_items, signed_cart, cart_jwt, status, and escalation_details.
    """
    app = build_buyer_agent_graph(db, merchant_private_key_pem, merchant_id)

    initial_state: BuyerAgentState = {
        "goal": goal,
        "parsed_intent": {},
        "catalog_candidates": [],
        "proposed_items": proposed_items or [],
        "selected_sku": None,
        "quantity": quantity,
        "cart_jwt": None,
        "signed_cart": None,
        "llm_reasoning": None,
        "status": "COMPLETED",
        "escalation_details": None,
        "error": None,
    }

    final_state = app.invoke(initial_state)
    return final_state
