"""Audit Ledger API."""

from typing import Any
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.ledger import _normalize_iso, verify_chain
from app.models import AuditLedgerEntry

router = APIRouter(prefix="/api/v1/ledger", tags=["Audit Ledger"])


class VerifyChainResponse(BaseModel):
    valid: bool
    broken_at_entry_id: int | None
    total_entries: int


@router.get("/verify-chain", response_model=VerifyChainResponse)
def verify_audit_ledger_chain(
    db: Session = Depends(get_db),
) -> VerifyChainResponse:
    """Forensically scans all audit ledger rows from genesis to head and verifies SHA-256 chain validity."""
    is_valid, broken_id = verify_chain(db)
    count = db.query(AuditLedgerEntry).count()
    return VerifyChainResponse(
        valid=is_valid,
        broken_at_entry_id=broken_id,
        total_entries=count,
    )


@router.get("/entries", status_code=status.HTTP_200_OK)
def list_audit_ledger_entries(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """Returns recent audit ledger entries in ascending order."""
    entries = (
        db.query(AuditLedgerEntry)
        .order_by(AuditLedgerEntry.id.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": e.id,
            "entry_type": e.entry_type.value if hasattr(e.entry_type, "value") else str(e.entry_type),
            "actor": e.actor,
            "payload": e.payload,
            "payload_hash": e.payload_hash,
            "prev_hash": e.prev_hash,
            "entry_hash": e.entry_hash,
            "created_at": _normalize_iso(e.created_at),
        }
        for e in reversed(entries)
    ]
