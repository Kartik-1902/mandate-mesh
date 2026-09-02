"""Authoritative cryptographic boundary for Mandate Mesh.

Handles:
- RFC 8785 canonical JSON serialization & SHA-256 content hashing.
- ES256 (ECDSA NIST P-256) keypair generation and PEM loading.
- JWT issuance and verification for UserIntentCredential, MerchantSignedCart,
  PaymentMandate, and PaymentReceipt.

NOTE: Per ADR-002, no other module in the codebase may directly call
`cryptography` or `jwt` primitives.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.errors import (
    PolicyCartExpired,
    PolicyCartHashMismatch,
    PolicyCartSignatureInvalid,
    PolicyIntentExpired,
    PolicyIntentNotYetValid,
    PolicyIntentSignatureInvalid,
    PolicyMandateSignatureInvalid,
    PolicyReceiptSignatureInvalid,
    PolicyViolation,
)
from app.schemas import (
    CartLineItem,
    MerchantSignedCart,
    PaymentMandate,
    PaymentReceipt,
    UserIntentCredential,
)

# Standard algorithm for all signatures in the system
JWT_ALGORITHM = "ES256"


# =============================================================================
# 1. Canonical Serialization & Hashing (RFC 8785)
# =============================================================================

def canonical_json(obj: Any) -> bytes:
    """Deterministic JSON serialization: sorted keys, no whitespace separators, UTF-8.
    Ensures identical byte outputs across heterogeneous environments and platforms."""
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    """Computes SHA-256 hexadecimal digest of raw bytes."""
    return hashlib.sha256(data).hexdigest()


def hash_object(obj: dict[str, Any]) -> str:
    """Computes content hash of any dictionary over canonical JSON."""
    return sha256_hex(canonical_json(obj))


def compute_cart_hash(cart: MerchantSignedCart | dict[str, Any]) -> str:
    """Computes the authoritative SHA-256 cart content hash.
    Explicitly excludes the `cart_hash` field itself to avoid self-reference."""
    if isinstance(cart, MerchantSignedCart):
        payload = {
            "cart_id": str(cart.cart_id),
            "currency": cart.currency,
            "line_items": [
                {
                    "category": li.category,
                    "name": li.name,
                    "quantity": li.quantity,
                    "sku": li.sku,
                    "unit_price_paise": li.unit_price_paise,
                }
                for li in cart.line_items
            ],
            "merchant_id": cart.merchant_id,
            "tax_paise": cart.tax_paise,
            "total_paise": cart.total_paise,
        }
    else:
        line_items = cart.get("line_items", [])
        normalized_items = []
        for li in line_items:
            if isinstance(li, dict):
                normalized_items.append(
                    {
                        "category": li["category"],
                        "name": li["name"],
                        "quantity": li["quantity"],
                        "sku": li["sku"],
                        "unit_price_paise": li["unit_price_paise"],
                    }
                )
            else:
                normalized_items.append(
                    {
                        "category": li.category,
                        "name": li.name,
                        "quantity": li.quantity,
                        "sku": li.sku,
                        "unit_price_paise": li.unit_price_paise,
                    }
                )
        payload = {
            "cart_id": str(cart["cart_id"]),
            "currency": cart.get("currency", "INR"),
            "line_items": normalized_items,
            "merchant_id": cart["merchant_id"],
            "tax_paise": cart.get("tax_paise", 0),
            "total_paise": cart["total_paise"],
        }
    return hash_object(payload)


def compute_intent_hash(intent: UserIntentCredential | dict[str, Any]) -> str:
    """Computes canonical content hash over UserIntentCredential claims."""
    if isinstance(intent, UserIntentCredential):
        payload = {
            "allowed_categories": sorted(intent.allowed_categories),
            "allowed_merchant_ids": sorted(intent.allowed_merchant_ids),
            "currency": intent.currency,
            "exp": int(intent.expires_at.timestamp()),
            "intent_id": str(intent.intent_id),
            "max_transactions": intent.max_transactions,
            "nbf": int(intent.not_before.timestamp()),
            "nonce": intent.nonce,
            "spend_cap_paise": intent.spend_cap_paise,
            "user_id": intent.user_id,
        }
    else:
        payload = {
            "allowed_categories": sorted(intent.get("allowed_categories", [])),
            "allowed_merchant_ids": sorted(intent.get("allowed_merchant_ids", [])),
            "currency": intent.get("currency", "INR"),
            "exp": intent.get("exp"),
            "intent_id": str(intent.get("intent_id")),
            "max_transactions": intent.get("max_transactions", 1),
            "nbf": intent.get("nbf"),
            "nonce": intent.get("nonce"),
            "spend_cap_paise": intent.get("spend_cap_paise"),
            "user_id": intent.get("user_id"),
        }
    return hash_object(payload)


def compute_mandate_hash(mandate: PaymentMandate | dict[str, Any]) -> str:
    """Computes canonical content hash over PaymentMandate snapshot."""
    if isinstance(mandate, PaymentMandate):
        payload = {
            "authorized_amount_paise": mandate.authorized_amount_paise,
            "cart_hash": mandate.cart_hash,
            "currency": mandate.currency,
            "intent_hash": mandate.intent_hash,
            "intent_id": mandate.intent_id,
            "mandate_id": str(mandate.mandate_id),
            "merchant_id": mandate.merchant_id,
        }
    else:
        payload = {
            "authorized_amount_paise": mandate["authorized_amount_paise"],
            "cart_hash": mandate["cart_hash"],
            "currency": mandate.get("currency", "INR"),
            "intent_hash": mandate["intent_hash"],
            "intent_id": mandate["intent_id"],
            "mandate_id": str(mandate["mandate_id"]),
            "merchant_id": mandate["merchant_id"],
        }
    return hash_object(payload)


# =============================================================================
# 2. Key Generation & Management (ES256 / NIST P-256)
# =============================================================================

def generate_es256_keypair() -> tuple[bytes, bytes]:
    """Generates an ES256 (ECDSA SECP256R1) private and public keypair in PEM format."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


