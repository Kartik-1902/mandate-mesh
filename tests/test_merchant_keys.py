"""Unit tests for MerchantKeyRegistry and multi-merchant key management (Milestone M1)."""

import pytest

from app.api.deps import (
    get_merchant_private_key as deps_get_merchant_private_key,
    get_merchant_public_key as deps_get_merchant_public_key,
    get_merchant_private_key_pem,
    get_merchant_public_key_pem,
)
from app.crypto import generate_es256_keypair, verify_cart_jwt
from app.errors import PolicyCartSignatureInvalid
from app.merchant import seed_catalog, sign_cart
from app.key_provider import (
    FilesystemKeyProvider,
    InMemoryTestKeyProvider,
    MerchantKeyProvider,
)
from app.merchant_keys import (
    KNOWN_DEMO_MERCHANTS,
    MerchantKeyNotFound,
    clear_test_merchant_keys,
    get_key_provider,
    get_merchant_kid,
    get_merchant_private_key,
    get_merchant_public_key,
    list_known_merchant_ids,
    register_test_merchant_key,
    set_key_provider,
)


def test_known_demo_merchants_resolve_distinct_keypairs():
    """Each known demo merchant resolves to a valid, distinct ES256 keypair."""
    keys: dict[str, tuple[bytes, bytes]] = {}

    for mid in KNOWN_DEMO_MERCHANTS:
        priv = get_merchant_private_key(mid)
        pub = get_merchant_public_key(mid)

        assert priv.startswith(b"-----BEGIN EC PRIVATE KEY-----") or priv.startswith(b"-----BEGIN PRIVATE KEY-----")
        assert pub.startswith(b"-----BEGIN PUBLIC KEY-----")

        keys[mid] = (priv, pub)

    # Assert all keys are pairwise distinct
    mids = list(KNOWN_DEMO_MERCHANTS)
    assert keys[mids[0]][0] != keys[mids[1]][0]
    assert keys[mids[0]][1] != keys[mids[1]][1]
    assert keys[mids[1]][0] != keys[mids[2]][0]
    assert keys[mids[1]][1] != keys[mids[2]][1]


def test_unknown_merchant_fails_closed():
    """Resolving keys for arbitrary or unregistered merchant IDs raises MerchantKeyNotFound."""
    with pytest.raises(MerchantKeyNotFound) as exc_pub:
        get_merchant_public_key("merchant_evil_corp_99")
    assert exc_pub.value.merchant_id == "merchant_evil_corp_99"

    with pytest.raises(MerchantKeyNotFound) as exc_priv:
        get_merchant_private_key("merchant_evil_corp_99")
    assert exc_priv.value.merchant_id == "merchant_evil_corp_99"

    with pytest.raises(MerchantKeyNotFound):
        get_merchant_public_key("")

    with pytest.raises(MerchantKeyNotFound):
        get_merchant_private_key("")


def test_get_merchant_kid_derivation():
    """get_merchant_kid derives canonical '<merchant_id>:key-1' string."""
    assert get_merchant_kid("merchant_cakehouse_01") == "merchant_cakehouse_01:key-1"
    assert get_merchant_kid("merchant_sweetdelight_02") == "merchant_sweetdelight_02:key-1"
    assert get_merchant_kid("merchant_artisan_03") == "merchant_artisan_03:key-1"


def test_sign_cart_dynamic_kid_derivation(db_session):
    """sign_cart automatically embeds merchant-specific kid when kid is omitted."""
    seed_catalog(db_session, merchant_id="merchant_cakehouse_01")

    priv_cake = get_merchant_private_key("merchant_cakehouse_01")
    cart_model, cart_jwt = sign_cart(
        merchant_id="merchant_cakehouse_01",
        line_items_req=[{"sku": "CAKE-CHOC-001", "quantity": 1}],
        merchant_private_key_pem=priv_cake,
        db=db_session,
    )

    # Verify signature with corresponding CakeHouse public key
    pub_cake = get_merchant_public_key("merchant_cakehouse_01")
    verified = verify_cart_jwt(cart_jwt, pub_cake)
    assert verified.merchant_id == "merchant_cakehouse_01"
    assert verified.total_paise == 94000


