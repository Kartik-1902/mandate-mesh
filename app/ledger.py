"""Append-only, hash-chained, tamper-evident audit ledger.

Provides:
- `append_entry()`: Appends a new verified entry to the chain under advisory locking.
- `verify_chain()`: Scans the entire ledger from genesis to head, mathematically
  verifying every SHA-256 link.

NOTE: Per ADR-004, `append_entry()` flushes but does not commit internally.
The calling service owns the database transaction boundary.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.crypto import hash_object, sha256_hex
from app.models import AuditLedgerEntry, LedgerEntryType

import threading

GENESIS_HASH = "0" * 64
LEDGER_LOCK_ID = 1  # Application-wide advisory lock key for the linear audit chain
_LOCAL_DIALECT_LOCK = threading.RLock()


def _normalize_iso(dt: datetime) -> str:
    """Ensures consistent ISO-8601 UTC timestamp format across database backends."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def append_entry(
    db: Session,
    entry_type: LedgerEntryType,
    payload: dict[str, Any],
    actor: str,
) -> AuditLedgerEntry:
    """Appends a new immutable entry to the audit ledger.

    Acquires `pg_advisory_xact_lock(1)` when running against PostgreSQL to serialize
    all concurrent appends into a single strictly linear chain without table locks.
    Flushes changes to the session without committing, preserving transaction atomicity.
    """
    is_postgres = False
    try:
        bind = db.get_bind()
        if bind and bind.dialect.name == "postgresql":
            is_postgres = True
            db.execute(text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": LEDGER_LOCK_ID})
    except Exception:
        pass

    # For non-PostgreSQL dialects (e.g. multi-threaded SQLite tests), serialize via process lock
    if not is_postgres:
        _LOCAL_DIALECT_LOCK.acquire()

    try:
        # Read latest head entry
        last = db.query(AuditLedgerEntry).order_by(AuditLedgerEntry.id.desc()).first()
        prev_hash = last.entry_hash if last else GENESIS_HASH

        # Compute canonical payload hash
        payload_hash = hash_object(payload)

        # Application-supplied timestamp ensures Python hash matches persisted row exactly
        created_at = datetime.now(timezone.utc)
        created_at_iso = _normalize_iso(created_at)

        # Compute tamper-evident entry hash
        entry_hash = sha256_hex(f"{prev_hash}{payload_hash}{created_at_iso}".encode("utf-8"))

        row = AuditLedgerEntry(
            entry_type=entry_type,
            actor=actor,
            payload=payload,
            payload_hash=payload_hash,
            prev_hash=prev_hash,
            entry_hash=entry_hash,
            created_at=created_at,
        )
        db.add(row)
        db.flush()  # Flushed within caller's transaction; caller commits
        return row
    finally:
        if not is_postgres:
            _LOCAL_DIALECT_LOCK.release()


def verify_chain(db: Session) -> tuple[bool, int | None]:
    """Forensically scans all audit ledger entries sequentially from id=1 to head.

    Recomputes payload hashes, previous hash linkages, and entry hashes.
    Returns:
        (True, None) if the entire chain is valid and untampered.
        (False, broken_entry_id) at the first point of detected mutation or deletion.
    """
    entries = db.query(AuditLedgerEntry).order_by(AuditLedgerEntry.id.asc()).all()
    prev_hash = GENESIS_HASH

    for entry in entries:
        # 1. Check previous hash linkage
        if entry.prev_hash != prev_hash:
            return False, entry.id

        # 2. Recompute and verify payload hash
        recomputed_payload_hash = hash_object(entry.payload)
        if entry.payload_hash != recomputed_payload_hash:
            return False, entry.id

        # 3. Recompute and verify entry hash
        created_at_iso = _normalize_iso(entry.created_at)
        recomputed_entry_hash = sha256_hex(
            f"{prev_hash}{recomputed_payload_hash}{created_at_iso}".encode("utf-8")
        )
        if entry.entry_hash != recomputed_entry_hash:
            return False, entry.id

        prev_hash = entry.entry_hash

    return True, None
