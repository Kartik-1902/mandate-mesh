"""Agent interaction REST API endpoints for Mandate Mesh Control Tower."""

from typing import Any
from uuid import uuid4
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
from app.models import MandateStatus
from app.policy import authorize_mandate, verify_intent
from app.razorpay_client import RazorpayClient
from app.schemas import UserIntentCredential

router = APIRouter(prefix="/api/v1/agent", tags=["Buyer Agent"])


class DeliberateRequest(BaseModel):
    goal: str = Field(..., description="Natural language buyer goal")
    initial_budget_paise: int | None = Field(default=None, description="Initial budget in paise if specified")
    merchant_id: str = Field(default="merchant_cakehouse_01", description="Target merchant ID")


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
    merchant_priv: bytes = Depends(get_merchant_private_key_pem),
    merchant_pub: bytes = Depends(get_merchant_public_key_pem),
    platform_priv: bytes = Depends(get_platform_private_key_pem),
) -> DeliberateResponse:
    """Runs LangGraph Buyer Agent over catalog and returns deliberation state."""
    res = run_buyer_agent(
        goal=req.goal,
        db=db,
        merchant_private_key_pem=merchant_priv,
        merchant_id=req.merchant_id,
    )

    status = res.get("status", "COMPLETED")
    signed_cart = res.get("signed_cart")
    cart_jwt = res.get("cart_jwt")
    parsed_intent = res.get("parsed_intent", {})

    # If within budget, automatically execute mandate authorization & Razorpay order creation
    mandate_dict = None
    razorpay_order_id = None

    if status == "COMPLETED" and signed_cart and cart_jwt:
        max_budget = parsed_intent.get("max_budget_paise") if isinstance(parsed_intent, dict) else None
        spend_cap = max_budget if max_budget else signed_cart.total_paise
        # Collect all categories from signed cart items
        cart_categories = list({it.category for it in signed_cart.line_items}) if signed_cart else [category]
        if not cart_categories:
            cart_categories = ["bakery", "gifting"]
            
        # Mint initial UserIntentCredential
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        intent = UserIntentCredential(
            user_id="user_control_tower_01",
            spend_cap_paise=spend_cap,
            allowed_categories=cart_categories,
            allowed_merchant_ids=[req.merchant_id],
            nonce=uuid4().hex,
            not_before=now - timedelta(minutes=1),
            expires_at=now + timedelta(hours=1),
        )
        intent_jwt = issue_intent_jwt(intent, user_priv)
        verify_intent(intent_jwt, user_pub, db)
        db.commit()

        # Authorize mandate on policy rail
        try:
            mandate_obj, mandate_jwt, record = authorize_mandate(
                intent_jwt=intent_jwt,
                cart_jwt=cart_jwt,
                idempotency_key=f"tx_agent_{uuid4().hex[:8]}",
                user_public_key_pem=user_pub,
                merchant_public_key_pem=merchant_pub,
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
            # Policy blocked
            status = "POLICY_REJECTED"

    return DeliberateResponse(
        status=status,
        goal=req.goal,
        parsed_intent=parsed_intent if isinstance(parsed_intent, dict) else None,
        proposed_items=res.get("proposed_items", []),
        signed_cart=signed_cart.model_dump() if signed_cart else None,
        cart_jwt=cart_jwt,
        escalation_details=res.get("escalation_details"),
        llm_reasoning=res.get("llm_reasoning"),
        mandate=mandate_dict,
        razorpay_order_id=razorpay_order_id,
    )


@router.post("/escalate-and-pay")
def escalate_and_pay(
    req: EscalateAndPayRequest,
    db: Session = Depends(get_db),
    user_priv: bytes = Depends(get_user_private_key_pem),
    user_pub: bytes = Depends(get_user_public_key_pem),
    merchant_pub: bytes = Depends(get_merchant_public_key_pem),
    platform_priv: bytes = Depends(get_platform_private_key_pem),
) -> dict[str, Any]:
    """Human-in-the-Loop Re-Authorization: Signs elevated intent and completes payment."""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)

    # 1. User signs new elevated credential on device
    intent = UserIntentCredential(
        user_id=req.user_id,
        spend_cap_paise=req.approved_budget_paise,
        allowed_categories=["bakery", "gifting"],
        allowed_merchant_ids=[req.merchant_id],
        nonce=uuid4().hex,
        not_before=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
    )
    intent_jwt = issue_intent_jwt(intent, user_priv)
    verify_intent(intent_jwt, user_pub, db)
    db.commit()

    # 2. Authorize payment mandate
    mandate_obj, mandate_jwt, record = authorize_mandate(
        intent_jwt=intent_jwt,
        cart_jwt=req.cart_jwt,
        idempotency_key=f"tx_escalated_{uuid4().hex[:8]}",
        user_public_key_pem=user_pub,
        merchant_public_key_pem=merchant_pub,
        platform_private_key_pem=platform_priv,
        db=db,
    )

    # 3. Create Razorpay order
    rzp = RazorpayClient(mock_mode=True)
    rzp_order = rzp.create_order(
        amount_paise=record.authorized_amount_paise,
        currency="INR",
        receipt=record.order_idempotency_key,
    )
    record.status = MandateStatus.ORDER_CREATED
    record.razorpay_order_id = rzp_order["id"]
    db.commit()

    return {
        "status": "ORDER_CREATED",
        "intent_jwt": intent_jwt,
        "mandate_id": str(mandate_obj.mandate_id),
        "mandate_jwt": mandate_jwt,
        "intent_hash": mandate_obj.intent_hash,
        "cart_hash": mandate_obj.cart_hash,
        "authorized_amount_paise": mandate_obj.authorized_amount_paise,
        "razorpay_order_id": rzp_order["id"],
        "receipt_reference": record.order_idempotency_key,
    }
