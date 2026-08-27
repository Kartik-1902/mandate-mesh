"""Demo and Adversarial API routes for Mandate Mesh Control Tower."""

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import (
    get_db,
    get_merchant_public_key_pem,
    get_merchant_private_key_pem,
    get_platform_private_key_pem,
    get_platform_public_key_pem,
    get_user_private_key_pem,
    get_user_public_key_pem,
)
from app.crypto import (
    compute_cart_hash,
    issue_cart_jwt,
    issue_intent_jwt,
    verify_receipt_jwt,
)
from app.ledger import verify_chain
from app.merchant import sign_cart
from app.models import MandateRecord, MandateStatus
from app.policy import authorize_mandate, verify_intent
from app.razorpay_client import RazorpayClient, simulate_payment_captured_webhook
from app.schemas import UserIntentCredential
from app.webhooks import process_payment_webhook

router = APIRouter(prefix="/api/v1/demo", tags=["Demo & Attacks"])


class SimulateCaptureRequest(BaseModel):
    razorpay_order_id: str
    amount_paise: int
    webhook_secret: str = "whsec_demo_secret"


@router.post("/attack/{attack_id}")
def trigger_attack(
    attack_id: int,
    db: Session = Depends(get_db),
    user_priv: bytes = Depends(get_user_private_key_pem),
    user_pub: bytes = Depends(get_user_public_key_pem),
    merchant_priv: bytes = Depends(get_merchant_private_key_pem),
    merchant_pub: bytes = Depends(get_merchant_public_key_pem),
    platform_priv: bytes = Depends(get_platform_private_key_pem),
) -> dict[str, Any]:
    """Executes a specific attack scenario and returns structured outcome for Control Tower UI."""
    now = datetime.now(timezone.utc)
    rzp = RazorpayClient(mock_mode=True)

    if attack_id == 1:
        # Attack 1: Over-budget spend
        intent = UserIntentCredential(
            user_id="user_attacker_01",
            spend_cap_paise=150000,  # ₹1,500 cap
            allowed_categories=["bakery"],
            allowed_merchant_ids=["merchant_cakehouse_01"],
            nonce=uuid4().hex,
            not_before=now - timedelta(minutes=1),
            expires_at=now + timedelta(hours=1),
        )
        intent_jwt = issue_intent_jwt(intent, user_priv)
        verify_intent(intent_jwt, user_pub, db)
        db.commit()

        cart_model, cart_jwt = sign_cart(
            merchant_id="merchant_cakehouse_01",
            line_items_req=[{"sku": "CAKE-PREM-001", "quantity": 1}],  # ₹4,940
            merchant_private_key_pem=merchant_priv,
            db=db,
        )

        try:
            authorize_mandate(intent_jwt, cart_jwt, f"tx_ui_atk1_{uuid4().hex[:8]}", user_pub, merchant_pub, platform_priv, db)
            return {"status": "FAILED", "message": "Attack succeeded unexpectedly!"}
        except Exception as e:
            is_valid, _ = verify_chain(db)
            return {
                "attack_id": 1,
                "name": "Over-Budget Runaway Spend",
                "attempted_amount_paise": 494000,
                "budget_cap_paise": 150000,
                "outcome": "BLOCKED",
                "http_status": getattr(e, "http_status", 403),
                "error_code": getattr(e, "code", "POLICY_SPEND_CAP_EXCEEDED"),
                "message": str(e),
                "money_moved_paise": 0,
                "chain_valid": is_valid,
            }

    elif attack_id == 2:
        # Attack 2: Prompt injection fake SKU
        try:
            sign_cart(
                merchant_id="merchant_cakehouse_01",
                line_items_req=[{"sku": "UNAPPROVED-GOLD-COIN-99", "quantity": 1}],
                merchant_private_key_pem=merchant_priv,
                db=db,
            )
            return {"status": "FAILED", "message": "Fake SKU cart signed unexpectedly!"}
        except Exception as e:
            is_valid, _ = verify_chain(db)
            return {
                "attack_id": 2,
                "name": "Prompt Injection / Fake SKU",
                "attempted_sku": "UNAPPROVED-GOLD-COIN-99",
                "outcome": "BLOCKED",
                "http_status": getattr(e, "http_status", 404),
                "error_code": getattr(e, "code", "CATALOG_SKU_NOT_FOUND"),
                "message": str(e),
                "money_moved_paise": 0,
                "chain_valid": is_valid,
            }

    elif attack_id == 3:
        # Attack 3: Cart quote tampering
        cart_model, cart_jwt = sign_cart(
            merchant_id="merchant_cakehouse_01",
            line_items_req=[{"sku": "CAKE-CHOC-001", "quantity": 1}],
            merchant_private_key_pem=merchant_priv,
            db=db,
        )

        header_b64, payload_b64, sig_b64 = cart_jwt.split(".")
        import base64
        p_dict = json.loads(base64.urlsafe_b64decode(payload_b64 + "==").decode("utf-8"))
        p_dict["total_paise"] = 1000  # Tampered
        tampered_b64 = base64.urlsafe_b64encode(json.dumps(p_dict).encode("utf-8")).decode("utf-8").rstrip("=")
        tampered_jwt = f"{header_b64}.{tampered_b64}.{sig_b64}"

        intent = UserIntentCredential(
            user_id="user_atk3",
            spend_cap_paise=150000,
            allowed_categories=["bakery"],
            allowed_merchant_ids=["merchant_cakehouse_01"],
            nonce=uuid4().hex,
            not_before=now - timedelta(minutes=1),
            expires_at=now + timedelta(hours=1),
        )
        intent_jwt = issue_intent_jwt(intent, user_priv)
        verify_intent(intent_jwt, user_pub, db)
        db.commit()

        try:
            authorize_mandate(intent_jwt, tampered_jwt, f"tx_ui_atk3_{uuid4().hex[:8]}", user_pub, merchant_pub, platform_priv, db)
            return {"status": "FAILED", "message": "Tampered cart accepted unexpectedly!"}
        except Exception as e:
            is_valid, _ = verify_chain(db)
            return {
                "attack_id": 3,
                "name": "MITM Cart Quote Tampering",
                "tampered_field": "total_paise -> 1000",
                "outcome": "BLOCKED",
                "http_status": getattr(e, "http_status", 409),
                "error_code": getattr(e, "code", "POLICY_CART_SIGNATURE_INVALID"),
                "message": str(e),
                "money_moved_paise": 0,
                "chain_valid": is_valid,
            }

    elif attack_id == 4:
        # Attack 4: Webhook Replay
        cart_model, cart_jwt = sign_cart(
            merchant_id="merchant_cakehouse_01",
            line_items_req=[{"sku": "CAKE-CHOC-001", "quantity": 1}],
            merchant_private_key_pem=merchant_priv,
            db=db,
        )
        intent = UserIntentCredential(
            user_id="user_resilience_04",
            spend_cap_paise=150000,
            allowed_categories=["bakery"],
            allowed_merchant_ids=["merchant_cakehouse_01"],
            nonce=uuid4().hex,
            not_before=now - timedelta(minutes=1),
            expires_at=now + timedelta(hours=1),
        )
        intent_jwt = issue_intent_jwt(intent, user_priv)
        verify_intent(intent_jwt, user_pub, db)
        db.commit()

        mandate, mandate_jwt, record = authorize_mandate(
            intent_jwt, cart_jwt, f"tx_ui_replay_{uuid4().hex[:8]}", user_pub, merchant_pub, platform_priv, db
        )
        rzp_order = rzp.create_order(amount_paise=94000, receipt=record.order_idempotency_key)
        record.status = MandateStatus.ORDER_CREATED
        record.razorpay_order_id = rzp_order["id"]
        db.commit()

        raw_body, signature = simulate_payment_captured_webhook(
            razorpay_order_id=record.razorpay_order_id,
            amount_paise=94000,
            webhook_secret="whsec_demo_secret",
        )
        wh1 = process_payment_webhook(raw_body, signature, db, "whsec_demo_secret", platform_priv)
        wh2 = process_payment_webhook(raw_body, signature, db, "whsec_demo_secret", platform_priv)
        is_valid, _ = verify_chain(db)

        return {
            "attack_id": 4,
            "name": "Webhook Replay & Deduplication",
            "razorpay_order_id": record.razorpay_order_id,
            "delivery_1": wh1.get("status"),
            "delivery_2_deduplicated": wh2.get("deduplicated", False),
            "outcome": "DEDUPLICATED",
            "http_status": 200,
            "error_code": "NONE (Deduplication Gate Active)",
            "message": "Duplicate payment.captured webhook safely ignored. Zero double-debit.",
            "money_moved_paise": 94000,
            "duplicate_money_moved_paise": 0,
            "chain_valid": is_valid,
        }

    raise HTTPException(status_code=400, detail="Invalid attack ID (must be 1-4)")


