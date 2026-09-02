"""Automated background and startup reconciliation engine for Mandate Mesh.

Enforces:
- Self-healing recovery for mandates stuck in `ORDER_CREATING` due to network partitions
  or application crashes during Razorpay order creation (ADR-005).
- Queries Razorpay Orders API using `receipt = order_idempotency_key`.
- If matched: advances status to `ORDER_CREATED` and records `razorpay_order_id`.
- If not found: resets status back to `RESERVED` so the transaction can be safely retried.
"""

from __future__ import annotations

from typing import Any
from sqlalchemy.orm import Session

from app.ledger import append_entry
from app.mandate_fsm import transition
from app.models import LedgerEntryType, MandateRecord, MandateStatus
from app.razorpay_client import RazorpayClient


def reconcile_stuck_orders(
    db: Session,
    razorpay_client: RazorpayClient,
) -> list[dict[str, Any]]:
    """Scans and reconciles all MandateRecord entries currently in ORDER_CREATING state.

    Args:
        db: SQLAlchemy database session.
        razorpay_client: Active or Mock Razorpay client instance.

    Returns:
        list[dict]: Summary of reconciled mandate records.
    """
    stuck_records = (
        db.query(MandateRecord)
        .filter(MandateRecord.status == MandateStatus.ORDER_CREATING)
        .all()
    )

    results: list[dict[str, Any]] = []

    for record in stuck_records:
        if not record.order_idempotency_key:
            continue

        matched_order = razorpay_client.reconcile_order(record.order_idempotency_key)

        if matched_order:
            record.razorpay_order_id = matched_order["id"]
            transition(record, MandateStatus.ORDER_CREATED, db)
            append_entry(
                db=db,
                entry_type=LedgerEntryType.ORDER_CREATED,
                payload={
                    "mandate_id": record.mandate_id,
                    "razorpay_order_id": matched_order["id"],
                    "receipt": record.order_idempotency_key,
                    "reconciled": True,
                },
                actor="system:reconciler",
            )
            results.append({
                "mandate_id": record.mandate_id,
                "order_idempotency_key": record.order_idempotency_key,
                "razorpay_order_id": matched_order["id"],
                "status": "ORDER_CREATED",
                "reconciled": True,
            })
        else:
            # Order was never created at Razorpay; reset status to RESERVED for retry (FSM)
            transition(record, MandateStatus.RESERVED, db)
            results.append({
                "mandate_id": record.mandate_id,
                "order_idempotency_key": record.order_idempotency_key,
                "razorpay_order_id": None,
                "status": "RESERVED",
                "reconciled": False,
            })

    if stuck_records:
        db.commit()

    return results
