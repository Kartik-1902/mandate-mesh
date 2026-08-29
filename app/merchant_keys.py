"""Authoritative Merchant Key Registry for Mandate Mesh (Milestone M1 / ADR-008).

Single source of truth for merchant cryptographic identity.
Resolves trusted ES256 keypairs strictly by merchant_id from filesystem storage
(keys/merchants/<merchant_id>/) or a pre-registered test registry.

Security Invariants:
1. Fail-closed: get_merchant_public_key / get_merchant_private_key immediately raise
   MerchantKeyNotFound for unknown merchant IDs.
2. No arbitrary auto-generation: Keys are never auto-generated at runtime for arbitrary IDs.
3. Untrusted kid isolation: Incoming JWT header 'kid' is never used to select verification keys.
4. ADR-002: Cryptographic operations are delegated to app.crypto; no direct cryptography/jwt imports.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from app.crypto import generate_es256_keypair, load_private_key_pem, load_public_key_pem

KEYS_BASE: Final[Path] = Path("keys")
MERCHANT_KEYS_DIR: Final[Path] = KEYS_BASE / "merchants"

# Hardcoded demo merchants authorized for the Buildathon / demo environment
KNOWN_DEMO_MERCHANTS: Final[set[str]] = {
    "merchant_cakehouse_01",
    "merchant_sweetdelight_02",
    "merchant_artisan_03",
}

# In-memory test registry pre-registered for known demo merchants or explicit test fixtures.
# Arbitrary merchant IDs are NEVER auto-generated at runtime.
_TEST_FALLBACK_KEYS: dict[str, tuple[bytes, bytes]] = {}


class MerchantKeyNotFound(Exception):
    """Raised when no trusted key material exists for the requested merchant_id."""

    def __init__(self, merchant_id: str, message: str | None = None) -> None:
        self.merchant_id = merchant_id
        super().__init__(message or f"No trusted key material registered for merchant_id: '{merchant_id}'")


def _get_or_init_test_fallback(merchant_id: str) -> tuple[bytes, bytes]:
    """Retrieves or lazily initializes fallback keypair ONLY for known demo merchants in test mode."""
    if merchant_id not in KNOWN_DEMO_MERCHANTS:
        raise MerchantKeyNotFound(merchant_id)

    if merchant_id not in _TEST_FALLBACK_KEYS:
        _TEST_FALLBACK_KEYS[merchant_id] = generate_es256_keypair()
    return _TEST_FALLBACK_KEYS[merchant_id]


def get_merchant_private_key(merchant_id: str) -> bytes:
    """Resolves trusted merchant private key from filesystem or explicit test registry.

    Args:
        merchant_id: Unique merchant identifier.

    Returns:
        bytes: The private key PEM bytes.

    Raises:
        MerchantKeyNotFound: If the merchant is unrecognized or untrusted.
    """
    if not merchant_id:
        raise MerchantKeyNotFound(merchant_id, "Merchant ID cannot be empty.")

    # 1. Check explicit test registry override
    if merchant_id in _TEST_FALLBACK_KEYS:
        return _TEST_FALLBACK_KEYS[merchant_id][0]

    # 2. Check keys/merchants/<merchant_id>/private.pem
    disk_path = MERCHANT_KEYS_DIR / merchant_id / "private.pem"
    if disk_path.exists() and disk_path.is_file():
        return load_private_key_pem(disk_path)

    # 2b. Legacy fallback for CakeHouse (keys/merchant_private.pem)
    if merchant_id == "merchant_cakehouse_01":
        legacy_path = KEYS_BASE / "merchant_private.pem"
        if legacy_path.exists() and legacy_path.is_file():
            return load_private_key_pem(legacy_path)

    # 3. Known demo merchant fallback
    if merchant_id in KNOWN_DEMO_MERCHANTS:
        return _get_or_init_test_fallback(merchant_id)[0]

    # 4. Fail closed: unknown merchant ID
    raise MerchantKeyNotFound(merchant_id)


def get_merchant_public_key(merchant_id: str) -> bytes:
    """Resolves trusted merchant public key from filesystem or explicit test registry.

    Args:
        merchant_id: Unique merchant identifier.

    Returns:
        bytes: The public key PEM bytes.

    Raises:
        MerchantKeyNotFound: If the merchant is unrecognized or untrusted.
    """
    if not merchant_id:
        raise MerchantKeyNotFound(merchant_id, "Merchant ID cannot be empty.")

    # 1. Check explicit test registry override
    if merchant_id in _TEST_FALLBACK_KEYS:
        return _TEST_FALLBACK_KEYS[merchant_id][1]

    # 2. Check keys/merchants/<merchant_id>/public.pem
    disk_path = MERCHANT_KEYS_DIR / merchant_id / "public.pem"
    if disk_path.exists() and disk_path.is_file():
        return load_public_key_pem(disk_path)

    # 2b. Legacy fallback for CakeHouse (keys/merchant_public.pem)
    if merchant_id == "merchant_cakehouse_01":
        legacy_path = KEYS_BASE / "merchant_public.pem"
        if legacy_path.exists() and legacy_path.is_file():
            return load_public_key_pem(legacy_path)

    # 3. Known demo merchant fallback
    if merchant_id in KNOWN_DEMO_MERCHANTS:
        return _get_or_init_test_fallback(merchant_id)[1]

    # 4. Fail closed: unknown merchant ID
    raise MerchantKeyNotFound(merchant_id)


def register_test_merchant_key(merchant_id: str, private_pem: bytes, public_pem: bytes) -> None:
    """Explicit test fixture hook for registering mock merchant keys in unit tests."""
    _TEST_FALLBACK_KEYS[merchant_id] = (private_pem, public_pem)


def clear_test_merchant_keys() -> None:
    """Clears all in-memory test fallback keys (useful between test runs)."""
    _TEST_FALLBACK_KEYS.clear()


def get_merchant_kid(merchant_id: str) -> str:
    """Returns canonical key identifier (kid) string for merchant: '<merchant_id>:key-1'."""
    return f"{merchant_id}:key-1"


def list_known_merchant_ids() -> list[str]:
    """Returns all merchant IDs with keys on disk or in the demo registry."""
    found: set[str] = set(KNOWN_DEMO_MERCHANTS)
    found.update(_TEST_FALLBACK_KEYS.keys())

    if MERCHANT_KEYS_DIR.exists() and MERCHANT_KEYS_DIR.is_dir():
        for item in MERCHANT_KEYS_DIR.iterdir():
            if item.is_dir() and (item / "public.pem").exists():
                found.add(item.name)

    return sorted(found)
