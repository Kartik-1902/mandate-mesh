"""Keypair generation script for Mandate Mesh (User, Merchant, Platform ES256 keys)."""

import os
from pathlib import Path
from app.crypto import generate_es256_keypair


def generate_all_keys(keys_dir: Path = Path("keys")) -> None:
    """Generates three distinct ES256 keypairs and writes them to keys_dir."""
    keys_dir.mkdir(parents=True, exist_ok=True)

    actors = ["user", "merchant", "platform"]

    print(f"Generating ES256 keypairs in '{keys_dir.resolve()}'...")
    for actor in actors:
        priv_path = keys_dir / f"{actor}_private.pem"
        pub_path = keys_dir / f"{actor}_public.pem"

        priv_pem, pub_pem = generate_es256_keypair()

        priv_path.write_bytes(priv_pem)
        pub_path.write_bytes(pub_pem)

        print(f"  [OK] {actor.capitalize()} keypair created:")
        print(f"       Private: {priv_path.name}")
        print(f"       Public:  {pub_path.name}")

    gitkeep = keys_dir / ".gitkeep"
    if not gitkeep.exists():
        gitkeep.touch()

    print("\nAll keypairs generated successfully.")


if __name__ == "__main__":
    generate_all_keys()
