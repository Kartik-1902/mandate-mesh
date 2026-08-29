"""Policy Rail Mandate Authorization & Reconciliation API."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import (
    get_db,
    get_platform_private_key_pem,
    get_razorpay_client,
    get_user_public_key_pem,
)
from app.crypto import extract_unverified_cart_merchant_id
from app.errors import PolicyViolation
from app.ledger import append_entry
from app.merchant_keys import get_merchant_public_key, MerchantKeyNotFound
from app.models import LedgerEntryType, MandateRecord, MandateStatus
from app.policy import authorize_mandate
from app.razorpay_client import RazorpayClient
from app.schemas import PaymentMandate

router = APIRouter(prefix="/api/v1/mandate", tags=["Mandates"])


class AuthorizeMandateRequest(BaseModel):
    intent_jwt: str
    cart_jwt: str
    idempotency_key: str


class AuthorizeMandateResponse(BaseModel):
    mandate: PaymentMandate
    mandate_jwt: str
    razorpay_order_id: str
    order_idempotency_key: str
    status: str


class ReconcileMandateResponse(BaseModel):
    mandate_id: str
    order_idempotency_key: str
    status: str
    razorpay_order_id: str | None
    reconciled: bool


@router.post("/authorize", status_code=status.HTTP_201_CREATED, response_model=AuthorizeMandateResponse)
def authorize_payment_mandate(
    req: AuthorizeMandateRequest,
    db: Session = Depends(get_db),
    razorpay_client: RazorpayClient = Depends(get_razorpay_client),
    user_pub: bytes = Depends(get_user_public_key_pem),
    platform_priv: bytes = Depends(get_platform_private_key_pem),
) -> AuthorizeMandateResponse:
    """Evaluates deterministic bounds, reserves spend cap, and creates Razorpay order."""
    # 0. Dynamically resolve trusted merchant public key from unverified cart header/claims
    unverified_mid = "unknown"
    try:
        unverified_mid = extract_unverified_cart_merchant_id(req.cart_jwt)
        resolved_merchant_pub = get_merchant_public_key(unverified_mid)
    except MerchantKeyNotFound as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown or untrusted merchant '{unverified_mid}': {e}",
        )
    except PolicyViolation as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid cart JWT: {e}",
        )

    # 1. Deterministic Policy Evaluation & Spend Reservation (State: RESERVED)
    mandate, mandate_jwt, record = authorize_mandate(
        intent_jwt=req.intent_jwt,
        cart_jwt=req.cart_jwt,
        idempotency_key=req.idempotency_key,
        user_public_key_pem=user_pub,
        merchant_public_key_pem=resolved_merchant_pub,
        platform_private_key_pem=platform_priv,
        db=db,
    )

    # 2. Pre-flight write to ORDER_CREATING before network call (ADR-005)
    record.status = MandateStatus.ORDER_CREATING
    db.commit()

    # 3. Call Razorpay Orders API with receipt = order_idempotency_key
    try:
        rzp_order = razorpay_client.create_order(
            amount_paise=mandate.authorized_amount_paise,
            currency=mandate.currency,
            receipt=record.order_idempotency_key,
            notes={
                "mandate_id": str(mandate.mandate_id),
                "intent_id": mandate.intent_id,
            },
        )
        record.razorpay_order_id = rzp_order["id"]
        record.status = MandateStatus.ORDER_CREATED
        append_entry(
            db=db,
            entry_type=LedgerEntryType.ORDER_CREATED,
            payload={
                "mandate_id": str(mandate.mandate_id),
                "razorpay_order_id": rzp_order["id"],
                "receipt": record.order_idempotency_key,
                "amount_paise": mandate.authorized_amount_paise,
            },
            actor="system:policy-rail",
        )
        db.commit()
    except Exception as e:
        # On network failure, record remains in ORDER_CREATING for reconciler recovery
        raise PolicyViolation(
            "GATEWAY_ORDER_CREATION_FAILED",
            f"Failed to create order at Razorpay: {e}. Record marked ORDER_CREATING for reconciliation.",
            http_status=502,
        ) from e

    return AuthorizeMandateResponse(
        mandate=mandate,
        mandate_jwt=mandate_jwt,
        razorpay_order_id=record.razorpay_order_id,
        order_idempotency_key=record.order_idempotency_key,
        status=record.status.value if hasattr(record.status, "value") else str(record.status),
    )


@router.post("/reconcile/{mandate_id}", response_model=ReconcileMandateResponse)
def reconcile_mandate_order(
    mandate_id: str,
    db: Session = Depends(get_db),
    razorpay_client: RazorpayClient = Depends(get_razorpay_client),
) -> ReconcileMandateResponse:
    """Performs application-level reconciliation for stuck ORDER_CREATING mandates (ADR-005)."""
    record = db.query(MandateRecord).filter_by(mandate_id=mandate_id).first()
    if not record:
        raise PolicyViolation("POLICY_MANDATE_NOT_FOUND", f"Mandate '{mandate_id}' not found.", http_status=404)

    # Reconcile via receipt reference
    existing_order = razorpay_client.reconcile_order(record.order_idempotency_key)

    if existing_order:
        record.razorpay_order_id = existing_order["id"]
        record.status = MandateStatus.ORDER_CREATED
        append_entry(
            db=db,
            entry_type=LedgerEntryType.ORDER_CREATED,
            payload={
                "mandate_id": record.mandate_id,
                "razorpay_order_id": existing_order["id"],
                "reconciled": True,
            },
            actor="system:reconciler",
        )
        db.commit()
        return ReconcileMandateResponse(
            mandate_id=record.mandate_id,
            order_idempotency_key=record.order_idempotency_key,
            status=record.status.value if hasattr(record.status, "value") else str(record.status),
            razorpay_order_id=record.razorpay_order_id,
            reconciled=True,
        )
    else:
        # No order created at Razorpay; reset status to RESERVED for clean retry
        record.status = MandateStatus.RESERVED
        db.commit()
        return ReconcileMandateResponse(
            mandate_id=record.mandate_id,
            order_idempotency_key=record.order_idempotency_key,
            status=record.status.value if hasattr(record.status, "value") else str(record.status),
            razorpay_order_id=None,
            reconciled=False,
        )
