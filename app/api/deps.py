"""FastAPI dependencies and key management providers."""

from collections.abc import Generator
from pathlib import Path
from sqlalchemy.orm import Session

from app.crypto import generate_es256_keypair, load_private_key_pem, load_public_key_pem
from app.db import get_session
from app.razorpay_client import RazorpayClient

# Key storage directory
KEYS_DIR = Path("keys")

# In-memory ephemeral fallback keys for automated testing
_FALLBACK_KEYS = {
    "user": generate_es256_keypair(),
    "merchant": generate_es256_keypair(),
    "platform": generate_es256_keypair(),
}


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency providing an active database session."""
    session = get_session()
    try:
        yield session
    finally:
        session.close()


def get_user_private_key_pem() -> bytes:
    priv_path = KEYS_DIR / "user_private.pem"
    if priv_path.exists():
        return load_private_key_pem(priv_path)
    return _FALLBACK_KEYS["user"][0]


def get_user_public_key_pem() -> bytes:
    pub_path = KEYS_DIR / "user_public.pem"
    if pub_path.exists():
        return load_public_key_pem(pub_path)
    return _FALLBACK_KEYS["user"][1]


def get_merchant_private_key(merchant_id: str) -> bytes:
    """Resolves merchant private key from MerchantKeyRegistry."""
    from app.merchant_keys import get_merchant_private_key as _get
    return _get(merchant_id)


def get_merchant_public_key(merchant_id: str) -> bytes:
    """Resolves merchant public key from MerchantKeyRegistry."""
    from app.merchant_keys import get_merchant_public_key as _get
    return _get(merchant_id)


def get_merchant_public_key_pem(merchant_id: str = "merchant_cakehouse_01") -> bytes:
    """Legacy backward-compatible getter (defaults to CakeHouse key)."""
    return get_merchant_public_key(merchant_id)


def get_merchant_private_key_pem(merchant_id: str = "merchant_cakehouse_01") -> bytes:
    """Legacy backward-compatible getter (defaults to CakeHouse key)."""
    return get_merchant_private_key(merchant_id)


def get_platform_private_key_pem() -> bytes:
    priv_path = KEYS_DIR / "platform_private.pem"
    if priv_path.exists():
        return load_private_key_pem(priv_path)
    return _FALLBACK_KEYS["platform"][0]


def get_platform_public_key_pem() -> bytes:
    pub_path = KEYS_DIR / "platform_public.pem"
    if pub_path.exists():
        return load_public_key_pem(pub_path)
    return _FALLBACK_KEYS["platform"][1]


def get_razorpay_client() -> RazorpayClient:
    """Returns configured RazorpayClient (defaults to Mock in-memory mode for tests)."""
    return RazorpayClient(mock_mode=True)


def get_webhook_secret() -> str:
    """Returns configured Razorpay webhook secret."""
    return "whsec_test_secret_123"