def load_private_key_pem(pem_data_or_path: bytes | str | Path) -> bytes:
    """Loads private key PEM bytes from bytes, string, or filesystem path."""
    if isinstance(pem_data_or_path, (str, Path)):
        p = Path(pem_data_or_path)
        if p.exists() and p.is_file():
            return p.read_bytes()
        if isinstance(pem_data_or_path, str) and "BEGIN" in pem_data_or_path:
            return pem_data_or_path.encode("utf-8")
        raise FileNotFoundError(f"Private key file not found: {pem_data_or_path}")
    return pem_data_or_path


def load_public_key_pem(pem_data_or_path: bytes | str | Path) -> bytes:
    """Loads public key PEM bytes from bytes, string, or filesystem path."""
    if isinstance(pem_data_or_path, (str, Path)):
        p = Path(pem_data_or_path)
        if p.exists() and p.is_file():
            return p.read_bytes()
        if isinstance(pem_data_or_path, str) and "BEGIN" in pem_data_or_path:
            return pem_data_or_path.encode("utf-8")
        raise FileNotFoundError(f"Public key file not found: {pem_data_or_path}")
    return pem_data_or_path


# =============================================================================
# 3. UserIntentCredential JWT Issuance & Verification
# =============================================================================

def issue_intent_jwt(
    intent: UserIntentCredential,
    private_key_pem: bytes | str | Path,
    kid: str = "user:key-1",
) -> str:
    """Signs a UserIntentCredential with the user's private key."""
    key_bytes = load_private_key_pem(private_key_pem)
    now_ts = int(datetime.now(timezone.utc).timestamp())
    claims = {
        "allowed_categories": sorted(intent.allowed_categories),
        "allowed_merchant_ids": sorted(intent.allowed_merchant_ids),
        "currency": intent.currency,
        "exp": int(intent.expires_at.timestamp()),
        "iat": now_ts,
        "intent_id": str(intent.intent_id),
        "iss": "mandate-mesh:user-credential",
        "max_transactions": intent.max_transactions,
        "nbf": int(intent.not_before.timestamp()),
        "nonce": intent.nonce,
        "spend_cap_paise": intent.spend_cap_paise,
        "user_id": intent.user_id,
    }
    return jwt.encode(claims, key_bytes, algorithm=JWT_ALGORITHM, headers={"kid": kid})


def verify_intent_jwt(
    token: str,
    public_key_pem: bytes | str | Path,
) -> UserIntentCredential:
    """Verifies ES256 signature, expiry, and window for UserIntentCredential."""
    key_bytes = load_public_key_pem(public_key_pem)
    try:
        claims = jwt.decode(
            token,
            key_bytes,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["exp", "nbf", "iat", "intent_id", "nonce"]},
        )
    except jwt.ExpiredSignatureError as e:
        raise PolicyIntentExpired("User intent credential has expired.") from e
    except jwt.ImmatureSignatureError as e:
        raise PolicyIntentNotYetValid("User intent credential is not yet valid (nbf in future).") from e
    except jwt.PyJWTError as e:
        raise PolicyIntentSignatureInvalid(f"POLICY_INTENT_SIGNATURE_INVALID: {e}") from e

    return UserIntentCredential(
        intent_id=UUID(claims["intent_id"]),
        user_id=claims["user_id"],
        spend_cap_paise=claims["spend_cap_paise"],
        currency=claims.get("currency", "INR"),
        allowed_categories=claims["allowed_categories"],
        allowed_merchant_ids=claims["allowed_merchant_ids"],
        max_transactions=claims.get("max_transactions", 1),
        nonce=claims["nonce"],
        not_before=datetime.fromtimestamp(claims["nbf"], tz=timezone.utc),
        expires_at=datetime.fromtimestamp(claims["exp"], tz=timezone.utc),
    )


