"""Milestone M8: Mixed-Merchant HITL, JIT Revalidation, and Partial-Failure Engine (ADR-013).

This module coordinates:
1. Pre-execution JIT revalidation of merchant stock and cart quote TTLs.
2. Deterministic re-quotation upon quote expiry while awaiting HITL approval, strictly
   reconstructing the originally authorized basket (never substituting other products).
3. Full policy validation of fresh quotes (category allowlist, merchant allowlist, signatures, hashes, amounts).
4. Independent per-leg execution and rejection under the M3 Mandate FSM.
5. Strict non-reversibility of already-captured payments (never roll back captured payments).
6. Independent failed-leg reservation release without mutating captured funds.
7. Aggregate PurchasePlan status synchronization (including PARTIAL_COMPLETE).
8. Explicit, deterministic execution and failure reporting without LLM involvement.
   - successful_legs: PAYMENT_CAPTURED only
   - pending_legs: ORDER_CREATED, PAYMENT_PENDING, IN_PROGRESS
   - failed_legs: RELEASED, PAYMENT_FAILED, EXPIRED
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import jwt
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.crypto import extract_mandate_intent_hash
from app.errors import (
    PolicyCartExpired,
    PolicyMerchantNotAllowed,
    PolicySpendCapExceeded,
    PolicyViolation,
)
from app.ledger import append_entry
from app.mandate_fsm import transition
from app.merchant import sign_cart
from app.merchant_keys import get_merchant_public_key
from app.models import (
    AuditLedgerEntry,
    CatalogItem,
    IntentRegistry,
    IntentStatus,
    LedgerEntryType,
    MandateRecord,
    MandateStatus,
    PurchasePlan,
)
from app.policy import verify_cart
from app.razorpay_client import RazorpayClient
from app.schemas import MerchantSignedCart, UserIntentCredential


class PlanExecutionStatus(str, Enum):
    """Aggregate lifecycle states for a multi-merchant PurchasePlan."""

    CONFIRMED = "CONFIRMED"          # Authorized, awaiting execution/approval
    IN_PROGRESS = "IN_PROGRESS"      # Orders created/pending at gateways
    PARTIAL_COMPLETE = "PARTIAL_COMPLETE"  # >= 1 leg captured AND >= 1 leg failed/pending
    COMPLETE = "COMPLETE"            # 100% of legs captured successfully
    FAILED = "FAILED"                # 100% of legs failed/released or rejected
    CANCELLED = "CANCELLED"          # Explicitly aborted before capture


class LegExecutionStatus(str, Enum):
    """Execution status for an individual merchant leg."""

    PENDING = "PENDING"
    ORDER_CREATED = "ORDER_CREATED"
    CAPTURED = "CAPTURED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    RELEASED = "RELEASED"
    REQUIRES_REAUTH = "REQUIRES_REAUTH"


class LegExecutionResult(BaseModel):
    """Authoritative outcome report for one merchant execution leg."""

    mandate_id: str
    merchant_id: str
    status: LegExecutionStatus
    authorized_amount_paise: int
    captured_amount_paise: int = 0
    released_reservation_paise: int = 0
    razorpay_order_id: str | None = None
    razorpay_payment_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class PlanExecutionReport(BaseModel):
    """Deterministic, aggregate post-execution report for a PurchasePlan."""

    plan_id: UUID
    intent_id: str
    status: PlanExecutionStatus
    total_authorized_paise: int
    total_captured_paise: int
    total_released_paise: int
    successful_legs: list[LegExecutionResult] = Field(default_factory=list)
    failed_legs: list[LegExecutionResult] = Field(default_factory=list)
    pending_legs: list[LegExecutionResult] = Field(default_factory=list)
    rejection_reason: str | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def sync_purchase_plan_status(plan: PurchasePlan, db: Session | None = None) -> PlanExecutionStatus:
    """Computes and updates the authoritative aggregate status of a PurchasePlan.

    STATUS DERIVATION RULES:
    - COMPLETE: 100% of child mandates are PAYMENT_CAPTURED.
    - PARTIAL_COMPLETE: At least one mandate is PAYMENT_CAPTURED, and at least one
      other required leg is failed, released, expired, or pending.
    - FAILED: 100% of child mandates have reached a terminal unsuccessful state (RELEASED, PAYMENT_FAILED, EXPIRED).
    - IN_PROGRESS: At least one mandate is actively in flight (ORDER_CREATING, ORDER_CREATED, PAYMENT_PENDING)
      and none are captured yet.
    - CONFIRMED: All mandates remain in RESERVED state awaiting fulfillment.
    """
    mandates = plan.mandates
    if not mandates:
        return PlanExecutionStatus(plan.status)

    total_count = len(mandates)
    captured_count = sum(1 for m in mandates if m.status == MandateStatus.PAYMENT_CAPTURED)
    failed_count = sum(
        1 for m in mandates
        if m.status in (MandateStatus.RELEASED, MandateStatus.PAYMENT_FAILED, MandateStatus.EXPIRED)
    )

    if captured_count == total_count:
        new_status = PlanExecutionStatus.COMPLETE
    elif captured_count > 0:
        new_status = PlanExecutionStatus.PARTIAL_COMPLETE
    elif failed_count == total_count:
        new_status = PlanExecutionStatus.FAILED
    elif any(m.status in (MandateStatus.ORDER_CREATING, MandateStatus.ORDER_CREATED, MandateStatus.PAYMENT_PENDING) for m in mandates):
        new_status = PlanExecutionStatus.IN_PROGRESS
    else:
        new_status = PlanExecutionStatus.CONFIRMED

    plan.status = new_status.value
    if db is not None:
        db.flush()

    return new_status


def _extract_original_mandate_items(
    mandate_record: MandateRecord,
    cart_jwt: str | None,
    db: Session,
) -> list[dict[str, Any]]:
    """Extracts the exact originally authorized items for this mandate."""
    # 1. From cart_jwt if provided
    if cart_jwt:
        try:
            claims = jwt.decode(cart_jwt, options={"verify_signature": False})
            items = claims.get("line_items") or claims.get("items") or []
            if items:
                return items
        except Exception:
            pass

    # 2. From MANDATE_CREATED audit ledger entry
    entries = (
        db.query(AuditLedgerEntry)
        .filter_by(entry_type=LedgerEntryType.MANDATE_CREATED)
        .all()
    )
    for entry in entries:
        payload = entry.payload or {}
        if payload.get("mandate_id") == mandate_record.mandate_id:
            items = payload.get("line_items") or payload.get("items") or []
            if items:
                return items

    return []


def revalidate_or_requote_leg(
    mandate_record: MandateRecord,
    db: Session,
    cart_jwt: str | None = None,
    merchant_private_key_pem: bytes | str | Path | None = None,
    merchant_public_key_pem: bytes | str | Path | None = None,
    allowed_categories: list[str] | None = None,
    allowed_merchant_ids: list[str] | None = None,
    quote_ttl_seconds: int = 300,
) -> tuple[bool, MerchantSignedCart | None, str | None, str | None]:
    """Performs deterministic JIT revalidation and exact basket re-quotation.

    CRITICAL INVARIANTS:
    1. Re-quotation MUST reconstruct the EXACT originally authorized basket for this mandate.
       Never substitute another SKU merely because it is in stock.
    2. If the original SKU is unavailable, fail closed and release the leg.
    3. Full policy validation is performed on the fresh quote (category allowlist,
       merchant allowlist, signature, dual-layer hash, price cap).
    """
    now = datetime.now(timezone.utc)

    # Automatically derive merchant_public_key_pem if private key was supplied
    if not merchant_public_key_pem and merchant_private_key_pem:
        try:
            from cryptography.hazmat.primitives import serialization
            priv_bytes = merchant_private_key_pem if isinstance(merchant_private_key_pem, bytes) else str(merchant_private_key_pem).encode()
            priv = serialization.load_pem_private_key(priv_bytes, password=None)
            merchant_public_key_pem = priv.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        except Exception:
            pass

    # 1. Extract exact originally authorized items
    original_items = _extract_original_mandate_items(mandate_record, cart_jwt, db)

    # 2. Check availability of the EXACT originally authorized SKUs
    if original_items:
        for it in original_items:
            sku = it.get("sku")
            catalog_item = (
                db.query(CatalogItem)
                .filter_by(merchant_id=mandate_record.merchant_id, sku=sku)
                .first()
            )
            if not catalog_item or not catalog_item.in_stock:
                return (
                    False,
                    None,
                    None,
                    f"Originally authorized SKU '{sku}' is out of stock or unavailable from merchant '{mandate_record.merchant_id}'.",
                )

    # 3. Check if current quote is still unexpired
    is_expired = False
    if cart_jwt:
        pub_key = merchant_public_key_pem or get_merchant_public_key(mandate_record.merchant_id)
        try:
            cart = verify_cart(cart_jwt, pub_key)
            elapsed = (now - mandate_record.created_at).total_seconds()
            if now > cart.expires_at or elapsed > quote_ttl_seconds:
                is_expired = True
            else:
                # Revalidate policy constraints even for unexpired quote
                if allowed_merchant_ids is not None and cart.merchant_id not in allowed_merchant_ids:
                    return False, None, None, f"Quote merchant '{cart.merchant_id}' is not in allowed merchants."
                if allowed_categories is not None:
                    allowed_cat_set = set(allowed_categories)
                    for item in cart.line_items:
                        if item.category not in allowed_cat_set:
                            return False, None, None, f"Quote item '{item.sku}' category '{item.category}' violates allowed categories {allowed_categories}."
                return True, cart, cart_jwt, None
        except Exception:
            is_expired = True
    else:
        elapsed = (now - mandate_record.created_at).total_seconds()
        if elapsed > quote_ttl_seconds:
            is_expired = True
        else:
            return True, None, None, None

    if not is_expired:
        return True, None, None, None

    # 4. Deterministic Re-Quotation of EXACT Originally Authorized Basket
    if not original_items:
        # If original items cannot be reconstructed, cannot safely re-quote
        return False, None, None, f"Original line items for mandate '{mandate_record.mandate_id}' could not be reconstructed."

    line_items_req = [
        {"sku": it["sku"], "quantity": it.get("quantity", 1)}
        for it in original_items
    ]

    try:
        fresh_cart, fresh_jwt = sign_cart(
            merchant_id=mandate_record.merchant_id,
            line_items_req=line_items_req,
            merchant_private_key_pem=merchant_private_key_pem,
            db=db,
        )
    except Exception as e:
        return False, None, None, f"Re-quotation failed for merchant '{mandate_record.merchant_id}': {e}"

    # 5. Full Policy Validation on the Fresh Quote
    # A. Cryptographic Signature & Hash Verification
    pub_key = merchant_public_key_pem or get_merchant_public_key(mandate_record.merchant_id)
    try:
        verified_fresh_cart = verify_cart(fresh_jwt, pub_key)
    except Exception as e:
        return False, None, None, f"Fresh quote failed cryptographic verification: {e}"

    # B. Merchant Identity & Allowlist Verification
    if verified_fresh_cart.merchant_id != mandate_record.merchant_id:
        return False, None, None, "Fresh quote merchant_id does not match authorized mandate merchant."
    if allowed_merchant_ids is not None and verified_fresh_cart.merchant_id not in allowed_merchant_ids:
        return False, None, None, f"Fresh quote merchant '{verified_fresh_cart.merchant_id}' is not in allowed merchants."

    # C. Category Allowlist Verification
    if allowed_categories is not None:
        allowed_cat_set = set(allowed_categories)
        for item in verified_fresh_cart.line_items:
            if item.category not in allowed_cat_set:
                return (
                    False,
                    None,
                    None,
                    f"Fresh quote item '{item.sku}' category '{item.category}' violates allowed categories {allowed_categories}.",
                )

    # D. Price Cap / Authorized Amount Verification
    if verified_fresh_cart.total_paise != mandate_record.authorized_amount_paise:
        if verified_fresh_cart.total_paise > mandate_record.authorized_amount_paise:
            overspend = verified_fresh_cart.total_paise - mandate_record.authorized_amount_paise
            return (
                False,
                verified_fresh_cart,
                fresh_jwt,
                f"Re-quoted price Rs. {verified_fresh_cart.total_paise / 100:.2f} exceeds authorized "
                f"Rs. {mandate_record.authorized_amount_paise / 100:.2f} by Rs. {overspend / 100:.2f}. "
                f"User re-authorization required.",
            )
        else:
            underspend = mandate_record.authorized_amount_paise - verified_fresh_cart.total_paise
            return (
                False,
                verified_fresh_cart,
                fresh_jwt,
                f"Re-quoted price Rs. {verified_fresh_cart.total_paise / 100:.2f} differs from authorized "
                f"Rs. {mandate_record.authorized_amount_paise / 100:.2f} (lower by Rs. {underspend / 100:.2f}). "
                f"User re-authorization required.",
            )

    return True, verified_fresh_cart, fresh_jwt, None


def execute_plan_leg(
    mandate_record: MandateRecord,
    db: Session,
    rzp_client: RazorpayClient | None = None,
    cart_jwt: str | None = None,
    merchant_private_key_pem: bytes | str | Path | None = None,
    merchant_public_key_pem: bytes | str | Path | None = None,
    allowed_categories: list[str] | None = None,
    allowed_merchant_ids: list[str] | None = None,
    quote_ttl_seconds: int = 300,
) -> LegExecutionResult:
    """Executes a single merchant mandate leg independently with per-mandate row locking.

    EXECUTION INVARIANTS:
    1. Acquires exclusive row lock on MandateRecord under PostgreSQL to serialize execution.
    2. Re-checks status after lock: already created/captured/released legs are idempotent no-ops.
    3. Revalidates intent status and TTL.
    4. Revalidates exact original basket and quote TTL (triggering JIT re-quotation if expired).
    5. Fails closed on quote price increase, stock exhaustion, or policy violation.
    6. Transitions mandate state through M3 FSM: RESERVED -> ORDER_CREATING -> ORDER_CREATED.
    7. Creates Razorpay order deterministically using mandate order_idempotency_key.
    8. Does NOT capture payment here (capture occurs via webhook or explicit capture call).
    """
    rzp = rzp_client or RazorpayClient(mock_mode=True)

    # 1. Acquire exclusive row lock on MandateRecord under PostgreSQL
    is_postgres = False
    try:
        bind = db.get_bind()
        if bind and bind.dialect.name == "postgresql":
            is_postgres = True
    except Exception:
        pass

    query = db.query(MandateRecord).filter_by(mandate_id=mandate_record.mandate_id)
    if is_postgres:
        query = query.with_for_update()

    record = query.first()
    if not record:
        raise PolicyViolation("MANDATE_NOT_FOUND", f"Mandate '{mandate_record.mandate_id}' not found.")

    # 2. Re-check state under lock (concurrency / idempotency check)
    if record.status in (MandateStatus.ORDER_CREATED, MandateStatus.PAYMENT_PENDING):
        return LegExecutionResult(
            mandate_id=record.mandate_id,
            merchant_id=record.merchant_id,
            status=LegExecutionStatus.ORDER_CREATED,
            authorized_amount_paise=record.authorized_amount_paise,
            captured_amount_paise=record.captured_paise,
            razorpay_order_id=record.razorpay_order_id,
        )
    if record.status == MandateStatus.PAYMENT_CAPTURED:
        return LegExecutionResult(
            mandate_id=record.mandate_id,
            merchant_id=record.merchant_id,
            status=LegExecutionStatus.CAPTURED,
            authorized_amount_paise=record.authorized_amount_paise,
            captured_amount_paise=record.captured_paise,
            razorpay_order_id=record.razorpay_order_id,
            razorpay_payment_id=record.razorpay_payment_id,
        )
    if record.status in (MandateStatus.RELEASED, MandateStatus.PAYMENT_FAILED, MandateStatus.EXPIRED):
        return LegExecutionResult(
            mandate_id=record.mandate_id,
            merchant_id=record.merchant_id,
            status=LegExecutionStatus.RELEASED,
            authorized_amount_paise=record.authorized_amount_paise,
            captured_amount_paise=0,
            released_reservation_paise=max(0, record.authorized_amount_paise - record.captured_paise),
            error_code="LEG_ALREADY_RELEASED",
            error_message="Mandate has already been released or failed.",
        )

    # 3. Revalidate parent intent
    now = datetime.now(timezone.utc)
    intent_reg = db.query(IntentRegistry).filter_by(intent_id=record.intent_id).first()
    intent_expired = False
    if intent_reg and intent_reg.expires_at:
        exp = intent_reg.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if now >= exp:
            intent_expired = True

    if not intent_reg or intent_reg.status == IntentStatus.EXPIRED or intent_expired:
        return release_failed_leg(
            mandate_record=record,
            db=db,
            reason="User intent has expired or is invalid.",
            error_code="POLICY_INTENT_EXPIRED",
        )

    # 4. JIT Revalidation & Exact Basket Re-Quotation
    is_valid, fresh_cart, fresh_jwt, error_msg = revalidate_or_requote_leg(
        mandate_record=record,
        db=db,
        cart_jwt=cart_jwt,
        merchant_private_key_pem=merchant_private_key_pem,
        merchant_public_key_pem=merchant_public_key_pem,
        allowed_categories=allowed_categories,
        allowed_merchant_ids=allowed_merchant_ids,
        quote_ttl_seconds=quote_ttl_seconds,
    )
    if not is_valid:
        if "re-authorization required" in (error_msg or "").lower():
            err_code = (
                "PRICE_DECREASE_REQUIRES_REAUTH"
                if (fresh_cart and fresh_cart.total_paise < record.authorized_amount_paise)
                else "PRICE_INCREASE_REQUIRES_REAUTH"
            )
            return LegExecutionResult(
                mandate_id=record.mandate_id,
                merchant_id=record.merchant_id,
                status=LegExecutionStatus.REQUIRES_REAUTH,
                authorized_amount_paise=record.authorized_amount_paise,
                error_code=err_code,
                error_message=error_msg,
            )
        err_code = "POLICY_VIOLATION" if "violates" in (error_msg or "").lower() else "MERCHANT_UNAVAILABLE"
        return release_failed_leg(
            mandate_record=record,
            db=db,
            reason=error_msg or "JIT revalidation failed.",
            error_code=err_code,
        )

    # If fresh cart was re-quoted within authorized amount, update cart_hash
    if fresh_cart:
        record.cart_hash = fresh_cart.cart_hash

    # 5. FSM Transition: RESERVED -> ORDER_CREATING
    transition(record, MandateStatus.ORDER_CREATING, db)

    try:
        # 6. Create Razorpay order deterministically
        rzp_order = rzp.create_order(
            amount_paise=record.authorized_amount_paise,
            currency="INR",
            receipt=record.order_idempotency_key,
        )
        record.razorpay_order_id = rzp_order["id"]

        # 7. FSM Transition: ORDER_CREATING -> ORDER_CREATED
        transition(record, MandateStatus.ORDER_CREATED, db)

        # Append to audit ledger
        append_entry(
            db=db,
            entry_type=LedgerEntryType.ORDER_CREATED,
            payload={
                "mandate_id": record.mandate_id,
                "merchant_id": record.merchant_id,
                "order_id": rzp_order["id"],
                "amount_paise": record.authorized_amount_paise,
            },
            actor="system:order-service",
        )
        db.commit()

        return LegExecutionResult(
            mandate_id=record.mandate_id,
            merchant_id=record.merchant_id,
            status=LegExecutionStatus.ORDER_CREATED,
            authorized_amount_paise=record.authorized_amount_paise,
            captured_amount_paise=0,
            razorpay_order_id=rzp_order["id"],
        )

    except Exception as e:
        db.rollback()
        return release_failed_leg(
            mandate_record=record,
            db=db,
            reason=f"Gateway order creation failed: {e}",
            error_code="GATEWAY_ORDER_CREATION_FAILED",
        )


def release_failed_leg(
    mandate_record: MandateRecord,
    db: Session,
    reason: str,
    error_code: str = "LEG_EXECUTION_FAILED",
) -> LegExecutionResult:
    """Releases reservation for an individual failed or rejected leg.

    SAFETY INVARIANTS:
    - NEVER touches or releases captured payments (captured_paise remains untouched).
    - Releases ONLY this mandate's reserved_paise back to IntentRegistry.
    - Transitions mandate through M3 FSM: -> RELEASED.
    """
    if mandate_record.status == MandateStatus.PAYMENT_CAPTURED:
        return LegExecutionResult(
            mandate_id=mandate_record.mandate_id,
            merchant_id=mandate_record.merchant_id,
            status=LegExecutionStatus.CAPTURED,
            authorized_amount_paise=mandate_record.authorized_amount_paise,
            captured_amount_paise=mandate_record.captured_paise,
            razorpay_order_id=mandate_record.razorpay_order_id,
            razorpay_payment_id=mandate_record.razorpay_payment_id,
        )

    if mandate_record.status == MandateStatus.RELEASED:
        return LegExecutionResult(
            mandate_id=mandate_record.mandate_id,
            merchant_id=mandate_record.merchant_id,
            status=LegExecutionStatus.RELEASED,
            authorized_amount_paise=mandate_record.authorized_amount_paise,
            captured_amount_paise=0,
            released_reservation_paise=0,
            error_code="LEG_ALREADY_RELEASED",
            error_message="Mandate has already been released.",
        )

    is_postgres = False
    try:
        bind = db.get_bind()
        if bind and bind.dialect.name == "postgresql":
            is_postgres = True
    except Exception:
        pass

    # Acquire FOR UPDATE on IntentRegistry before changing reserved_paise
    intent_query = db.query(IntentRegistry).filter_by(intent_id=mandate_record.intent_id)
    if is_postgres:
        intent_query = intent_query.with_for_update()
    intent_reg = intent_query.first()

    released_amount = mandate_record.reserved_paise

    if mandate_record.status == MandateStatus.RESERVED:
        transition(mandate_record, MandateStatus.ORDER_CREATING, db)
        transition(mandate_record, MandateStatus.RELEASED, db)
    elif mandate_record.status in (MandateStatus.ORDER_CREATED, MandateStatus.PAYMENT_PENDING):
        transition(mandate_record, MandateStatus.PAYMENT_FAILED, db)
        transition(mandate_record, MandateStatus.RELEASED, db)
    elif mandate_record.status == MandateStatus.ORDER_CREATING:
        transition(mandate_record, MandateStatus.RELEASED, db)

    if intent_reg and released_amount > 0:
        intent_reg.reserved_paise = max(0, intent_reg.reserved_paise - released_amount)

    mandate_record.reserved_paise = 0

    if mandate_record.plan:
        sync_purchase_plan_status(mandate_record.plan, db)

    append_entry(
        db=db,
        entry_type=LedgerEntryType.POLICY_REJECTED,
        payload={
            "mandate_id": mandate_record.mandate_id,
            "plan_id": str(mandate_record.plan_id) if mandate_record.plan_id else None,
            "merchant_id": mandate_record.merchant_id,
            "released_amount_paise": released_amount,
            "reason": reason,
            "error_code": error_code,
        },
        actor="system:hitl-coordinator",
    )
    db.commit()

    return LegExecutionResult(
        mandate_id=mandate_record.mandate_id,
        merchant_id=mandate_record.merchant_id,
        status=LegExecutionStatus.RELEASED,
        authorized_amount_paise=mandate_record.authorized_amount_paise,
        captured_amount_paise=0,
        released_reservation_paise=released_amount,
        error_code=error_code,
        error_message=reason,
    )


def execute_purchase_plan(
    plan: PurchasePlan,
    db: Session,
    approved_merchant_ids: list[str] | None = None,
    rzp_client: RazorpayClient | None = None,
    merchant_keys: dict[str, Any] | None = None,
    cart_jwts: dict[str, str] | None = None,
    allowed_categories: list[str] | None = None,
    quote_ttl_seconds: int = 300,
) -> PlanExecutionReport:
    """Coordinates execution across all merchant legs for a PurchasePlan.

    REPORT CLASSIFICATION INVARIANTS:
    - successful_legs: PAYMENT_CAPTURED only.
    - pending_legs: ORDER_CREATED, PAYMENT_PENDING, REQUIRES_REAUTH.
    - failed_legs: RELEASED, PAYMENT_FAILED, EXPIRED.
    """
    mandates = (
        db.query(MandateRecord)
        .filter_by(plan_id=plan.plan_id)
        .order_by(MandateRecord.merchant_id.asc())
        .all()
    )

    successful_legs: list[LegExecutionResult] = []
    failed_legs: list[LegExecutionResult] = []
    pending_legs: list[LegExecutionResult] = []

    for mandate_rec in mandates:
        if approved_merchant_ids is not None and mandate_rec.merchant_id not in approved_merchant_ids:
            res = release_failed_leg(
                mandate_record=mandate_rec,
                db=db,
                reason="Rejected by human operator during HITL review.",
                error_code="HITL_USER_REJECTED",
            )
            failed_legs.append(res)
            continue

        mid_key = None
        if merchant_keys and mandate_rec.merchant_id in merchant_keys:
            mid_key = merchant_keys[mandate_rec.merchant_id]
            if isinstance(mid_key, dict):
                mid_key = mid_key.get("private_key_pem")

        cart_jwt = cart_jwts.get(mandate_rec.merchant_id) if cart_jwts else None

        res = execute_plan_leg(
            mandate_record=mandate_rec,
            db=db,
            rzp_client=rzp_client,
            cart_jwt=cart_jwt,
            merchant_private_key_pem=mid_key,
            allowed_categories=allowed_categories,
            allowed_merchant_ids=approved_merchant_ids,
            quote_ttl_seconds=quote_ttl_seconds,
        )

        # Strict outcome categorization
        if res.status == LegExecutionStatus.CAPTURED:
            successful_legs.append(res)
        elif res.status in (LegExecutionStatus.FAILED, LegExecutionStatus.RELEASED, LegExecutionStatus.EXPIRED):
            failed_legs.append(res)
        else:
            # ORDER_CREATED, PENDING, REQUIRES_REAUTH are in-flight
            pending_legs.append(res)

    aggregate_status = sync_purchase_plan_status(plan, db)
    db.commit()

    total_captured = sum(m.captured_paise for m in mandates)
    total_released = sum(leg.released_reservation_paise for leg in failed_legs)

    return PlanExecutionReport(
        plan_id=plan.plan_id,
        intent_id=plan.intent_id,
        status=aggregate_status,
        total_authorized_paise=plan.total_authorized_paise,
        total_captured_paise=total_captured,
        total_released_paise=total_released,
        successful_legs=successful_legs,
        failed_legs=failed_legs,
        pending_legs=pending_legs,
    )


def get_plan_execution_report(plan: PurchasePlan, db: Session) -> PlanExecutionReport:
    """Generates an explicit, deterministic execution report for a PurchasePlan."""
    mandates = (
        db.query(MandateRecord)
        .filter_by(plan_id=plan.plan_id)
        .order_by(MandateRecord.merchant_id.asc())
        .all()
    )

    successful_legs: list[LegExecutionResult] = []
    failed_legs: list[LegExecutionResult] = []
    pending_legs: list[LegExecutionResult] = []

    total_released = 0
    for m in mandates:
        if m.status == MandateStatus.PAYMENT_CAPTURED:
            leg_status = LegExecutionStatus.CAPTURED
            released_for_leg = 0
        elif m.status in (MandateStatus.RELEASED, MandateStatus.PAYMENT_FAILED, MandateStatus.EXPIRED):
            leg_status = LegExecutionStatus.RELEASED
            # Actual released reservation = authorized minus already captured
            released_for_leg = max(0, m.authorized_amount_paise - m.captured_paise)
            total_released += released_for_leg
        elif m.status == MandateStatus.ORDER_CREATED:
            leg_status = LegExecutionStatus.ORDER_CREATED
            released_for_leg = 0
        else:
            leg_status = LegExecutionStatus.PENDING
            released_for_leg = 0

        res = LegExecutionResult(
            mandate_id=m.mandate_id,
            merchant_id=m.merchant_id,
            status=leg_status,
            authorized_amount_paise=m.authorized_amount_paise,
            captured_amount_paise=m.captured_paise,
            released_reservation_paise=released_for_leg,
            razorpay_order_id=m.razorpay_order_id,
            razorpay_payment_id=m.razorpay_payment_id,
        )

        if leg_status == LegExecutionStatus.CAPTURED:
            successful_legs.append(res)
        elif leg_status in (LegExecutionStatus.RELEASED, LegExecutionStatus.FAILED, LegExecutionStatus.EXPIRED):
            failed_legs.append(res)
        else:
            pending_legs.append(res)

    aggregate_status = sync_purchase_plan_status(plan, db)

    return PlanExecutionReport(
        plan_id=plan.plan_id,
        intent_id=plan.intent_id,
        status=aggregate_status,
        total_authorized_paise=plan.total_authorized_paise,
        total_captured_paise=sum(m.captured_paise for m in mandates),
        total_released_paise=total_released,
        successful_legs=successful_legs,
        failed_legs=failed_legs,
        pending_legs=pending_legs,
    )
