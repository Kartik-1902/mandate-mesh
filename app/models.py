"""SQLAlchemy ORM models for runtime state, catalog, deduplication, and audit ledger."""

import enum
from datetime import datetime
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


# =============================================================================
# Enums
# =============================================================================

class LedgerEntryType(str, enum.Enum):
    INTENT_ISSUED = "INTENT_ISSUED"
    CART_SIGNED = "CART_SIGNED"
    MANDATE_CREATED = "MANDATE_CREATED"
    POLICY_REJECTED = "POLICY_REJECTED"
    ORDER_CREATED = "ORDER_CREATED"
    WEBHOOK_RECEIVED = "WEBHOOK_RECEIVED"
    PAYMENT_CAPTURED = "PAYMENT_CAPTURED"
    RECEIPT_ISSUED = "RECEIPT_ISSUED"


class IntentStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"         # further transactions possible
    EXHAUSTED = "EXHAUSTED"   # transactions_consumed == max_transactions
    EXPIRED = "EXPIRED"       # intent TTL exceeded
    REVOKED = "REVOKED"       # explicitly cancelled


class MandateStatus(str, enum.Enum):
    RESERVED = "RESERVED"                 # initial state; spend cap decremented
    ORDER_CREATING = "ORDER_CREATING"     # Razorpay call in flight
    ORDER_CREATED = "ORDER_CREATED"       # Razorpay order exists; awaiting payment
    PAYMENT_PENDING = "PAYMENT_PENDING"   # payer initiated payment (client-side)
    PAYMENT_CAPTURED = "PAYMENT_CAPTURED" # webhook confirmed — TERMINAL
    PAYMENT_FAILED = "PAYMENT_FAILED"     # webhook confirmed — non-terminal intermediate
    EXPIRED = "EXPIRED"                   # order TTL exceeded — non-terminal intermediate
    RELEASED = "RELEASED"                 # reservation released — TERMINAL


class WebhookEventStatus(str, enum.Enum):
    RECEIVED = "RECEIVED"       # persisted; processing not yet started
    PROCESSING = "PROCESSING"   # handler in progress
    PROCESSED = "PROCESSED"     # handler completed successfully
    FAILED = "FAILED"           # handler raised an unrecoverable error


# =============================================================================
# Models
# =============================================================================

# BigInteger for PostgreSQL with SQLite Integer variant for native autoincrement
PK_BIGINT = BigInteger().with_variant(Integer, "sqlite")


class AuditLedgerEntry(Base):
    """Append-only, hash-chained, tamper-evident audit ledger row.
    Never queried for runtime financial decisions."""
    __tablename__ = "audit_ledger"

    id: Mapped[int] = mapped_column(PK_BIGINT, primary_key=True, autoincrement=True)
    entry_type: Mapped[LedgerEntryType] = mapped_column(Enum(LedgerEntryType), nullable=False)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    entry_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class IntentRegistry(Base):
    """Authoritative runtime budget and transaction counter per UserIntentCredential."""
    __tablename__ = "intent_registry"

    id: Mapped[int] = mapped_column(PK_BIGINT, primary_key=True, autoincrement=True)
    intent_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    nonce: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    spend_cap_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reserved_paise: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    captured_paise: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    max_transactions: Mapped[int] = mapped_column(Integer, nullable=False)
    transactions_consumed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[IntentStatus] = mapped_column(
        Enum(IntentStatus), default=IntentStatus.ACTIVE, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    @property
    def available_paise(self) -> int:
        return self.spend_cap_paise - self.reserved_paise - self.captured_paise


class MandateRecord(Base):
    """Mutable runtime state for one payment transaction."""
    __tablename__ = "mandate_records"
    __table_args__ = (
        UniqueConstraint("intent_id", "idempotency_key", name="uq_mandate_idempotency"),
    )

    id: Mapped[int] = mapped_column(PK_BIGINT, primary_key=True, autoincrement=True)
    mandate_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    intent_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    merchant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    cart_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorized_amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reserved_paise: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    captured_paise: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    status: Mapped[MandateStatus] = mapped_column(
        Enum(MandateStatus), default=MandateStatus.RESERVED, nullable=False
    )
    order_idempotency_key: Mapped[str | None] = mapped_column(
        String(40), unique=True, nullable=True
    )
    razorpay_order_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    razorpay_payment_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    mandate_jwt: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class WebhookEvent(Base):
    """Runtime deduplication store for inbound payment webhooks."""
    __tablename__ = "webhook_events"
    __table_args__ = (
        UniqueConstraint("razorpay_event_id", "event_type", name="uq_webhook_event"),
    )

    id: Mapped[int] = mapped_column(PK_BIGINT, primary_key=True, autoincrement=True)
    razorpay_event_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    razorpay_order_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    razorpay_payment_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    raw_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[WebhookEventStatus] = mapped_column(
        Enum(WebhookEventStatus), default=WebhookEventStatus.RECEIVED, nullable=False
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CatalogItem(Base):
    """Authoritative merchant product catalog in PostgreSQL."""
    __tablename__ = "catalog_items"
    __table_args__ = (
        UniqueConstraint("merchant_id", "sku", name="uq_merchant_sku"),
    )

    id: Mapped[int] = mapped_column(PK_BIGINT, primary_key=True, autoincrement=True)
    merchant_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    price_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    in_stock: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