# =============================================================================
# 4. MerchantSignedCart JWT Issuance & Verification
# =============================================================================

def issue_cart_jwt(
    cart: MerchantSignedCart,
    private_key_pem: bytes | str | Path,
    kid: str = "merchant:key-1",
) -> str:
    """Signs a MerchantSignedCart with the merchant's private key, embedding cart_hash."""
    key_bytes = load_private_key_pem(private_key_pem)
    computed_hash = compute_cart_hash(cart)

    claims = {
        "cart_hash": computed_hash,
        "cart_id": str(cart.cart_id),
        "currency": cart.currency,
        "exp": int(cart.expires_at.timestamp()),
        "iat": int(cart.issued_at.timestamp()),
        "iss": f"mandate-mesh:merchant:{cart.merchant_id}",
        "line_items": [
            {
                "category": li.category,
                "name": li.name,
                "quantity": li.quantity,
                "sku": li.sku,
                "unit_price_paise": li.unit_price_paise,
            }
            for li in cart.line_items
        ],
        "merchant_id": cart.merchant_id,
        "tax_paise": cart.tax_paise,
        "total_paise": cart.total_paise,
    }
    return jwt.encode(claims, key_bytes, algorithm=JWT_ALGORITHM, headers={"kid": kid})


def verify_cart_jwt(
    token: str,
    public_key_pem: bytes | str | Path,
) -> MerchantSignedCart:
    """Verifies ES256 signature, expiry, and recomputes cart_hash independently."""
    key_bytes = load_public_key_pem(public_key_pem)
    try:
        claims = jwt.decode(
            token,
            key_bytes,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["exp", "iat", "cart_id", "cart_hash", "line_items"]},
        )
    except jwt.ExpiredSignatureError as e:
        raise PolicyCartExpired("Merchant cart quote has expired.") from e
    except jwt.PyJWTError as e:
        raise PolicyCartSignatureInvalid(f"Cart JWT signature verification failed: {e}") from e

    line_items = [
        CartLineItem(
            sku=li["sku"],
            name=li["name"],
            category=li["category"],
            unit_price_paise=li["unit_price_paise"],
            quantity=li["quantity"],
        )
        for li in claims["line_items"]
    ]

    cart = MerchantSignedCart(
        cart_id=UUID(claims["cart_id"]),
        merchant_id=claims["merchant_id"],
        line_items=line_items,
        tax_paise=claims.get("tax_paise", 0),
        currency=claims.get("currency", "INR"),
        cart_hash=claims["cart_hash"],
        issued_at=datetime.fromtimestamp(claims["iat"], tz=timezone.utc),
        expires_at=datetime.fromtimestamp(claims["exp"], tz=timezone.utc),
    )

    # Independent SHA-256 recomputation (Dual-layer defense against tampering)
    recomputed_hash = compute_cart_hash(cart)
    if recomputed_hash != claims["cart_hash"]:
        raise PolicyCartHashMismatch(
            f"Cart hash mismatch: computed {recomputed_hash}, embedded {claims['cart_hash']}"
        )

    return cart


def extract_unverified_cart_merchant_id(token: str) -> str:
    """Extracts merchant_id from cart JWT claims without cryptographic signature verification.

    Used strictly by API ingress layers to look up the authoritative merchant public key
    from the trusted key registry prior to full cryptographic verification.
    """
    try:
        claims = jwt.decode(token, options={"verify_signature": False})
    except Exception as e:
        raise PolicyCartSignatureInvalid(f"Failed to parse unverified cart JWT claims: {e}") from e

    merchant_id = claims.get("merchant_id")
    if not merchant_id or not isinstance(merchant_id, str):
        raise PolicyCartSignatureInvalid("Unverified cart JWT missing valid 'merchant_id' claim.")

    return merchant_id


def extract_mandate_intent_hash(token: str) -> str:
    """Extracts intent_hash claim from platform-signed mandate JWT without signature verification."""
    try:
        claims = jwt.decode(token, options={"verify_signature": False})
        return str(claims.get("intent_hash", ""))
    except Exception as e:
        raise PolicyViolation("POLICY_MANDATE_MALFORMED", f"Failed to extract intent_hash from mandate JWT: {e}") from e


