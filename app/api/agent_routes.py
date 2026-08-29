"""Agent interaction REST API endpoints for Mandate Mesh Control Tower with Multi-Merchant Routing."""

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agent import run_buyer_agent
from app.api.deps import (
    get_db,
    get_merchant_private_key_pem,
    get_merchant_public_key_pem,
    get_platform_private_key_pem,
    get_user_private_key_pem,
    get_user_public_key_pem,
)
from app.crypto import issue_intent_jwt
from app.merchant_keys import get_merchant_public_key, list_known_merchant_ids
from app.models import MandateStatus
from app.policy import authorize_mandate, verify_intent
from app.quote_router import route_with_fallback
from app.razorpay_client import RazorpayClient
from app.schemas import UserIntentCredential
from app.schemas_routing import (
    CandidateQuoteResponse,
    OptimizationPolicy,
    RoutingDecision,
    RoutingDecisionResponse,
)

router = APIRouter(prefix="/api/v1/agent", tags=["Buyer Agent"])


class DeliberateRequest(BaseModel):
    request_id: UUID = Field(default_factory=uuid4, description="Unique client request ID for deterministic idempotency")
    goal: str = Field(..., description="Natural language buyer goal")
    allowed_merchant_ids: list[str] | None = Field(default=None, description="Authorized candidate merchant IDs")
    spend_cap_paise: int = Field(default=150000, description="Spending ceiling in paise (default ₹1,500.00)")
    merchant_id: str | None = Field(default=None, description="Target merchant ID (legacy backward compatibility)")
    initial_budget_paise: int | None = Field(default=None, description="Initial budget in paise if specified")


class DeliberateResponse(BaseModel):
    status: str
    goal: str
    parsed_intent: dict[str, Any] | None
    proposed_items: list[dict[str, Any]]
    signed_cart: dict[str, Any] | None
    cart_jwt: str | None
    escalation_details: dict[str, Any] | None
    llm_reasoning: str | None
    mandate: dict[str, Any] | None = None
    razorpay_order_id: str | None = None
    routing_decision: RoutingDecisionResponse | None = None
    candidate_quotes: list[CandidateQuoteResponse] = Field(default_factory=list)


class EscalateAndPayRequest(BaseModel):
    cart_jwt: str
    approved_budget_paise: int
    user_id: str = "user_control_tower_01"
    merchant_id: str = "merchant_cakehouse_01"


@router.post("/deliberate", response_model=DeliberateResponse)
def deliberate_goal(
    req: DeliberateRequest,
    db: Session = Depends(get_db),
    user_priv: bytes = Depends(get_user_private_key_pem),
    user_pub: bytes = Depends(get_user_public_key_pem),
    platform_priv: bytes = Depends(get_platform_private_key_pem),
) -> DeliberateResponse:
    """Runs LangGraph Buyer Agent with Multi-Merchant Routing and Pre-Agent Intent Minting."""
    known_merchants = list_known_merchant_ids()

    # 1. Resolve authorized candidate merchants
    if req.allowed_merchant_ids:
        target_merchants = req.allowed_merchant_ids
    elif req.merchant_id:
        target_merchants = [req.merchant_id]
    else:
        target_merchants = known_merchants

    # Validate that all requested merchants are known registered merchants
    for mid in target_merchants:
        if mid not in known_merchants:
            raise HTTPException(
                status_code=400,
                detail=f"Requested merchant '{mid}' is not a registered merchant identity.",
            )

    spend_cap = req.initial_budget_paise or req.spend_cap_paise

    # 2. Pre-Agent Intent Minting (Patch 4 / Invariant 1)
    now = datetime.now(timezone.utc)
    intent = UserIntentCredential(
        user_id="user_control_tower_01",
        spend_cap_paise=spend_cap,
        allowed_categories=["bakery", "gifting", "electronics"],
        allowed_merchant_ids=target_merchants,
        nonce=uuid4().hex,
        not_before=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
    )
    intent_jwt = issue_intent_jwt(intent, user_priv)
    verify_intent(intent_jwt, user_pub, db)
    db.commit()

    # 3. Execute LangGraph Buyer Agent within minted Intent boundary
    res = run_buyer_agent(
        goal=req.goal,
        db=db,
        intent=intent,
        allowed_merchant_ids=target_merchants,
        spend_cap_paise=spend_cap,
    )

    status = res.get("status", "COMPLETED")
    all_quotes = res.get("all_quotes", [])

    # Milestone M6: Automated Just-In-Time Fallback Revalidation across candidate quotes pool
    routing_decision, winner_quote = route_with_fallback(
        quotes=all_quotes,
        intent=intent,
        policy=OptimizationPolicy.LOWEST_TOTAL_PRICE,
        db=db,
    )
    winner_total = winner_quote.total_paise if winner_quote else None

    # Safe external projection of all candidate quotes (omitting raw JWTs per ADR-002 / Patch 1)
    candidate_quotes = [
        CandidateQuoteResponse.from_merchant_quote(
            quote=q,
            is_winner=(winner_quote is not None and q.merchant_id == winner_quote.merchant_id),
            winner_total_paise=winner_total,
        )
        for q in all_quotes
    ]

    mandate_dict = None
    razorpay_order_id = None
    signed_cart = winner_quote.signed_cart if winner_quote else res.get("signed_cart")
    cart_jwt = winner_quote.cart_jwt if winner_quote else res.get("cart_jwt")

    # 4. If an eligible winner exists within budget, authorize payment mandate & Razorpay order
    if status == "COMPLETED" and winner_quote and winner_quote.cart_jwt:
        try:
            winner_pub = get_merchant_public_key(winner_quote.merchant_id)
            tx_idempotency_key = f"tx_agent_{req.request_id.hex}"

            mandate_obj, mandate_jwt, record = authorize_mandate(
                intent_jwt=intent_jwt,
                cart_jwt=winner_quote.cart_jwt,
                idempotency_key=tx_idempotency_key,
                user_public_key_pem=user_pub,
                merchant_public_key_pem=winner_pub,
                platform_private_key_pem=platform_priv,
                db=db,
            )

            # Create mock Razorpay order
            rzp = RazorpayClient(mock_mode=True)
            rzp_order = rzp.create_order(
                amount_paise=record.authorized_amount_paise,
                currency="INR",
                receipt=record.order_idempotency_key,
            )
            record.status = MandateStatus.ORDER_CREATED
            record.razorpay_order_id = rzp_order["id"]
            db.commit()

            mandate_dict = {
                "mandate_id": str(mandate_obj.mandate_id),
                "intent_id": str(mandate_obj.intent_id),
                "intent_hash": mandate_obj.intent_hash,
                "cart_hash": mandate_obj.cart_hash,
                "authorized_amount_paise": mandate_obj.authorized_amount_paise,
                "mandate_jwt": mandate_jwt,
                "status": record.status.value,
            }
            razorpay_order_id = rzp_order["id"]
        except Exception:
            status = "POLICY_REJECTED"

    signed_cart_dict = None
    if signed_cart:
        signed_cart_dict = signed_cart.model_dump()
        signed_cart_dict["cart_id"] = str(signed_cart.cart_id)

    routing_decision_resp = (
        RoutingDecisionResponse.from_routing_decision(routing_decision)
        if routing_decision
        else None
    )

    return DeliberateResponse(
        status=status,
        goal=req.goal,
        parsed_intent=res.get("parsed_intent"),
        proposed_items=res.get("proposed_items", []),
        signed_cart=signed_cart_dict,
        cart_jwt=cart_jwt,
        escalation_details=res.get("escalation_details"),
        llm_reasoning=res.get("llm_reasoning"),
        mandate=mandate_dict,
        razorpay_order_id=razorpay_order_id,
        routing_decision=routing_decision_resp,
        candidate_quotes=candidate_quotes,
    )


