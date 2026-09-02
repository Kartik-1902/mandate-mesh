"""Canonical Product Catalog API (Milestone M4 / ADR-007)."""

from typing import Any
from uuid import UUID
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.merchant import seed_catalog
from app.models import CanonicalProduct

router = APIRouter(prefix="/api/v1/products", tags=["Canonical Products"])


class CanonicalProductResponse(BaseModel):
    product_id: UUID
    canonical_name: str
    brand: str | None = None
    category: str
    tags: list[str] | dict[str, Any] = []
    description: str | None = None

    model_config = {"from_attributes": True}


@router.get("", status_code=status.HTTP_200_OK, response_model=list[CanonicalProductResponse])
def list_canonical_products(
    category: str | None = None,
    query: str | None = None,
    db: Session = Depends(get_db),
) -> list[CanonicalProduct]:
    """Returns canonical product definitions across all merchants."""
    q = db.query(CanonicalProduct)
    if category:
        q = q.filter(CanonicalProduct.category.ilike(f"%{category}%"))

    products = q.all()
    if not products:
        seed_catalog(db)
        products = q.all()

    if query:
        q_lower = query.lower()
        products = [
            p
            for p in products
            if q_lower in p.canonical_name.lower()
            or q_lower in (p.description or "").lower()
            or (p.brand and q_lower in p.brand.lower())
        ]

    return products