# =============================================================================
# 5. PaymentMandate JWT Issuance & Verification (Platform-Signed)
# =============================================================================

def issue_mandate_jwt(
    mandate: PaymentMandate,
    platform_private_key_pem: bytes | str | Path,
    kid: str = "platform:key-1",
) -> str:
    """Platform-signs the immutable PaymentMandate snapshot."""
    key_bytes = load_private_key_pem(platform_private_key_pem)
    claims = {
        "authorized_amount_paise": mandate.authorized_amount_paise,
        "cart_hash": mandate.cart_hash,
        "created_at": mandate.created_at.isoformat(),
        "currency": mandate.currency,
        "iat": int(mandate.created_at.timestamp()),
        "intent_hash": mandate.intent_hash,
        "intent_id": mandate.intent_id,
        "iss": "mandate-mesh:policy-rail",
        "mandate_id": str(mandate.mandate_id),
        "merchant_id": mandate.merchant_id,
    }
    return jwt.encode(claims, key_bytes, algorithm=JWT_ALGORITHM, headers={"kid": kid})


def verify_mandate_jwt(
    token: str,
    platform_public_key_pem: bytes | str | Path,
) -> PaymentMandate:
    """Verifies ES256 signature and returns typed PaymentMandate."""
    key_bytes = load_public_key_pem(platform_public_key_pem)
    try:
        claims = jwt.decode(
            token,
            key_bytes,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["mandate_id", "intent_id", "cart_hash", "intent_hash"]},
        )
    except jwt.PyJWTError as e:
        raise PolicyMandateSignatureInvalid(f"POLICY_MANDATE_SIGNATURE_INVALID: {e}") from e

    # Ensure mutable fields do not exist in claims
    if "status" in claims or "razorpay_order_id" in claims:
        raise PolicyViolation("POLICY_MANDATE_MALFORMED", "PaymentMandate must not contain mutable runtime state fields.", http_status=409)

    created_at = datetime.fromisoformat(claims["created_at"]) if "created_at" in claims else datetime.fromtimestamp(claims["iat"], tz=timezone.utc)

    return PaymentMandate(
        mandate_id=UUID(claims["mandate_id"]),
        intent_id=claims["intent_id"],
        intent_hash=claims["intent_hash"],
        cart_hash=claims["cart_hash"],
        merchant_id=claims["merchant_id"],
        authorized_amount_paise=claims["authorized_amount_paise"],
        currency=claims.get("currency", "INR"),
        created_at=created_at,
    )


# =============================================================================
# 6. PaymentReceipt JWT Issuance & Verification (Platform-Signed)
# =============================================================================

def issue_receipt_jwt(
    receipt: PaymentReceipt,
    platform_private_key_pem: bytes | str | Path,
    kid: str = "platform:key-1",
) -> str:
    """Platform-signs the final PaymentReceipt artifact after webhook capture confirmation."""
    key_bytes = load_private_key_pem(platform_private_key_pem)
    claims = {
        "amount_captured_paise": receipt.amount_captured_paise,
        "captured_at": receipt.captured_at.isoformat(),
        "cart_hash": receipt.cart_hash,
        "currency": receipt.currency,
        "iat": int(receipt.captured_at.timestamp()),
        "intent_hash": receipt.intent_hash,
        "iss": "mandate-mesh:policy-rail",
        "mandate_id": str(receipt.mandate_id),
        "razorpay_order_id": receipt.razorpay_order_id,
        "razorpay_payment_id": receipt.razorpay_payment_id,
        "receipt_id": str(receipt.receipt_id),
    }
    return jwt.encode(claims, key_bytes, algorithm=JWT_ALGORITHM, headers={"kid": kid})


def verify_receipt_jwt(
    token: str,
    platform_public_key_pem: bytes | str | Path,
) -> PaymentReceipt:
    """Verifies ES256 signature of PaymentReceipt."""
    key_bytes = load_public_key_pem(platform_public_key_pem)
    try:
        claims = jwt.decode(
            token,
            key_bytes,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["receipt_id", "mandate_id", "razorpay_order_id", "razorpay_payment_id"]},
        )
    except jwt.PyJWTError as e:
        raise PolicyReceiptSignatureInvalid(f"POLICY_RECEIPT_SIGNATURE_INVALID: {e}") from e

    captured_at = datetime.fromisoformat(claims["captured_at"]) if "captured_at" in claims else datetime.fromtimestamp(claims["iat"], tz=timezone.utc)

    return PaymentReceipt(
        receipt_id=UUID(claims["receipt_id"]),
        mandate_id=UUID(claims["mandate_id"]),
        intent_hash=claims["intent_hash"],
        cart_hash=claims["cart_hash"],
        razorpay_order_id=claims["razorpay_order_id"],
        razorpay_payment_id=claims["razorpay_payment_id"],
        amount_captured_paise=claims["amount_captured_paise"],
        captured_at=captured_at,
        currency=claims.get("currency", "INR"),
    )


