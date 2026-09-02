"""Authoritative Merchant Key Registry for Mandate Mesh (Milestone M2 / ADR-008).

Single source of truth for merchant cryptographic identity.
Delegates to the active MerchantKeyProvider (FilesystemKeyProvider by default,
or an injected InMemoryTestKeyProvider in testing environments).

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

from app.key_provider import (
    KEYS_BASE,
    KNOWN_DEMO_MERCHANTS,
    MERCHANT_KEYS_DIR,
    FilesystemKeyProvider,
    InMemoryTestKeyProvider,
    MerchantKeyNotFound,
    MerchantKeyProvider,
    get_merchant_kid,
)

# Active key provider instance (defaults to FilesystemKeyProvider)
_current_provider: MerchantKeyProvider | None = None


def get_key_provider() -> MerchantKeyProvider:
    """Returns the globally active MerchantKeyProvider (defaults to FilesystemKeyProvider)."""
    global _current_provider
    if _current_provider is None:
        _current_provider = FilesystemKeyProvider()
    return _current_provider


def set_key_provider(provider: MerchantKeyProvider | None) -> None:
    """Explicitly sets or resets the active MerchantKeyProvider (used for test fixture injection)."""
    global _current_provider
    _current_provider = provider


def get_merchant_private_key(
    merchant_id: str,
    provider: MerchantKeyProvider | None = None,
) -> bytes:
    """Resolves trusted merchant private key from the active or injected key provider.

    Args:
        merchant_id: Unique merchant identifier.
        provider: Optional explicit provider override.

    Returns:
        bytes: The private key PEM bytes.

    Raises:
        MerchantKeyNotFound: If the merchant is unrecognized or untrusted.
    """
    p = provider or get_key_provider()
    return p.get_private_key(merchant_id)


def get_merchant_public_key(
    merchant_id: str,
    provider: MerchantKeyProvider | None = None,
) -> bytes:
    """Resolves trusted merchant public key from the active or injected key provider.

    Args:
        merchant_id: Unique merchant identifier.
        provider: Optional explicit provider override.

    Returns:
        bytes: The public key PEM bytes.

    Raises:
        MerchantKeyNotFound: If the merchant is unrecognized or untrusted.
    """
    p = provider or get_key_provider()
    return p.get_public_key(merchant_id)


def register_test_merchant_key(merchant_id: str, private_pem: bytes, public_pem: bytes) -> None:
    """Explicit test fixture hook for registering mock merchant keys in unit tests."""
    p = get_key_provider()
    if isinstance(p, InMemoryTestKeyProvider):
        p.register_key(merchant_id, private_pem, public_pem)
    else:
        test_provider = InMemoryTestKeyProvider()
        test_provider.register_key(merchant_id, private_pem, public_pem)
        set_key_provider(test_provider)


def clear_test_merchant_keys() -> None:
    """Clears test keys and restores default provider."""
    p = get_key_provider()
    if isinstance(p, InMemoryTestKeyProvider):
        p.clear()
    set_key_provider(None)


def list_known_merchant_ids(provider: MerchantKeyProvider | None = None) -> list[str]:
    """Returns all merchant IDs known to the active or injected provider."""
    p = provider or get_key_provider()
    return p.list_known_merchants()
