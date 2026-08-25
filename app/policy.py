"""Deterministic policy rail and authorization engine.

Enforces:
- Cryptographic verification of UserIntentCredential and MerchantSignedCart.
- Invariant bounds checking: spend cap, categories, merchants, TTL, max transactions.
- Atomic spend reservation with `IntentRegistry` under `SELECT ... FOR UPDATE`.
- Single atomic transaction for reservation, mandate issuance, and ledger entry.

NOTE: Per Section 0: The LLM proposes; deterministic Python disposes.
An unauthorized rupee can never move because of an LLM decision.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.crypto import (
    compute_intent_hash,
    issue_mandate_jwt,
    verify_cart_jwt,
    verify_intent_jwt,
)
from app.errors import (
    PolicyCartExpired,
    PolicyCategoryNotAllowed,
    PolicyIntentExpired,
    PolicyMerchantNotAllowed,
    PolicyReplayDetected,
    PolicySpendCapExceeded,
    PolicyTransactionLimitReached,
    PolicyViolation,
)
from app.ledger import append_entry
from app.models import (
    IntentRegistry,
    IntentStatus,
    LedgerEntryType,
    MandateRecord,
    MandateStatus,
)
from app.schemas import MerchantSignedCart, PaymentMandate, UserIntentCredential


import threading

_LOCAL_POLICY_LOCK = threading.Lock()


def verify_intent(
    intent_jwt: str,
    user_public_key_pem: bytes | str | Path,
    db: Session,
) -> UserIntentCredential:
    """Verifies user intent cryptographic validity and ensures registration in IntentRegistry.

    If the intent does not exist in IntentRegistry, it is inserted as ACTIVE.
    The unique constraint on `nonce` guarantees that the intent credential was freshly minted.
    If the intent exists and is ACTIVE, it is re-used (supporting max_transactions > 1).
    """
    intent = verify_intent_jwt(intent_jwt, user_public_key_pem)
    intent_id_str = str(intent.intent_id)

    existing = (
        db.query(IntentRegistry)
        .filter_by(intent_id=intent_id_str)
        .first()
    )

    if not existing:
        try:
            new_reg = IntentRegistry(
                intent_id=intent_id_str,
                user_id=intent.user_id,
                nonce=intent.nonce,
                spend_cap_paise=intent.spend_cap_paise,
                reserved_paise=0,
                captured_paise=0,
                max_transactions=intent.max_transactions,
                transactions_consumed=0,
                status=IntentStatus.ACTIVE,
                expires_at=intent.expires_at,
            )
            db.add(new_reg)
            append_entry(
                db=db,
                entry_type=LedgerEntryType.INTENT_ISSUED,
                payload={
                    "intent_id": intent_id_str,
                    "user_id": intent.user_id,
                    "spend_cap_paise": intent.spend_cap_paise,
                    "max_transactions": intent.max_transactions,
                    "expires_at": intent.expires_at.isoformat(),
                },
                actor=f"user:{intent.user_id}",
            )
            db.flush()
        except IntegrityError as e:
            db.rollback()
            raise PolicyReplayDetected(
                f"Intent registration rejected: nonce '{intent.nonce}' has already been used."
            ) from e
    else:
        if existing.status == IntentStatus.EXHAUSTED:
            raise PolicyTransactionLimitReached(
                f"Intent '{intent_id_str}' has exhausted its maximum of {existing.max_transactions} transactions."
            )
        elif existing.status == IntentStatus.EXPIRED:
            raise PolicyIntentExpired(f"Intent '{intent_id_str}' has expired.")
        elif existing.status != IntentStatus.ACTIVE:
            raise PolicyViolation("POLICY_INTENT_INACTIVE", f"Intent '{intent_id_str}' is in inactive state: {existing.status}")

    return intent


def verify_cart(
    cart_jwt: str,
    merchant_public_key_pem: bytes | str | Path,
) -> MerchantSignedCart:
    """Verifies merchant signature, expiration, and matching cart_hash."""
    return verify_cart_jwt(cart_jwt, merchant_public_key_pem)


def authorize_mandate(
    intent_jwt: str,
    cart_jwt: str,
    idempotency_key: str,
    user_public_key_pem: bytes | str | Path,
    merchant_public_key_pem: bytes | str | Path,
    platform_private_key_pem: bytes | str | Path,
    db: Session,
    platform_kid: str = "platform:key-1",
) -> tuple[PaymentMandate, str, MandateRecord]:
    """Evaluates the deterministic policy bounds engine and atomically reserves spend cap.

    Checks:
    1. ES256 signatures & dual-layer cart_hash match.
    2. Category allowlist against line items.
    3. Merchant allowlist against cart merchant_id.
    4. Time validity (nbf/exp).
    5. Available spend budget under row lock.
    6. Transaction count limit.
    7. Transaction replay identity (intent_id, idempotency_key).

    On success: Atomically reserves budget in IntentRegistry, issues signed PaymentMandate,
                creates MandateRecord (status: RESERVED), and logs to audit ledger.
    On failure: Logs POLICY_REJECTED to audit ledger and fails closed with zero financial mutation.
    """
    intent = verify_intent(intent_jwt, user_public_key_pem, db)
    cart = verify_cart(cart_jwt, merchant_public_key_pem)
    now = datetime.now(timezone.utc)

    intent_id_str = str(intent.intent_id)

    is_postgres = False
    query = db.query(IntentRegistry).filter_by(intent_id=intent_id_str)
    try:
        bind = db.get_bind()
        if bind and bind.dialect.name == "postgresql":
            is_postgres = True
            query = query.with_for_update()
    except Exception:
        pass

    if not is_postgres:
        _LOCAL_POLICY_LOCK.acquire()

    try:
        intent_row = query.first()
        if not intent_row:
            raise PolicyViolation("POLICY_INTENT_NOT_FOUND", f"Intent {intent_id_str} not found in registry.")

        def _reject_policy(error: PolicyViolation) -> None:
            """Helper to record forensic failure in audit ledger before raising."""
            try:
                append_entry(
                    db=db,
                    entry_type=LedgerEntryType.POLICY_REJECTED,
                    payload={
                        "intent_id": intent_id_str,
                        "merchant_id": cart.merchant_id,
                        "requested_total_paise": cart.total_paise,
                        "error_code": error.code,
                        "message": error.message,
                    },
                    actor="system:policy-rail",
                )
                db.commit()
            except Exception:
                db.rollback()
            raise error

        # 1. Category Allowlist Check
        allowed_categories_set = set(intent.allowed_categories)
        for li in cart.line_items:
            if li.category not in allowed_categories_set:
                _reject_policy(
                    PolicyCategoryNotAllowed(
                        f"Line item '{li.name}' category '{li.category}' is not in authorized categories: {intent.allowed_categories}",
                        details={"category": li.category, "allowed_categories": intent.allowed_categories},
                    )
                )

        # 2. Merchant Allowlist Check
        if cart.merchant_id not in intent.allowed_merchant_ids:
            _reject_policy(
                PolicyMerchantNotAllowed(
                    f"Merchant '{cart.merchant_id}' is not in authorized merchants: {intent.allowed_merchant_ids}",
                    details={"merchant_id": cart.merchant_id, "allowed_merchants": intent.allowed_merchant_ids},
                )
            )

        # 3. Time Window Expiration Check
        if now > intent.expires_at:
            _reject_policy(PolicyIntentExpired(f"User intent expired at {intent.expires_at.isoformat()}."))

        if now > cart.expires_at:
            _reject_policy(PolicyCartExpired(f"Merchant cart quote expired at {cart.expires_at.isoformat()}."))

        # 4. Transaction Count Limit Check
        if intent_row.transactions_consumed >= intent_row.max_transactions:
            _reject_policy(
                PolicyTransactionLimitReached(
                    f"Intent transaction limit reached ({intent_row.transactions_consumed}/{intent_row.max_transactions}).",
                    details={"transactions_consumed": intent_row.transactions_consumed, "max_transactions": intent_row.max_transactions},
                )
            )

        # 5. Available Spend Cap Check
        available_budget = intent_row.available_paise
        if cart.total_paise > available_budget:
            _reject_policy(
                PolicySpendCapExceeded(
                    f"Cart total ₹{cart.total_paise / 100:.2f} exceeds available budget of ₹{available_budget / 100:.2f}.",
                    details={
                        "requested_paise": cart.total_paise,
                        "available_paise": available_budget,
                        "spend_cap_paise": intent_row.spend_cap_paise,
                        "reserved_paise": intent_row.reserved_paise,
                        "captured_paise": intent_row.captured_paise,
                    },
                )
            )

        # 6. Replay Check on (intent_id, idempotency_key)
        existing_mandate = (
            db.query(MandateRecord)
            .filter_by(intent_id=intent_id_str, idempotency_key=idempotency_key)
            .first()
        )
        if existing_mandate:
            _reject_policy(
                PolicyReplayDetected(
                    f"Transaction replay detected: idempotency_key '{idempotency_key}' already exists for intent '{intent_id_str}'."
                )
            )

        # =========================================================================
        # Atomic Spend Reservation & Mandate Issuance
        # =========================================================================
        mandate_id = uuid4()
        intent_hash = compute_intent_hash(intent)

        # Increment reservations
        intent_row.reserved_paise += cart.total_paise
        intent_row.transactions_consumed += 1
        if intent_row.transactions_consumed >= intent_row.max_transactions:
            intent_row.status = IntentStatus.EXHAUSTED

        # Construct immutable PaymentMandate snapshot
        mandate = PaymentMandate(
            mandate_id=mandate_id,
            intent_id=intent_id_str,
            intent_hash=intent_hash,
            cart_hash=cart.cart_hash,
            merchant_id=cart.merchant_id,
            authorized_amount_paise=cart.total_paise,
            currency=cart.currency,
            created_at=now,
        )

        # Sign platform mandate JWT
        mandate_jwt = issue_mandate_jwt(mandate, platform_private_key_pem, kid=platform_kid)

        # Persist runtime mutable MandateRecord
        mandate_record = MandateRecord(
            mandate_id=str(mandate_id),
            intent_id=intent_id_str,
            idempotency_key=idempotency_key,
            merchant_id=cart.merchant_id,
            cart_hash=cart.cart_hash,
            authorized_amount_paise=cart.total_paise,
            reserved_paise=cart.total_paise,
            captured_paise=0,
            status=MandateStatus.RESERVED,
            order_idempotency_key=f"mm_{mandate_id.hex}",
            razorpay_order_id=None,
            razorpay_payment_id=None,
            mandate_jwt=mandate_jwt,
            created_at=now,
        )
        db.add(mandate_record)

        # Log successful authorization to audit ledger
        append_entry(
            db=db,
            entry_type=LedgerEntryType.MANDATE_CREATED,
            payload={
                "mandate_id": str(mandate_id),
                "intent_id": intent_id_str,
                "merchant_id": cart.merchant_id,
                "authorized_amount_paise": cart.total_paise,
                "intent_hash": intent_hash,
                "cart_hash": cart.cart_hash,
            },
            actor="system:policy-rail",
        )

        db.commit()
        return mandate, mandate_jwt, mandate_record
    finally:
        if not is_postgres:
            _LOCAL_POLICY_LOCK.release()