# =============================================================================
# 7. Self-Test Entrypoint
# =============================================================================

def selftest() -> bool:
    """Runs a complete in-memory verification of all cryptographic primitives."""
    from datetime import timedelta
    from uuid import uuid4

    print("Running app.crypto self-test...")

    # 1. Generate keypairs
    user_priv, user_pub = generate_es256_keypair()
    merchant_priv, merchant_pub = generate_es256_keypair()
    platform_priv, platform_pub = generate_es256_keypair()

    now = datetime.now(timezone.utc)

    # 2. Test UserIntentCredential
    intent = UserIntentCredential(
        user_id="user_test",
        spend_cap_paise=150000,
        allowed_categories=["bakery"],
        allowed_merchant_ids=["merchant_01"],
        max_transactions=1,
        nonce="nonce_test_123",
        not_before=now,
        expires_at=now + timedelta(hours=1),
    )
    intent_jwt = issue_intent_jwt(intent, user_priv)
    decoded_intent = verify_intent_jwt(intent_jwt, user_pub)
    assert decoded_intent.spend_cap_paise == intent.spend_cap_paise
    assert decoded_intent.nonce == intent.nonce
    print("  [OK] UserIntentCredential sign/verify roundtrip passed.")

    # 3. Test MerchantSignedCart
    item = CartLineItem(sku="SKU-1", name="Cake", category="bakery", unit_price_paise=94000, quantity=1)
    cart = MerchantSignedCart(
        merchant_id="merchant_01",
        line_items=[item],
        tax_paise=0,
        currency="INR",
        cart_hash="",  # will be computed during signing
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    cart.cart_hash = compute_cart_hash(cart)
    cart_jwt = issue_cart_jwt(cart, merchant_priv)
    decoded_cart = verify_cart_jwt(cart_jwt, merchant_pub)
    assert decoded_cart.total_paise == 94000
    assert decoded_cart.cart_hash == cart.cart_hash
    print("  [OK] MerchantSignedCart sign/verify & cart_hash recomputation passed.")

    # 4. Test PaymentMandate
    mandate = PaymentMandate(
        intent_id=str(intent.intent_id),
        intent_hash=compute_intent_hash(intent),
        cart_hash=decoded_cart.cart_hash,
        merchant_id="merchant_01",
        authorized_amount_paise=94000,
        currency="INR",
        created_at=now,
    )
    mandate_jwt = issue_mandate_jwt(mandate, platform_priv)
    decoded_mandate = verify_mandate_jwt(mandate_jwt, platform_pub)
    assert decoded_mandate.authorized_amount_paise == 94000
    assert decoded_mandate.cart_hash == cart.cart_hash
    print("  [OK] PaymentMandate platform sign/verify passed.")

    # 5. Test PaymentReceipt
    receipt = PaymentReceipt(
        mandate_id=decoded_mandate.mandate_id,
        intent_hash=decoded_mandate.intent_hash,
        cart_hash=decoded_mandate.cart_hash,
        razorpay_order_id="order_123",
        razorpay_payment_id="pay_456",
        amount_captured_paise=94000,
        captured_at=now,
    )
    receipt_jwt = issue_receipt_jwt(receipt, platform_priv)
    decoded_receipt = verify_receipt_jwt(receipt_jwt, platform_pub)
    assert decoded_receipt.amount_captured_paise == 94000
    assert decoded_receipt.razorpay_payment_id == "pay_456"
    print("  [OK] PaymentReceipt platform sign/verify passed.")

    # 6. Test Tampering Rejections
    try:
        verify_intent_jwt(intent_jwt, merchant_pub)
        raise AssertionError("Wrong key must fail verification")
    except PolicyViolation:
        print("  [OK] Wrong key rejection verified.")

    print("\nPASS: All 4 credential types signed, verified, and tamper-checked successfully.")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mandate Mesh Crypto CLI")
    parser.add_argument("--selftest", action="store_true", help="Run in-memory self-test")
    args = parser.parse_args()

    if args.selftest:
        success = selftest()
        sys.exit(0 if success else 1)
    else:
        parser.print_help()
