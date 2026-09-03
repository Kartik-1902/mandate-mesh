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
from uuid import UUID, uuid4
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
    PurchasePlan,
)
from app.merchant_keys import get_merchant_public_key
from app.schemas import MerchantSignedCart, PaymentMandate, UserIntentCredential


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
    is_postgres = False
    try:
        bind = db.get_bind()
        if bind and bind.dialect.name == "postgresql":
            is_postgres = True
    except Exception:
        pass

    intent = verify_intent(intent_jwt, user_public_key_pem, db)
    cart = verify_cart(cart_jwt, merchant_public_key_pem)
    now = datetime.now(timezone.utc)

    intent_id_str = str(intent.intent_id)
    query = db.query(IntentRegistry).filter_by(intent_id=intent_id_str)
    if is_postgres:
        query = query.with_for_update()

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

    # 3. Temporal Validity Check
    if now < intent.not_before:
        _reject_policy(PolicyViolation("POLICY_INTENT_NOT_YET_VALID", "Intent not yet valid."))
    if now > intent.expires_at:
        _reject_policy(PolicyIntentExpired("Intent has expired."))
    if now > cart.expires_at:
        _reject_policy(PolicyCartExpired("Cart quote has expired."))

    # 4. Transaction Limit Check
    if intent_row.transactions_consumed >= intent_row.max_transactions:
        _reject_policy(
            PolicyTransactionLimitReached(
                f"Intent '{intent_id_str}' has reached its maximum transaction limit of {intent_row.max_transactions}."
            )
        )

    # 5. Spend Cap Enforcement Check
    available = intent_row.available_paise
    if cart.total_paise > available:
        _reject_policy(
            PolicySpendCapExceeded(
                f"Requested Rs. {cart.total_paise / 100:.2f} exceeds available budget Rs. {available / 100:.2f}.",
                details={
                    "spend_cap_paise": intent_row.spend_cap_paise,
                    "reserved_paise": intent_row.reserved_paise,
                    "captured_paise": intent_row.captured_paise,
                    "available_paise": available,
                    "requested_paise": cart.total_paise,
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


def authorize_plan(
    intent_jwt: str,
    legs: list[dict[str, Any]] | list[Any] | Any,
    user_public_key_pem: bytes | str | Path,
    platform_private_key_pem: bytes | str | Path,
    db: Session,
    plan_id: UUID | str | None = None,
    platform_kid: str = "platform:key-1",
    merchant_public_keys: dict[str, bytes | str | Path] | None = None,
) -> tuple[PurchasePlan, list[PaymentMandate], list[MandateRecord]]:
    """Authoritative financial authorization boundary for a complete multi-leg PurchasePlan (Milestone M7 / ADR-012).

    CRITICAL TRANSACTION BOUNDARY & INVARIANTS:
    1. Single Atomic Transaction: All checks, row locking, mutations (PurchasePlan, MandateRecords,
       IntentRegistry reservations), and audit entries occur within a single database transaction,
       concluding with exactly one db.commit() or db.rollback().
    2. Concurrency Serialization: SELECT FOR UPDATE is acquired on the authoritative IntentRegistry row
       BEFORE validating remaining spend capacity, max transactions, or creating any child mandate.
    3. Spend Capacity Check: Ensures (reserved_paise + captured_paise + plan_total <= spend_cap_paise)
       under the row lock using authoritative signed quote totals, not caller estimates.
    4. Child Leg Validation: Every proposed leg is verified (merchant allowlist, category allowlist,
       temporal validity, dual-layer cart hash, cryptographic ES256 signature).
    5. Deterministic Leg Idempotency: Each leg is assigned exactly `tx_plan_{plan_id.hex}_leg_{merchant_id}`.
       Duplicate plan requests return the existing plan and child mandates idempotently.
    6. Max Transactions Accounting: The complete PurchasePlan increments `transactions_consumed` by 1.
    7. All-or-Nothing Guarantee: A failure in ANY leg aborts the entire plan with zero financial mutation.
    """
    from app.basket_planner import MixedBasketPlan

    # 1. Resolve effective_plan_id and raw_legs
    if isinstance(legs, MixedBasketPlan):
        effective_plan_id = UUID(str(plan_id)) if plan_id else legs.plan_id
        raw_legs = legs.legs
    elif isinstance(legs, (list, tuple)):
        effective_plan_id = UUID(str(plan_id)) if plan_id else uuid4()
        raw_legs = list(legs)
    else:
        raise PolicyViolation("POLICY_INVALID_PLAN_INPUT", "Plan legs must be a MixedBasketPlan or sequence of legs.")

    if len(raw_legs) == 0:
        raise PolicyViolation("POLICY_EMPTY_PLAN", "Purchase plan must contain at least one merchant leg.")

    # 2. Verify User Intent Credential
    intent = verify_intent(intent_jwt, user_public_key_pem, db)
    intent_id_str = str(intent.intent_id)

    # 3. Detect duplicate PurchasePlan request (Plan-level Idempotency)
    existing_plan = db.query(PurchasePlan).filter_by(plan_id=effective_plan_id).first()
    if existing_plan:
        if existing_plan.intent_id != intent_id_str:
            raise PolicyViolation(
                "POLICY_PLAN_INTENT_MISMATCH",
                f"Plan '{effective_plan_id}' already exists under intent '{existing_plan.intent_id}', not '{intent_id_str}'."
            )
        existing_mandate_records = (
            db.query(MandateRecord)
            .filter_by(plan_id=effective_plan_id)
            .order_by(MandateRecord.merchant_id.asc())
            .all()
        )
        existing_mandates: list[PaymentMandate] = []
        for rec in existing_mandate_records:
            existing_mandates.append(
                PaymentMandate(
                    mandate_id=UUID(rec.mandate_id),
                    intent_id=rec.intent_id,
                    intent_hash=compute_intent_hash(intent),
                    cart_hash=rec.cart_hash,
                    merchant_id=rec.merchant_id,
                    authorized_amount_paise=rec.authorized_amount_paise,
                    currency="INR",
                    created_at=rec.created_at,
                    plan_id=effective_plan_id,
                )
            )
        return existing_plan, existing_mandates, existing_mandate_records

    # 4. Acquire exclusive row lock on IntentRegistry
    is_postgres = False
    try:
        bind = db.get_bind()
        if bind and bind.dialect.name == "postgresql":
            is_postgres = True
    except Exception:
        pass

    query = db.query(IntentRegistry).filter_by(intent_id=intent_id_str)
    if is_postgres:
        query = query.with_for_update()

    intent_row = query.first()
    if not intent_row:
        raise PolicyViolation("POLICY_INTENT_NOT_FOUND", f"Intent {intent_id_str} not found in registry.")

    def _reject_plan_policy(error: PolicyViolation, merchant_id: str | None = None, requested_paise: int = 0) -> None:
        """Helper to record forensic plan failure in audit ledger and roll back transaction."""
        try:
            append_entry(
                db=db,
                entry_type=LedgerEntryType.POLICY_REJECTED,
                payload={
                    "plan_id": str(effective_plan_id),
                    "intent_id": intent_id_str,
                    "merchant_id": merchant_id or "aggregate_plan",
                    "requested_total_paise": requested_paise,
                    "error_code": error.code,
                    "message": error.message,
                },
                actor="system:policy-rail",
            )
            db.commit()
        except Exception:
            db.rollback()
        raise error

    now = datetime.now(timezone.utc)

    # 5. Intent Temporal & Status Validations
    if intent_row.status == IntentStatus.EXHAUSTED:
        _reject_plan_policy(
            PolicyTransactionLimitReached(
                f"Intent '{intent_id_str}' has exhausted its maximum of {intent_row.max_transactions} transactions."
            )
        )
    if intent_row.status == IntentStatus.EXPIRED or now > intent.expires_at:
        _reject_plan_policy(PolicyIntentExpired(f"Intent '{intent_id_str}' has expired."))
    if intent_row.status != IntentStatus.ACTIVE:
        _reject_plan_policy(
            PolicyViolation("POLICY_INTENT_INACTIVE", f"Intent '{intent_id_str}' is in inactive state: {intent_row.status}")
        )
    if now < intent.not_before:
        _reject_plan_policy(PolicyViolation("POLICY_INTENT_NOT_YET_VALID", "Intent is not yet valid."))

    # 6. Max Transactions Check (Plan counts as 1 atomic transaction against intent allowance)
    if intent_row.transactions_consumed >= intent_row.max_transactions:
        _reject_plan_policy(
            PolicyTransactionLimitReached(
                f"Intent '{intent_id_str}' has reached its maximum transaction limit of {intent_row.max_transactions}."
            )
        )

    # 7. Comprehensive Child Leg Validations (ALL legs validated before ANY mutation)
    verified_legs: list[dict[str, Any]] = []
    seen_merchants: set[str] = set()
    allowed_categories_set = set(intent.allowed_categories)

    for idx, leg in enumerate(raw_legs):
        if isinstance(leg, dict):
            cart_jwt = leg.get("cart_jwt")
            expected_mid = leg.get("merchant_id")
        elif hasattr(leg, "cart_jwt"):
            cart_jwt = leg.cart_jwt
            expected_mid = getattr(leg, "merchant_id", None)
        else:
            _reject_plan_policy(
                PolicyViolation("POLICY_INVALID_LEG_FORMAT", f"Leg at index {idx} has invalid format.")
            )

        if not cart_jwt:
            _reject_plan_policy(
                PolicyViolation("POLICY_MISSING_CART_JWT", f"Leg at index {idx} missing cart_jwt.")
            )

        # Resolve merchant public key
        pub_key = None
        if merchant_public_keys and expected_mid and expected_mid in merchant_public_keys:
            pub_key = merchant_public_keys[expected_mid]
        elif expected_mid:
            try:
                pub_key = get_merchant_public_key(expected_mid)
            except Exception as e:
                _reject_plan_policy(
                    PolicyViolation(
                        "POLICY_MERCHANT_KEY_NOT_FOUND",
                        f"Public key not found for merchant '{expected_mid}': {e}",
                    ),
                    merchant_id=expected_mid,
                )
        else:
            _reject_plan_policy(
                PolicyViolation("POLICY_MISSING_MERCHANT_ID", f"Leg at index {idx} missing merchant_id.")
            )

        # Cryptographic & Dual-Layer Verification of Signed Cart
        try:
            cart = verify_cart(cart_jwt, pub_key)
        except PolicyViolation as e:
            _reject_plan_policy(e, merchant_id=expected_mid)
        except Exception as e:
            _reject_plan_policy(
                PolicyViolation("POLICY_CART_VERIFICATION_FAILED", f"Cart signature verification failed: {e}"),
                merchant_id=expected_mid,
            )

        # Merchant identity verification
        if expected_mid and cart.merchant_id != expected_mid:
            _reject_plan_policy(
                PolicyViolation(
                    "POLICY_MERCHANT_MISMATCH",
                    f"Cart merchant '{cart.merchant_id}' does not match expected '{expected_mid}'.",
                ),
                merchant_id=expected_mid,
            )

        # Duplicate merchant in same plan verification
        if cart.merchant_id in seen_merchants:
            _reject_plan_policy(
                PolicyViolation(
                    "POLICY_DUPLICATE_MERCHANT_LEG",
                    f"Plan contains multiple legs for merchant '{cart.merchant_id}'. Each merchant must have at most one leg.",
                ),
                merchant_id=cart.merchant_id,
            )
        seen_merchants.add(cart.merchant_id)

        # Merchant allowlist check
        if cart.merchant_id not in intent.allowed_merchant_ids:
            _reject_plan_policy(
                PolicyMerchantNotAllowed(
                    f"Merchant '{cart.merchant_id}' is not in authorized merchants: {intent.allowed_merchant_ids}",
                    details={"merchant_id": cart.merchant_id, "allowed_merchants": intent.allowed_merchant_ids},
                ),
                merchant_id=cart.merchant_id,
                requested_paise=cart.total_paise,
            )

        # Cart temporal expiration check
        if now > cart.expires_at:
            _reject_plan_policy(
                PolicyCartExpired("Cart quote has expired."),
                merchant_id=cart.merchant_id,
                requested_paise=cart.total_paise,
            )

        # Category allowlist check across all line items in this leg
        for li in cart.line_items:
            if li.category not in allowed_categories_set:
                _reject_plan_policy(
                    PolicyCategoryNotAllowed(
                        f"Line item '{li.name}' category '{li.category}' is not in authorized categories: {intent.allowed_categories}",
                        details={"category": li.category, "allowed_categories": intent.allowed_categories},
                    ),
                    merchant_id=cart.merchant_id,
                    requested_paise=cart.total_paise,
                )

        # Deterministic unique idempotency key check per leg:
        # tx_plan_{plan_id.hex}_leg_{merchant_id}
        leg_idempotency_key = f"tx_plan_{effective_plan_id.hex}_leg_{cart.merchant_id}"
        existing_mandate = (
            db.query(MandateRecord)
            .filter_by(intent_id=intent_id_str, idempotency_key=leg_idempotency_key)
            .first()
        )
        if existing_mandate:
            _reject_plan_policy(
                PolicyReplayDetected(
                    f"Transaction replay detected: idempotency_key '{leg_idempotency_key}' already exists for intent '{intent_id_str}'."
                ),
                merchant_id=cart.merchant_id,
                requested_paise=cart.total_paise,
            )

        verified_legs.append({
            "cart": cart,
            "cart_jwt": cart_jwt,
            "idempotency_key": leg_idempotency_key,
        })

    # 8. Compute Authoritative Aggregate Plan Total & Validate Spend Capacity
    plan_total_paise = sum(vl["cart"].total_paise for vl in verified_legs)
    available_paise = intent_row.available_paise

    if plan_total_paise > available_paise:
        _reject_plan_policy(
            PolicySpendCapExceeded(
                f"Aggregate plan cost of Rs. {plan_total_paise / 100:.2f} exceeds available budget Rs. {available_paise / 100:.2f}.",
                details={
                    "spend_cap_paise": intent_row.spend_cap_paise,
                    "reserved_paise": intent_row.reserved_paise,
                    "captured_paise": intent_row.captured_paise,
                    "available_paise": available_paise,
                    "requested_paise": plan_total_paise,
                },
            ),
            requested_paise=plan_total_paise,
        )

    # 9. Atomic Multi-Leg Creation & Accounting Invariant Updates
    # A. Create PurchasePlan aggregate
    purchase_plan = PurchasePlan(
        plan_id=effective_plan_id,
        intent_id=intent_id_str,
        status="CONFIRMED",
        total_authorized_paise=plan_total_paise,
        created_at=now,
    )
    db.add(purchase_plan)

    # B. Create child MandateRecords & log ledger entries
    intent_hash = compute_intent_hash(intent)
    mandates: list[PaymentMandate] = []
    mandate_records: list[MandateRecord] = []

    for vl in verified_legs:
        cart = vl["cart"]
        cart_jwt = vl["cart_jwt"]
        leg_idempotency_key = vl["idempotency_key"]
        mandate_id = uuid4()

        mandate = PaymentMandate(
            mandate_id=mandate_id,
            intent_id=intent_id_str,
            intent_hash=intent_hash,
            cart_hash=cart.cart_hash,
            merchant_id=cart.merchant_id,
            authorized_amount_paise=cart.total_paise,
            currency=cart.currency,
            created_at=now,
            plan_id=effective_plan_id,
        )
        mandate_jwt = issue_mandate_jwt(mandate, platform_private_key_pem, kid=platform_kid)

        mandate_record = MandateRecord(
            mandate_id=str(mandate_id),
            intent_id=intent_id_str,
            plan_id=effective_plan_id,
            idempotency_key=leg_idempotency_key,
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
        mandates.append(mandate)
        mandate_records.append(mandate_record)

        append_entry(
            db=db,
            entry_type=LedgerEntryType.MANDATE_CREATED,
            payload={
                "mandate_id": str(mandate_id),
                "plan_id": str(effective_plan_id),
                "intent_id": intent_id_str,
                "merchant_id": cart.merchant_id,
                "authorized_amount_paise": cart.total_paise,
                "intent_hash": intent_hash,
                "cart_hash": cart.cart_hash,
            },
            actor="system:policy-rail",
        )

    # C. Update IntentRegistry aggregate reservation & transaction count
    intent_row.reserved_paise += plan_total_paise
    intent_row.transactions_consumed += 1
    if intent_row.transactions_consumed >= intent_row.max_transactions:
        intent_row.status = IntentStatus.EXHAUSTED

    # D. Commit transaction exactly once
    db.commit()
    return purchase_plan, mandates, mandate_records
