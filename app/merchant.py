"""Authoritative merchant catalog lookup and cart signing engine.

NOTE: Per §2.4, the merchant catalog is the ONLY authoritative source of pricing.
The agent toolbox accepts only SKU and quantity — prices are never supplied by agents.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4
from sqlalchemy.orm import Session

from app.crypto import compute_cart_hash, issue_cart_jwt
from app.errors import CatalogSkuNotFound
from app.ledger import append_entry
from app.models import CatalogItem, LedgerEntryType
from app.schemas import CartLineItem, MerchantSignedCart


def seed_catalog(
    db: Session,
    merchant_id: str = "merchant_cakehouse_01",
) -> list[CatalogItem]:
    """Pre-seeds standard merchant inventory items in PostgreSQL/SQLite if not present."""
    default_items = [
        {
            "sku": "CAKE-CHOC-001",
            "name": "Chocolate Truffle Cake (1kg)",
            "description": "Rich dark chocolate sponge layered with Belgian truffle ganache.",
            "category": "bakery",
            "price_paise": 94000,  # ₹940.00
            "in_stock": True,
        },
        {
            "sku": "CAKE-VAN-001",
            "name": "Classic Vanilla Bean Cake (1kg)",
            "description": "Fluffy Madagascar vanilla sponge with buttercream frosting.",
            "category": "bakery",
            "price_paise": 85000,  # ₹850.00
            "in_stock": True,
        },
        {
            "sku": "CAKE-PREM-001",
            "name": "Luxury 3-Tier Fondant Cake (3kg)",
            "description": "Gourmet multi-tier celebration cake with gold leaf detailing.",
            "category": "bakery",
            "price_paise": 494000,  # ₹4,940.00 (Over-budget test SKU)
            "in_stock": True,
        },
        {
            "sku": "GIFT-CARD-001",
            "name": "Celebration Greeting Card & Candles",
            "description": "Handmade birthday card with premium sparkling candles.",
            "category": "gifting",
            "price_paise": 25000,  # ₹250.00
            "in_stock": True,
        },
        {
            "sku": "ELEC-HEAD-001",
            "name": "Wireless Noise Cancelling Headphones",
            "description": "Over-ear bluetooth headphones with spatial audio.",
            "category": "electronics",  # Disallowed category for bakery intent
            "price_paise": 120000,  # ₹1,200.00
            "in_stock": True,
        },
    ]

    seeded = []
    for item_data in default_items:
        existing = db.query(CatalogItem).filter_by(sku=item_data["sku"]).first()
        if not existing:
            item = CatalogItem(
                merchant_id=merchant_id,
                sku=item_data["sku"],
                name=item_data["name"],
                description=item_data["description"],
                category=item_data["category"],
                price_paise=item_data["price_paise"],
                in_stock=item_data["in_stock"],
            )
            db.add(item)
            seeded.append(item)
        else:
            seeded.append(existing)

    db.flush()
    return seeded


def sign_cart(
    merchant_id: str,
    line_items_req: list[dict[str, Any]],
    merchant_private_key_pem: bytes | str | Path,
    db: Session,
    tax_paise: int = 0,
    ttl_seconds: int = 300,
    kid: str | None = None,
) -> tuple[MerchantSignedCart, str]:
    """Authoritatively prices line items against the merchant's catalog table and signs a cart quote.

    Args:
        merchant_id: Unique merchant identifier.
        line_items_req: List of dicts containing only {"sku": str, "quantity": int}.
        merchant_private_key_pem: Merchant's private key for signing.
        db: Active SQLAlchemy database session.
        tax_paise: Additional tax amount in paise.
        ttl_seconds: Cart expiration window (defaults to 5 minutes / 300s).
        kid: Key identifier for the JWT header (defaults to f"{merchant_id}:key-1").

    Returns:
        tuple[MerchantSignedCart, str]: The validated cart model and signed JWT string.

    Raises:
        CatalogSkuNotFound: If any requested SKU is missing from the merchant's catalog.
    """
    built_items: list[CartLineItem] = []

    for req_item in line_items_req:
        sku = req_item["sku"]
        qty = int(req_item.get("quantity", 1))
        if qty <= 0:
            raise ValueError("Line item quantity must be greater than zero.")

        catalog_row = (
            db.query(CatalogItem)
            .filter_by(merchant_id=merchant_id, sku=sku)
            .first()
        )
        if not catalog_row:
            raise CatalogSkuNotFound(sku=sku)

        built_items.append(
            CartLineItem(
                sku=catalog_row.sku,
                name=catalog_row.name,
                category=catalog_row.category,
                unit_price_paise=catalog_row.price_paise,
                quantity=qty,
            )
        )

    now = datetime.now(timezone.utc)
    cart = MerchantSignedCart(
        cart_id=uuid4(),
        merchant_id=merchant_id,
        line_items=built_items,
        tax_paise=tax_paise,
        currency="INR",
        cart_hash="",  # Placeholder to be populated below
        issued_at=now,
        expires_at=now + timedelta(seconds=ttl_seconds),
    )

    # Compute canonical cart hash
    cart.cart_hash = compute_cart_hash(cart)

    # Issue signed JWT with embedded cart_hash and merchant-specific kid
    effective_kid = kid or f"{merchant_id}:key-1"
    cart_jwt = issue_cart_jwt(cart, merchant_private_key_pem, kid=effective_kid)

    # Record in audit ledger
    append_entry(
        db=db,
        entry_type=LedgerEntryType.CART_SIGNED,
        payload={
            "cart_id": str(cart.cart_id),
            "cart_hash": cart.cart_hash,
            "merchant_id": cart.merchant_id,
            "total_paise": cart.total_paise,
            "expires_at": cart.expires_at.isoformat(),
        },
        actor=f"merchant:{merchant_id}",
    )

    return cart, cart_jwt
