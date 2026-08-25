"""Razorpay Inbound Webhook API."""

from typing import Any
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import (
    get_db,
    get_platform_private_key_pem,
    get_webhook_secret,
)
from app.webhooks import process_payment_webhook

router = APIRouter(prefix="/api/v1/webhooks", tags=["Webhooks"])


@router.post("/razorpay", status_code=status.HTTP_200_OK)
async def razorpay_webhook_endpoint(
    request: Request,
    x_razorpay_signature: str | None = Header(default=None),
    db: Session = Depends(get_db),
    webhook_secret: str = Depends(get_webhook_secret),
    platform_priv: bytes = Depends(get_platform_private_key_pem),
) -> dict[str, Any]:
    """Ingests inbound Razorpay webhooks and processes captures/failures atomically."""
    if not x_razorpay_signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing X-Razorpay-Signature header.",
        )

    # Read raw unparsed body bytes for HMAC verification
    raw_body = await request.body()

    return process_payment_webhook(
        raw_body=raw_body,
        signature=x_razorpay_signature,
        db=db,
        webhook_secret=webhook_secret,
        platform_private_key_pem=platform_priv,
    )