@router.post("/escalate-and-pay", response_model=DeliberateResponse)
def escalate_and_pay(
    req: EscalateAndPayRequest,
    db: Session = Depends(get_db),
    user_priv: bytes = Depends(get_user_private_key_pem),
    user_pub: bytes = Depends(get_user_public_key_pem),
    platform_priv: bytes = Depends(get_platform_private_key_pem),
) -> DeliberateResponse:
    """Human-in-the-Loop budget escalation (ADR-007): Mints upgraded intent and authorizes mandate."""
    merchant_pub = get_merchant_public_key(req.merchant_id)

    now = datetime.now(timezone.utc)
    intent = UserIntentCredential(
        user_id=req.user_id,
        spend_cap_paise=req.approved_budget_paise,
        allowed_categories=["bakery", "gifting", "electronics"],
        allowed_merchant_ids=[req.merchant_id],
        nonce=uuid4().hex,
        not_before=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
    )
    intent_jwt = issue_intent_jwt(intent, user_priv)
    verify_intent(intent_jwt, user_pub, db)
    db.commit()

    try:
        mandate_obj, mandate_jwt, record = authorize_mandate(
            intent_jwt=intent_jwt,
            cart_jwt=req.cart_jwt,
            idempotency_key=f"tx_agent_{uuid4().hex}",
            user_public_key_pem=user_pub,
            merchant_public_key_pem=merchant_pub,
            platform_private_key_pem=platform_priv,
            db=db,
        )

        rzp = RazorpayClient(mock_mode=True)
        rzp_order = rzp.create_order(
            amount_paise=record.authorized_amount_paise,
            currency="INR",
            receipt=record.order_idempotency_key,
        )
        record.status = MandateStatus.ORDER_CREATED
        record.razorpay_order_id = rzp_order["id"]
        db.commit()

        mandate_dict = {
            "mandate_id": str(mandate_obj.mandate_id),
            "intent_id": str(mandate_obj.intent_id),
            "intent_hash": mandate_obj.intent_hash,
            "cart_hash": mandate_obj.cart_hash,
            "authorized_amount_paise": mandate_obj.authorized_amount_paise,
            "mandate_jwt": mandate_jwt,
            "status": record.status.value,
        }
        return DeliberateResponse(
            status="COMPLETED",
            goal="User re-authorized budget escalation",
            parsed_intent={"max_budget_paise": req.approved_budget_paise},
            proposed_items=[],
            signed_cart=None,
            cart_jwt=req.cart_jwt,
            escalation_details=None,
            llm_reasoning="Human operator approved budget increase.",
            mandate=mandate_dict,
            razorpay_order_id=rzp_order["id"],
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Policy authorization failed: {e}")
