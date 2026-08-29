"""Multi-Merchant Keypair Generation Script for Mandate Mesh (Milestone M1).

Generates independent ES256 keypairs for:
- User (`keys/user_private.pem`, `keys/user_public.pem`)
- Platform (`keys/platform_private.pem`, `keys/platform_public.pem`)
- Demo Merchants:
  - CakeHouse 01: `keys/merchants/merchant_cakehouse_01/{private,public}.pem`
  - Sweet Delight 02: `keys/merchants/merchant_sweetdelight_02/{private,public}.pem`
  - Artisan Bakes 03: `keys/merchants/merchant_artisan_03/{private,public}.pem`
- Legacy flat merchant keys (`keys/merchant_private.pem`, `keys/merchant_public.pem`)
  mirrored from merchant_cakehouse_01 for backward compatibility.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Sequence

from app.crypto import generate_es256_keypair
from app.merchant_keys import KNOWN_DEMO_MERCHANTS, MERCHANT_KEYS_DIR


def generate_all_merchant_keys(
    keys_base: Path = Path("keys"),
    merchant_ids: Sequence[str] | None = None,
    force: bool = False,
) -> None:
    """Generates all required actor and merchant keypairs."""
    keys_base.mkdir(parents=True, exist_ok=True)
    target_merchants = list(merchant_ids or sorted(KNOWN_DEMO_MERCHANTS))

    print(f"[*] Initializing cryptographic key hierarchy in '{keys_base.resolve()}'...\n")

    # 1. Base actors (User & Platform)
    for actor in ["user", "platform"]:
        priv_p = keys_base / f"{actor}_private.pem"
        pub_p = keys_base / f"{actor}_public.pem"

        if force or not priv_p.exists() or not pub_p.exists():
            priv_b, pub_b = generate_es256_keypair()
            priv_p.write_bytes(priv_b)
            pub_p.write_bytes(pub_b)
            print(f"  [OK] Generated {actor.capitalize()} keypair: {priv_p.name}, {pub_p.name}")
        else:
            print(f"  [-] Existing {actor.capitalize()} keypair preserved: {priv_p.name}")

    # 2. Multi-merchant hierarchy: keys/merchants/<merchant_id>/
    merchants_dir = keys_base / "merchants"
    merchants_dir.mkdir(parents=True, exist_ok=True)

    for mid in target_merchants:
        m_dir = merchants_dir / mid
        m_dir.mkdir(parents=True, exist_ok=True)

        priv_p = m_dir / "private.pem"
        pub_p = m_dir / "public.pem"

        if force or not priv_p.exists() or not pub_p.exists():
            priv_b, pub_b = generate_es256_keypair()
            priv_p.write_bytes(priv_b)
            pub_p.write_bytes(pub_b)
            print(f"  [OK] Generated Merchant '{mid}' keypair in {m_dir.relative_to(keys_base)}")
        else:
            print(f"  [-] Existing Merchant '{mid}' keypair preserved in {m_dir.relative_to(keys_base)}")

    # 3. Legacy flat merchant keys (mirrors merchant_cakehouse_01)
    cakehouse_priv = merchants_dir / "merchant_cakehouse_01" / "private.pem"
    cakehouse_pub = merchants_dir / "merchant_cakehouse_01" / "public.pem"
    flat_priv = keys_base / "merchant_private.pem"
    flat_pub = keys_base / "merchant_public.pem"

    if cakehouse_priv.exists() and cakehouse_pub.exists():
        if force or not flat_priv.exists() or not flat_pub.exists():
            shutil.copyfile(cakehouse_priv, flat_priv)
            shutil.copyfile(cakehouse_pub, flat_pub)
            print(f"  [OK] Mirrored CakeHouse keys to legacy flat files: {flat_priv.name}, {flat_pub.name}")

    # Ensure .gitkeep
    gitkeep = keys_base / ".gitkeep"
    if not gitkeep.exists():
        gitkeep.touch()

    print("\n[+] Multi-merchant key generation completed successfully.")


if __name__ == "__main__":
    generate_all_merchant_keys()
