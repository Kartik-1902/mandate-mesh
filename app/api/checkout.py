"""Merchant Catalog & Cart Signing API."""

from typing import Any
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_merchant_private_key_pem
from app.merchant import seed_catalog, sign_cart
from app.models import CatalogItem
from app.schemas import MerchantSignedCart

router = APIRouter(tags=["Merchant & Checkout"])


class LineItemReq(BaseModel):
    sku: str
    quantity: int = Field(default=1, ge=1)


class SignCartRequest(BaseModel):
    merchant_id: str
    line_items: list[LineItemReq]
    tax_paise: int = 0


class SignCartResponse(BaseModel):
    cart: MerchantSignedCart
    cart_jwt: str


@router.get("/catalog.json", status_code=status.HTTP_200_OK)
def get_merchant_catalog(
    merchant_id: str = "merchant_cakehouse_01",
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """Returns authoritative merchant product catalog for autonomous AI agents."""
    items = db.query(CatalogItem).filter_by(merchant_id=merchant_id).all()
    if not items:
        # Seed default catalog if empty
        items = seed_catalog(db, merchant_id=merchant_id)

    return [
        {
            "sku": item.sku,
            "name": item.name,
            "description": item.description,
            "category": item.category,
            "price_paise": item.price_paise,
            "in_stock": item.in_stock,
        }
        for item in items
    ]


@router.post("/checkout/sign-cart", status_code=status.HTTP_200_OK, response_model=SignCartResponse)
def checkout_sign_cart(
    req: SignCartRequest,
    db: Session = Depends(get_db),
    merchant_priv: bytes = Depends(get_merchant_private_key_pem),
) -> SignCartResponse:
    """Authoritatively prices requested SKUs from database catalog and issues signed MerchantSignedCart JWT."""
    line_items_dict = [{"sku": li.sku, "quantity": li.quantity} for li in req.line_items]

    cart_model, cart_jwt = sign_cart(
        merchant_id=req.merchant_id,
        line_items_req=line_items_dict,
        merchant_private_key_pem=merchant_priv,
        db=db,
        tax_paise=req.tax_paise,
    )

    return SignCartResponse(cart=cart_model, cart_jwt=cart_jwt)
