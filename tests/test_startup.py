"""Unit tests for application startup lifecycle and Alembic schema validation (Correction 1)."""

from unittest.mock import MagicMock, patch
import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.main import validate_schema_head


def test_validate_schema_head_raises_when_revision_mismatch():
    """Production startup must fail-fast when database revision does not match Alembic head."""
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    with patch("alembic.migration.MigrationContext.configure") as mock_mig_ctx:
        mock_ctx_instance = MagicMock()
        mock_ctx_instance.get_current_revision.return_value = "0001_old_revision"
        mock_mig_ctx.return_value = mock_ctx_instance

        with patch("alembic.script.ScriptDirectory.from_config") as mock_script_dir:
            mock_script_instance = MagicMock()
            mock_script_instance.get_current_head.return_value = "0002_merchant_scoped_sku"
            mock_script_dir.return_value = mock_script_instance

            with pytest.raises(RuntimeError) as exc:
                validate_schema_head(test_engine)

            assert "Production startup failed: database revision '0001_old_revision' does not match expected Alembic head '0002_merchant_scoped_sku'" in str(exc.value)


def test_validate_schema_head_passes_when_at_head():
    """Production startup succeeds when database revision matches Alembic head exactly."""
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    with patch("alembic.migration.MigrationContext.configure") as mock_mig_ctx:
        mock_ctx_instance = MagicMock()
        mock_ctx_instance.get_current_revision.return_value = "0002_merchant_scoped_sku"
        mock_mig_ctx.return_value = mock_ctx_instance

        with patch("alembic.script.ScriptDirectory.from_config") as mock_script_dir:
            mock_script_instance = MagicMock()
            mock_script_instance.get_current_head.return_value = "0002_merchant_scoped_sku"
            mock_script_dir.return_value = mock_script_instance

            # Must not raise
            validate_schema_head(test_engine)