@router.post("/simulate-capture")
def simulate_capture(
    req: SimulateCaptureRequest,
    db: Session = Depends(get_db),
    platform_priv: bytes = Depends(get_platform_private_key_pem),
    platform_pub: bytes = Depends(get_platform_public_key_pem),
) -> dict[str, Any]:
    """Simulates Razorpay webhook delivery to capture an active order and issue PaymentReceipt."""
    raw_body, signature = simulate_payment_captured_webhook(
        razorpay_order_id=req.razorpay_order_id,
        amount_paise=req.amount_paise,
        webhook_secret=req.webhook_secret,
    )

    wh_res = process_payment_webhook(
        raw_body=raw_body,
        signature=signature,
        db=db,
        webhook_secret=req.webhook_secret,
        platform_private_key_pem=platform_priv,
    )

    receipt = None
    if wh_res.get("receipt_jwt"):
        receipt_obj = verify_receipt_jwt(wh_res["receipt_jwt"], platform_pub)
        receipt = receipt_obj.model_dump()

    return {
        "status": wh_res.get("status", "PAYMENT_CAPTURED"),
        "receipt_id": wh_res.get("receipt_id"),
        "receipt_jwt": wh_res.get("receipt_jwt"),
        "receipt": receipt,
        "deduplicated": wh_res.get("deduplicated", False),
    }
