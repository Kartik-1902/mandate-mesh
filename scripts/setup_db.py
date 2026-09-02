"""Explicit database setup & migration script for local development and CI.

Usage:
    python scripts/setup_db.py
"""

from pathlib import Path
from alembic import command
from alembic.config import Config


def run_setup() -> None:
    """Executes Alembic migrations up to head."""
    root_dir = Path(__file__).resolve().parent.parent
    ini_path = root_dir / "alembic.ini"
    if not ini_path.exists():
        raise FileNotFoundError(f"Could not find alembic.ini at {ini_path}")

    cfg = Config(str(ini_path))
    print(f"Applying Alembic migrations from {ini_path}...")
    command.upgrade(cfg, "head")
    print("Database schema is now at the latest Alembic head revision.")


if __name__ == "__main__":
    run_setup()
