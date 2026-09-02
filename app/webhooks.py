"""Atomic webhook processing engine for Razorpay events.

Enforces:
- Strict 9-point validation protocol (ADR-006).
- Idempotent duplicate event deduplication via `WebhookEvent`.
- Single atomic database transaction spanning state transition, accounting updates,
  receipt issuance, and audit ledger entries.

NOTE: Per ADR-006, the webhook payload is NEVER the authoritative source of truth
for the captured amount. The expected amount is strictly `MandateRecord.authorized_amount_paise`.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.crypto import extract_mandate_intent_hash, issue_receipt_jwt
from app.errors import PolicyViolation
from app.ledger import append_entry
from app.mandate_fsm import transition
from app.models import (
    IntentRegistry,
    LedgerEntryType,
    MandateRecord,
    MandateStatus,
    WebhookEvent,
    WebhookEventStatus,
)
from app.razorpay_client import verify_webhook_signature
from app.schemas import PaymentReceipt


def process_payment_webhook(
    raw_body: bytes,
    signature: str,
    db: Session,
    webhook_secret: str,
    platform_private_key_pem: bytes | str | Path,
    platform_kid: str = "platform:key-1",
) -> dict[str, Any]:
    """Processes inbound Razorpay webhooks atomically with strict 9-point validation.

    NOTE: Concurrency safety in production is guaranteed by PostgreSQL row locks and
    database uniqueness constraints (e.g. uq_webhook_event). SQLite in local development
    is single-threaded.

    Args:
        raw_body: Raw request body bytes (unparsed JSON).
        signature: `X-Razorpay-Signature` header value.
        db: SQLAlchemy database session.
        webhook_secret: Configured Razorpay webhook secret.
        platform_private_key_pem: Platform private key for signing PaymentReceipt.
        platform_kid: Platform key identifier.

    Returns:
        dict: Summary of processing result.
    """
    # 1. HMAC Signature Verification over raw bytes
    if not verify_webhook_signature(raw_body, signature, webhook_secret):
        raise PolicyViolation(
            "POLICY_WEBHOOK_SIGNATURE_INVALID",
            "Webhook signature verification failed.",
            http_status=401,
        )

    try:
        event_data = json.loads(raw_body.decode("utf-8"))
    except Exception as e:
        raise PolicyViolation("POLICY_WEBHOOK_MALFORMED", f"Invalid JSON payload: {e}", http_status=400) from e

    event_id = event_data.get("event_id") or event_data.get("id") or str(uuid4())
    event_type = event_data.get("event")

    if not event_type:
        raise PolicyViolation("POLICY_WEBHOOK_MALFORMED", "Missing event type in webhook payload.", http_status=400)

    # 2. WebhookEvent Deduplication Check
    existing_event = (
        db.query(WebhookEvent)
        .filter_by(razorpay_event_id=event_id, event_type=event_type)
        .first()
    )
    if existing_event:
        return {
            "received": True,
            "deduplicated": True,
            "event_id": event_id,
            "message": "Event already processed.",
        }

    # =========================================================================
    # Event: payment.captured
    # =========================================================================
    if event_type == "payment.captured":
        try:
            payment_entity = event_data["payload"]["payment"]["entity"]
            order_id = payment_entity["order_id"]
            payment_id = payment_entity["id"]
            amount_paise = int(payment_entity["amount"])
            currency = payment_entity.get("currency", "INR")
            payment_status = payment_entity.get("status")
        except KeyError as e:
            raise PolicyViolation("POLICY_WEBHOOK_MALFORMED", f"Missing field in payment entity: {e}", http_status=400) from e

        # 3 & 4. Lookup MandateRecord by razorpay_order_id
        mandate_record = (
            db.query(MandateRecord)
            .filter_by(razorpay_order_id=order_id)
            .first()
        )
        if not mandate_record:
            raise PolicyViolation(
                "POLICY_MANDATE_NOT_FOUND",
                f"No mandate found matching Razorpay order_id '{order_id}'.",
                http_status=404,
            )

        # Handle duplicate delivery where mandate is already captured
        if mandate_record.status == MandateStatus.PAYMENT_CAPTURED:
            return {
                "received": True,
                "deduplicated": True,
                "event_id": event_id,
                "status": "PAYMENT_CAPTURED",
                "message": "Payment already captured.",
            }

        # 5. Strict Amount Verification against MandateRecord
        if amount_paise != mandate_record.authorized_amount_paise:
            raise PolicyViolation(
                "POLICY_WEBHOOK_AMOUNT_MISMATCH",
                f"Captured amount Rs. {amount_paise / 100:.2f} does not match authorized amount Rs. {mandate_record.authorized_amount_paise / 100:.2f}.",
                http_status=409,
                details={
                    "webhook_amount_paise": amount_paise,
                    "authorized_amount_paise": mandate_record.authorized_amount_paise,
                },
            )

        # 6. Currency Verification
        expected_currency = getattr(mandate_record, "currency", "INR")
        if currency != expected_currency:
            raise PolicyViolation(
                "POLICY_WEBHOOK_CURRENCY_MISMATCH",
                f"Captured currency '{currency}' does not match authorized currency '{expected_currency}'.",
                http_status=409,
            )

        # 7. Payment Capture Status Check
        if payment_status != "captured":
            raise PolicyViolation(
                "POLICY_WEBHOOK_STATUS_INVALID",
                f"Payment status is '{payment_status}', expected 'captured'.",
                http_status=409,
            )

        # 8. Mandate State Check
        valid_pre_capture_states = (
            MandateStatus.ORDER_CREATED,
            MandateStatus.PAYMENT_PENDING,
        )
        if mandate_record.status not in valid_pre_capture_states:
            raise PolicyViolation(
                "POLICY_MANDATE_STATE_INVALID",
                f"Mandate state '{mandate_record.status}' is not eligible for capture.",
                http_status=409,
            )

        # 9. Intent Registry Balance Check
        intent_reg = (
            db.query(IntentRegistry)
            .filter_by(intent_id=mandate_record.intent_id)
            .first()
        )
        if not intent_reg or intent_reg.reserved_paise < amount_paise:
            raise PolicyViolation(
                "POLICY_RESERVATION_NOT_FOUND",
                "Insufficient reservation balance in IntentRegistry to complete capture.",
                http_status=409,
            )

        # =====================================================================
        # Atomic State Mutation & Receipt Issuance
        # =====================================================================
        now = datetime.now(timezone.utc)

        # Update MandateRecord via FSM transition
        transition(mandate_record, MandateStatus.PAYMENT_CAPTURED, db)
        mandate_record.captured_paise = amount_paise
        mandate_record.reserved_paise = 0
        mandate_record.razorpay_payment_id = payment_id

        # Update IntentRegistry accounting
        intent_reg.reserved_paise -= amount_paise
        intent_reg.captured_paise += amount_paise

        # Record deduplication entry
        webhook_event = WebhookEvent(
            razorpay_event_id=event_id,
            event_type=event_type,
            razorpay_order_id=order_id,
            razorpay_payment_id=payment_id,
            raw_payload=event_data,
            status=WebhookEventStatus.PROCESSED,
        )
        db.add(webhook_event)

        # Issue PaymentReceipt
        receipt_id = uuid4()
        intent_hash = extract_mandate_intent_hash(mandate_record.mandate_jwt) if mandate_record.mandate_jwt else ""
        receipt = PaymentReceipt(
            receipt_id=receipt_id,
            mandate_id=UUID(mandate_record.mandate_id),
            intent_hash=intent_hash,
            cart_hash=mandate_record.cart_hash,
            razorpay_order_id=order_id,
            razorpay_payment_id=payment_id,
            amount_captured_paise=amount_paise,
            captured_at=now,
            currency=currency,
        )

        receipt_jwt = issue_receipt_jwt(receipt, platform_private_key_pem, kid=platform_kid)

        # Audit Ledger Appends
        append_entry(
            db=db,
            entry_type=LedgerEntryType.WEBHOOK_RECEIVED,
            payload={"event_id": event_id, "event_type": event_type, "order_id": order_id},
            actor="gateway:razorpay",
        )
        append_entry(
            db=db,
            entry_type=LedgerEntryType.PAYMENT_CAPTURED,
            payload={"order_id": order_id, "payment_id": payment_id, "amount_paise": amount_paise},
            actor="system:policy-rail",
        )
        append_entry(
            db=db,
            entry_type=LedgerEntryType.RECEIPT_ISSUED,
            payload={
                "receipt_id": str(receipt_id),
                "mandate_id": mandate_record.mandate_id,
                "order_id": order_id,
                "payment_id": payment_id,
                "amount_paise": amount_paise,
            },
            actor="system:policy-rail",
        )

        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return {
                "received": True,
                "deduplicated": True,
                "event_id": event_id,
                "status": "PAYMENT_CAPTURED",
            }

        return {
            "received": True,
            "status": "PAYMENT_CAPTURED",
            "mandate_id": mandate_record.mandate_id,
            "receipt_id": str(receipt_id),
            "receipt_jwt": receipt_jwt,
        }

    # =========================================================================
    # Event: payment.failed
    # =========================================================================
    elif event_type == "payment.failed":
        payment_entity = event_data.get("payload", {}).get("payment", {}).get("entity", {})
        order_id = payment_entity.get("order_id")
        if order_id:
            mandate_record = db.query(MandateRecord).filter_by(razorpay_order_id=order_id).first()
            if mandate_record and mandate_record.status != MandateStatus.PAYMENT_CAPTURED:
                transition(mandate_record, MandateStatus.PAYMENT_FAILED, db)
                intent_reg = db.query(IntentRegistry).filter_by(intent_id=mandate_record.intent_id).first()
                if intent_reg:
                    # Release reservation back to available budget
                    intent_reg.reserved_paise = max(0, intent_reg.reserved_paise - mandate_record.reserved_paise)
                    mandate_record.reserved_paise = 0

                webhook_event = WebhookEvent(
                    razorpay_event_id=event_id,
                    event_type=event_type,
                    razorpay_order_id=order_id,
                    raw_payload=event_data,
                    status=WebhookEventStatus.PROCESSED,
                )
                db.add(webhook_event)
                append_entry(
                    db=db,
                    entry_type=LedgerEntryType.WEBHOOK_RECEIVED,
                    payload={"event_id": event_id, "event_type": event_type, "order_id": order_id},
                    actor="gateway:razorpay",
                )
                db.commit()

        return {"received": True, "status": "PAYMENT_FAILED", "event_id": event_id}

    # Other event types (no financial action required)
    else:
        webhook_event = WebhookEvent(
            razorpay_event_id=event_id,
            event_type=event_type,
            raw_payload=event_data,
            status=WebhookEventStatus.PROCESSED,
        )
        db.add(webhook_event)
        db.commit()
        return {"received": True, "event_type": event_type, "event_id": event_id}
