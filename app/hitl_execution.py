"""Milestone M8: Mixed-Merchant HITL, JIT Revalidation, and Partial-Failure Engine (ADR-013).

This module coordinates:
1. Pre-execution JIT revalidation of merchant stock and cart quote TTLs.
2. Deterministic re-quotation upon quote expiry while awaiting HITL approval.
3. Independent per-leg execution and rejection under the M3 Mandate FSM.
4. Strict non-reversibility of already-captured payments (never roll back captured payments).
5. Independent failed-leg reservation release without mutating captured funds.
6. Aggregate PurchasePlan status synchronization (including PARTIAL_COMPLETE).
7. Explicit, deterministic execution and failure reporting without LLM involvement.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

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
from app.schemas import MerchantSignedCart


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
        # At least one captured, but not all captured -> PARTIAL_COMPLETE
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


def revalidate_or_requote_leg(
    mandate_record: MandateRecord,
    db: Session,
    cart_jwt: str | None = None,
    merchant_private_key_pem: bytes | str | Path | None = None,
    merchant_public_key_pem: bytes | str | Path | None = None,
    quote_ttl_seconds: int = 300,
) -> tuple[bool, MerchantSignedCart | None, str | None, str | None]:
    """Performs deterministic JIT revalidation of merchant stock and quote validity.

    Returns:
        (is_valid_to_execute, fresh_signed_cart, fresh_cart_jwt, error_reason)
    """
    now = datetime.now(timezone.utc)

    # 1. Check merchant availability and catalog stock
    merchant_items = (
        db.query(CatalogItem)
        .filter_by(merchant_id=mandate_record.merchant_id)
        .all()
    )
    if not merchant_items or not any(it.in_stock for it in merchant_items):
        return False, None, None, f"Merchant '{mandate_record.merchant_id}' is unavailable or has no active stock."

    # 2. Inspect existing cart quote validity
    is_expired = False
    if cart_jwt:
        pub_key = merchant_public_key_pem or get_merchant_public_key(mandate_record.merchant_id)
        try:
            cart = verify_cart(cart_jwt, pub_key)
            if now > cart.expires_at:
                is_expired = True
            else:
                return True, cart, cart_jwt, None
        except Exception:
            is_expired = True
    else:
        # Check elapsed time from mandate creation against quote TTL
        elapsed = (now - mandate_record.created_at).total_seconds()
        if elapsed > quote_ttl_seconds:
            is_expired = True
        else:
            return True, None, None, None

    if not is_expired:
        return True, None, None, None

    # 3. Deterministic Re-Quotation Path for Expired Quotes
    in_stock_items = [it for it in merchant_items if it.in_stock]
    if not in_stock_items:
        return False, None, None, f"Merchant '{mandate_record.merchant_id}' items are out of stock."

    line_items_req = [{"sku": in_stock_items[0].sku, "quantity": 1}]
    try:
        fresh_cart, fresh_jwt = sign_cart(
            merchant_id=mandate_record.merchant_id,
            line_items_req=line_items_req,
            merchant_private_key_pem=merchant_private_key_pem,
            db=db,
        )
    except Exception as e:
        return False, None, None, f"Re-quotation failed for merchant '{mandate_record.merchant_id}': {e}"

    # Verify fresh quote price against original authorized amount
    if fresh_cart.total_paise > mandate_record.authorized_amount_paise:
        overspend = fresh_cart.total_paise - mandate_record.authorized_amount_paise
        return (
            False,
            fresh_cart,
            fresh_jwt,
            f"Re-quoted price Rs. {fresh_cart.total_paise / 100:.2f} exceeds authorized "
            f"Rs. {mandate_record.authorized_amount_paise / 100:.2f} by Rs. {overspend / 100:.2f}. "
            f"User re-authorization required.",
        )

    return True, fresh_cart, fresh_jwt, None


def execute_plan_leg(
    mandate_record: MandateRecord,
    db: Session,
    rzp_client: RazorpayClient | None = None,
    cart_jwt: str | None = None,
    merchant_private_key_pem: bytes | str | Path | None = None,
    merchant_public_key_pem: bytes | str | Path | None = None,
    quote_ttl_seconds: int = 300,
) -> LegExecutionResult:
    """Executes a single merchant mandate leg independently.

    EXECUTION INVARIANTS:
    1. Revalidates intent status and TTL.
    2. Revalidates merchant stock and quote TTL (triggering JIT re-quotation if expired).
    3. Fails closed on quote price increase or stock exhaustion.
    4. Transitions mandate state through M3 FSM: RESERVED -> ORDER_CREATING -> ORDER_CREATED.
    5. Creates Razorpay order deterministically using mandate order_idempotency_key.
    6. Does NOT capture payment here (capture occurs via webhook or explicit capture call).
    """
    rzp = rzp_client or RazorpayClient(mock_mode=True)

    # 1. Revalidate parent intent
    intent_reg = db.query(IntentRegistry).filter_by(intent_id=mandate_record.intent_id).first()
    if not intent_reg or intent_reg.status == IntentStatus.EXPIRED:
        return release_failed_leg(
            mandate_record=mandate_record,
            db=db,
            reason="User intent has expired or is invalid.",
            error_code="POLICY_INTENT_EXPIRED",
        )

    # 2. Revalidate mandate state (idempotency: skip if already created/captured/released)
    if mandate_record.status in (MandateStatus.ORDER_CREATED, MandateStatus.PAYMENT_PENDING):
        return LegExecutionResult(
            mandate_id=mandate_record.mandate_id,
            merchant_id=mandate_record.merchant_id,
            status=LegExecutionStatus.ORDER_CREATED,
            authorized_amount_paise=mandate_record.authorized_amount_paise,
            captured_amount_paise=mandate_record.captured_paise,
            razorpay_order_id=mandate_record.razorpay_order_id,
        )
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
    if mandate_record.status in (MandateStatus.RELEASED, MandateStatus.PAYMENT_FAILED, MandateStatus.EXPIRED):
        return LegExecutionResult(
            mandate_id=mandate_record.mandate_id,
            merchant_id=mandate_record.merchant_id,
            status=LegExecutionStatus.RELEASED,
            authorized_amount_paise=mandate_record.authorized_amount_paise,
            captured_amount_paise=0,
            released_reservation_paise=mandate_record.authorized_amount_paise,
            error_code="LEG_ALREADY_RELEASED",
            error_message="Mandate has already been released or failed.",
        )

    # 3. JIT Revalidation of Merchant Stock and Quote TTL
    is_valid, fresh_cart, fresh_jwt, error_msg = revalidate_or_requote_leg(
        mandate_record=mandate_record,
        db=db,
        cart_jwt=cart_jwt,
        merchant_private_key_pem=merchant_private_key_pem,
        merchant_public_key_pem=merchant_public_key_pem,
        quote_ttl_seconds=quote_ttl_seconds,
    )
    if not is_valid:
        if "re-authorization required" in (error_msg or "").lower():
            return LegExecutionResult(
                mandate_id=mandate_record.mandate_id,
                merchant_id=mandate_record.merchant_id,
                status=LegExecutionStatus.REQUIRES_REAUTH,
                authorized_amount_paise=mandate_record.authorized_amount_paise,
                error_code="PRICE_INCREASE_REQUIRES_REAUTH",
                error_message=error_msg,
            )
        return release_failed_leg(
            mandate_record=mandate_record,
            db=db,
            reason=error_msg or "JIT revalidation failed.",
            error_code="MERCHANT_UNAVAILABLE",
        )

    # If fresh cart was re-quoted at same/lower price, update cart_hash
    if fresh_cart:
        mandate_record.cart_hash = fresh_cart.cart_hash

    # 4. FSM Transition: RESERVED -> ORDER_CREATING
    transition(mandate_record, MandateStatus.ORDER_CREATING, db)

    try:
        # 5. Create Razorpay order
        rzp_order = rzp.create_order(
            amount_paise=mandate_record.authorized_amount_paise,
            currency="INR",
            receipt=mandate_record.order_idempotency_key,
        )
        mandate_record.razorpay_order_id = rzp_order["id"]

        # 6. FSM Transition: ORDER_CREATING -> ORDER_CREATED
        transition(mandate_record, MandateStatus.ORDER_CREATED, db)

        # Append to audit ledger
        append_entry(
            db=db,
            entry_type=LedgerEntryType.ORDER_CREATED,
            payload={
                "mandate_id": mandate_record.mandate_id,
                "merchant_id": mandate_record.merchant_id,
                "order_id": rzp_order["id"],
                "amount_paise": mandate_record.authorized_amount_paise,
            },
            actor="system:order-service",
        )
        db.commit()

        return LegExecutionResult(
            mandate_id=mandate_record.mandate_id,
            merchant_id=mandate_record.merchant_id,
            status=LegExecutionStatus.ORDER_CREATED,
            authorized_amount_paise=mandate_record.authorized_amount_paise,
            captured_amount_paise=0,
            razorpay_order_id=rzp_order["id"],
        )
    except Exception as e:
        db.rollback()
        return release_failed_leg(
            mandate_record=mandate_record,
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

    SAFETY INVARIANT:
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

    released_amount = mandate_record.reserved_paise

    if mandate_record.status == MandateStatus.RESERVED:
        transition(mandate_record, MandateStatus.ORDER_CREATING, db)
        transition(mandate_record, MandateStatus.RELEASED, db)
    elif mandate_record.status in (MandateStatus.ORDER_CREATED, MandateStatus.PAYMENT_PENDING):
        transition(mandate_record, MandateStatus.PAYMENT_FAILED, db)
        transition(mandate_record, MandateStatus.RELEASED, db)
    elif mandate_record.status == MandateStatus.ORDER_CREATING:
        transition(mandate_record, MandateStatus.RELEASED, db)

    intent_reg = db.query(IntentRegistry).filter_by(intent_id=mandate_record.intent_id).first()
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
    quote_ttl_seconds: int = 300,
) -> PlanExecutionReport:
    """Coordinates execution across all merchant legs for a PurchasePlan.

    Supports:
    - Aggregate approval: approved_merchant_ids is None (all legs approved).
    - Selective/Partial HITL approval: approved_merchant_ids specifies approved merchants;
      unapproved legs are rejected and their reservations released.
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
            quote_ttl_seconds=quote_ttl_seconds,
        )
        if res.status in (LegExecutionStatus.CAPTURED, LegExecutionStatus.ORDER_CREATED):
            successful_legs.append(res)
        elif res.status in (LegExecutionStatus.FAILED, LegExecutionStatus.RELEASED, LegExecutionStatus.REQUIRES_REAUTH):
            failed_legs.append(res)
        else:
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
        leg_status = LegExecutionStatus.PENDING
        if m.status == MandateStatus.PAYMENT_CAPTURED:
            leg_status = LegExecutionStatus.CAPTURED
        elif m.status == MandateStatus.ORDER_CREATED:
            leg_status = LegExecutionStatus.ORDER_CREATED
        elif m.status in (MandateStatus.RELEASED, MandateStatus.PAYMENT_FAILED, MandateStatus.EXPIRED):
            leg_status = LegExecutionStatus.RELEASED

        res = LegExecutionResult(
            mandate_id=m.mandate_id,
            merchant_id=m.merchant_id,
            status=leg_status,
            authorized_amount_paise=m.authorized_amount_paise,
            captured_amount_paise=m.captured_paise,
            released_reservation_paise=m.authorized_amount_paise if leg_status == LegExecutionStatus.RELEASED else 0,
            razorpay_order_id=m.razorpay_order_id,
            razorpay_payment_id=m.razorpay_payment_id,
        )

        if leg_status in (LegExecutionStatus.CAPTURED, LegExecutionStatus.ORDER_CREATED):
            successful_legs.append(res)
        elif leg_status == LegExecutionStatus.RELEASED:
            failed_legs.append(res)
            total_released += res.released_reservation_paise
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