def test_wrong_merchant_key_fails_cart_verification(db_session):
    """Cart signed with Merchant A's key cannot be verified with Merchant B's key."""
    seed_catalog(db_session, merchant_id="merchant_cakehouse_01")

    priv_cake = get_merchant_private_key("merchant_cakehouse_01")
    pub_sweet = get_merchant_public_key("merchant_sweetdelight_02")
    pub_cake = get_merchant_public_key("merchant_cakehouse_01")

    _, cart_jwt = sign_cart(
        merchant_id="merchant_cakehouse_01",
        line_items_req=[{"sku": "CAKE-CHOC-001", "quantity": 1}],
        merchant_private_key_pem=priv_cake,
        db=db_session,
    )

    # Verifying with Sweet Delight's key must raise PolicyCartSignatureInvalid
    with pytest.raises(PolicyCartSignatureInvalid):
        verify_cart_jwt(cart_jwt, pub_sweet)

    # Verifying with correct CakeHouse key must succeed
    verified = verify_cart_jwt(cart_jwt, pub_cake)
    assert verified.merchant_id == "merchant_cakehouse_01"


def test_register_test_merchant_key_fixture_hook():
    """register_test_merchant_key allows explicit test-scoped registration for mock merchants."""
    mock_priv, mock_pub = generate_es256_keypair()
    mock_id = "merchant_mock_fixture_01"

    # Ensure clear state
    clear_test_merchant_keys()

    # Initially raises
    with pytest.raises(MerchantKeyNotFound):
        get_merchant_public_key(mock_id)

    # Register mock key
    register_test_merchant_key(mock_id, mock_priv, mock_pub)

    assert get_merchant_private_key(mock_id) == mock_priv
    assert get_merchant_public_key(mock_id) == mock_pub
    assert mock_id in list_known_merchant_ids()

    # Clear and verify it raises again
    clear_test_merchant_keys()
    with pytest.raises(MerchantKeyNotFound):
        get_merchant_public_key(mock_id)


def test_in_memory_test_key_provider_direct_injection():
    """InMemoryTestKeyProvider can be instantiated and passed directly to functions."""
    priv, pub = generate_es256_keypair()
    provider = InMemoryTestKeyProvider(
        initial_keys={"merchant_injected_01": (priv, pub)},
        auto_generate_for_demo=False,
    )

    assert isinstance(provider, MerchantKeyProvider)
    assert provider.get_private_key("merchant_injected_01") == priv
    assert provider.get_public_key("merchant_injected_01") == pub
    assert provider.list_known_merchants() == ["merchant_injected_01"]

    with pytest.raises(MerchantKeyNotFound):
        provider.get_public_key("nonexistent")

    # Injected via provider parameter
    assert get_merchant_public_key("merchant_injected_01", provider=provider) == pub
    assert get_merchant_private_key("merchant_injected_01", provider=provider) == priv


def test_filesystem_key_provider_protocol_conformance():
    """FilesystemKeyProvider satisfies the MerchantKeyProvider protocol."""
    fs_provider = FilesystemKeyProvider()
    assert isinstance(fs_provider, MerchantKeyProvider)
    known = fs_provider.list_known_merchants()
    assert isinstance(known, list)


def test_deps_multi_merchant_and_backward_compatibility_helpers():
    """deps.py provides new multi-merchant getters and backward-compatible flat aliases."""
    clear_test_merchant_keys()
    # New getters
    priv_sweet = deps_get_merchant_private_key("merchant_sweetdelight_02")
    pub_sweet = deps_get_merchant_public_key("merchant_sweetdelight_02")
    assert priv_sweet == get_merchant_private_key("merchant_sweetdelight_02")
    assert pub_sweet == get_merchant_public_key("merchant_sweetdelight_02")

    # Flat legacy getters delegate to CakeHouse
    flat_pub = get_merchant_public_key_pem()
    flat_priv = get_merchant_private_key_pem()
    assert flat_pub == get_merchant_public_key("merchant_cakehouse_01")
    assert flat_priv == get_merchant_private_key("merchant_cakehouse_01")
