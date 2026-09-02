"""Authoritative Merchant Key Provider Interface and Implementations (Milestone M2).

Defines the MerchantKeyProvider protocol and standard implementations:
- MerchantKeyProvider: Structural protocol defining the key resolution interface.
- FilesystemKeyProvider: Resolves keys from filesystem storage (production / staging / local).
- InMemoryTestKeyProvider: Explicitly injected in-memory key provider for unit & integration tests.
- Future KMS / HSM key providers will implement MerchantKeyProvider behind this abstraction boundary.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final, Protocol, runtime_checkable

from app.crypto import generate_es256_keypair, load_private_key_pem, load_public_key_pem

KEYS_BASE: Final[Path] = Path("keys")
MERCHANT_KEYS_DIR: Final[Path] = KEYS_BASE / "merchants"

KNOWN_DEMO_MERCHANTS: Final[set[str]] = {
    "merchant_cakehouse_01",
    "merchant_sweetdelight_02",
    "merchant_artisan_03",
}


class MerchantKeyNotFound(Exception):
    """Raised when no trusted key material exists for the requested merchant_id."""

    def __init__(self, merchant_id: str, message: str | None = None) -> None:
        self.merchant_id = merchant_id
        super().__init__(message or f"No trusted key material registered for merchant_id: '{merchant_id}'")


def get_merchant_kid(merchant_id: str) -> str:
    """Returns canonical key identifier (kid) string for merchant: '<merchant_id>:key-1'."""
    return f"{merchant_id}:key-1"


@runtime_checkable
class MerchantKeyProvider(Protocol):
    """Protocol for resolving merchant cryptographic key material."""

    def get_private_key(self, merchant_id: str) -> bytes:
        """Resolves private key PEM bytes for merchant_id. Raises MerchantKeyNotFound if missing."""
        ...

    def get_public_key(self, merchant_id: str) -> bytes:
        """Resolves public key PEM bytes for merchant_id. Raises MerchantKeyNotFound if missing."""
        ...

    def list_known_merchants(self) -> list[str]:
        """Lists all known merchant IDs."""
        ...


class FilesystemKeyProvider:
    """Key provider that resolves keys from filesystem storage."""

    def __init__(self, base_dir: Path | str = MERCHANT_KEYS_DIR) -> None:
        self.base_dir = Path(base_dir)

    def get_private_key(self, merchant_id: str) -> bytes:
        if not merchant_id:
            raise MerchantKeyNotFound(merchant_id, "Merchant ID cannot be empty.")

        disk_path = self.base_dir / merchant_id / "private.pem"
        if disk_path.exists() and disk_path.is_file():
            return load_private_key_pem(disk_path)

        # Legacy fallback for CakeHouse (keys/merchant_private.pem)
        if merchant_id == "merchant_cakehouse_01":
            legacy_path = self.base_dir.parent / "merchant_private.pem"
            if legacy_path.exists() and legacy_path.is_file():
                return load_private_key_pem(legacy_path)

        raise MerchantKeyNotFound(merchant_id)

    def get_public_key(self, merchant_id: str) -> bytes:
        if not merchant_id:
            raise MerchantKeyNotFound(merchant_id, "Merchant ID cannot be empty.")

        disk_path = self.base_dir / merchant_id / "public.pem"
        if disk_path.exists() and disk_path.is_file():
            return load_public_key_pem(disk_path)

        # Legacy fallback for CakeHouse (keys/merchant_public.pem)
        if merchant_id == "merchant_cakehouse_01":
            legacy_path = self.base_dir.parent / "merchant_public.pem"
            if legacy_path.exists() and legacy_path.is_file():
                return load_public_key_pem(legacy_path)

        raise MerchantKeyNotFound(merchant_id)

    def list_known_merchants(self) -> list[str]:
        found: set[str] = set()
        if self.base_dir.exists() and self.base_dir.is_dir():
            for item in self.base_dir.iterdir():
                if item.is_dir() and (item / "public.pem").exists():
                    found.add(item.name)
        return sorted(found)


class InMemoryTestKeyProvider:
    """Explicitly injected in-memory key provider for unit and integration tests."""

    def __init__(
        self,
        initial_keys: dict[str, tuple[bytes, bytes]] | None = None,
        auto_generate_for_demo: bool = True,
    ) -> None:
        self._keys: dict[str, tuple[bytes, bytes]] = dict(initial_keys or {})
        if auto_generate_for_demo:
            for mid in KNOWN_DEMO_MERCHANTS:
                if mid not in self._keys:
                    self._keys[mid] = generate_es256_keypair()

    def register_key(self, merchant_id: str, private_pem: bytes, public_pem: bytes) -> None:
        """Explicitly registers mock merchant keys."""
        self._keys[merchant_id] = (private_pem, public_pem)

    def clear(self) -> None:
        """Clears all in-memory keys."""
        self._keys.clear()

    def get_private_key(self, merchant_id: str) -> bytes:
        if not merchant_id:
            raise MerchantKeyNotFound(merchant_id, "Merchant ID cannot be empty.")
        if merchant_id in self._keys:
            return self._keys[merchant_id][0]
        raise MerchantKeyNotFound(merchant_id)

    def get_public_key(self, merchant_id: str) -> bytes:
        if not merchant_id:
            raise MerchantKeyNotFound(merchant_id, "Merchant ID cannot be empty.")
        if merchant_id in self._keys:
            return self._keys[merchant_id][1]
        raise MerchantKeyNotFound(merchant_id)

    def list_known_merchants(self) -> list[str]:
        return sorted(self._keys.keys())
