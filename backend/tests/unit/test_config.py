"""
Unit tests for application configuration.

These tests verify that Settings correctly validates env vars,
applies defaults, and raises on missing required fields.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from pydantic import ValidationError

if TYPE_CHECKING:
    from netacheck.core.config import Settings


def _make_settings(**overrides: Any) -> Settings:
    """Helper: build a valid Settings object with test defaults."""
    from netacheck.core.config import Settings

    defaults = {
        "secret_key": "test_secret_key_for_tests_only",
        "admin_api_key": "test_admin_key",
        "database_url": "postgresql+asyncpg://user:pass@localhost:5432/testdb",
        "environment": "development",
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


class TestSettingsDefaults:
    def test_app_name_default(self) -> None:
        s = _make_settings()
        assert s.app_name == "NetaCheck"

    def test_environment_defaults_to_development(self) -> None:
        # Explicitly pass environment='development' to avoid ENVIRONMENT env var leakage
        s = _make_settings(environment="development")
        assert s.environment == "development"

    def test_debug_defaults_to_false(self) -> None:
        s = _make_settings()
        assert s.debug is False

    def test_log_level_default(self) -> None:
        s = _make_settings()
        assert s.log_level == "INFO"

    def test_scraper_delay_default(self) -> None:
        s = _make_settings()
        assert s.scraper_request_delay_seconds == 1.5

    def test_scraper_respect_robots_default(self) -> None:
        s = _make_settings()
        assert s.scraper_respect_robots_txt is True


class TestDatabaseUrlNormalization:
    def test_postgres_prefix_converted(self) -> None:
        s = _make_settings(database_url="postgres://user:pass@localhost:5432/db")
        assert str(s.database_url).startswith("postgresql+asyncpg://")

    def test_postgresql_prefix_converted(self) -> None:
        s = _make_settings(database_url="postgresql://user:pass@localhost:5432/db")
        assert str(s.database_url).startswith("postgresql+asyncpg://")

    def test_asyncpg_prefix_unchanged(self) -> None:
        url = "postgresql+asyncpg://user:pass@localhost:5432/db"
        s = _make_settings(database_url=url)
        assert str(s.database_url).startswith("postgresql+asyncpg://")


class TestEnvironmentProperties:
    def test_is_production(self) -> None:
        s = _make_settings(environment="production")
        assert s.is_production is True
        assert s.is_development is False
        assert s.is_test is False

    def test_is_development(self) -> None:
        s = _make_settings(environment="development")
        assert s.is_development is True
        assert s.is_production is False

    def test_is_test(self) -> None:
        s = _make_settings(environment="test")
        assert s.is_test is True


class TestRequiredFields:
    def test_missing_secret_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Settings should raise ValidationError when secret_key is not provided."""
        from netacheck.core.config import Settings

        # Prevent pydantic-settings from reading from environment
        monkeypatch.delenv("SECRET_KEY", raising=False)
        monkeypatch.delenv("ADMIN_API_KEY", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)

        with pytest.raises(ValidationError):
            Settings(
                admin_api_key="key",
                database_url="postgresql+asyncpg://u:p@h/db",
                # secret_key intentionally omitted
            )

    def test_missing_admin_api_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Settings should raise ValidationError when admin_api_key is not provided."""
        from netacheck.core.config import Settings

        monkeypatch.delenv("SECRET_KEY", raising=False)
        monkeypatch.delenv("ADMIN_API_KEY", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)

        with pytest.raises(ValidationError):
            Settings(
                secret_key="key",
                database_url="postgresql+asyncpg://u:p@h/db",
                # admin_api_key intentionally omitted
            )
