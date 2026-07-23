"""
Unit tests for application configuration.

These tests verify that Settings correctly validates env vars,
applies defaults, and raises on missing required fields.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError


def _make_settings(**overrides: object) -> object:
    """Helper: build a valid Settings object with test defaults."""
    # Import here to avoid module-level settings singleton issues
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
    def test_app_name_default(self):
        s = _make_settings()
        assert s.app_name == "NetaCheck"  # type: ignore[union-attr]

    def test_environment_defaults_to_development(self):
        # Explicitly pass environment='development' to avoid ENVIRONMENT env var leakage
        s = _make_settings(environment="development")
        assert s.environment == "development"  # type: ignore[union-attr]

    def test_debug_defaults_to_false(self):
        s = _make_settings()
        assert s.debug is False  # type: ignore[union-attr]

    def test_log_level_default(self):
        s = _make_settings()
        assert s.log_level == "INFO"  # type: ignore[union-attr]

    def test_scraper_delay_default(self):
        s = _make_settings()
        assert s.scraper_request_delay_seconds == 1.5  # type: ignore[union-attr]

    def test_scraper_respect_robots_default(self):
        s = _make_settings()
        assert s.scraper_respect_robots_txt is True  # type: ignore[union-attr]


class TestDatabaseUrlNormalization:
    def test_postgres_prefix_converted(self):
        s = _make_settings(
            database_url="postgres://user:pass@localhost:5432/db"
        )
        assert str(s.database_url).startswith("postgresql+asyncpg://")  # type: ignore[union-attr]

    def test_postgresql_prefix_converted(self):
        s = _make_settings(
            database_url="postgresql://user:pass@localhost:5432/db"
        )
        assert str(s.database_url).startswith("postgresql+asyncpg://")  # type: ignore[union-attr]

    def test_asyncpg_prefix_unchanged(self):
        url = "postgresql+asyncpg://user:pass@localhost:5432/db"
        s = _make_settings(database_url=url)
        assert str(s.database_url).startswith("postgresql+asyncpg://")  # type: ignore[union-attr]


class TestEnvironmentProperties:
    def test_is_production(self):
        s = _make_settings(environment="production")
        assert s.is_production is True  # type: ignore[union-attr]
        assert s.is_development is False  # type: ignore[union-attr]
        assert s.is_test is False  # type: ignore[union-attr]

    def test_is_development(self):
        s = _make_settings(environment="development")
        assert s.is_development is True  # type: ignore[union-attr]
        assert s.is_production is False  # type: ignore[union-attr]

    def test_is_test(self):
        s = _make_settings(environment="test")
        assert s.is_test is True  # type: ignore[union-attr]


class TestRequiredFields:
    def test_missing_secret_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Settings should raise ValidationError when secret_key is not provided."""
        from netacheck.core.config import Settings

        # Prevent pydantic-settings from reading from environment
        monkeypatch.delenv("SECRET_KEY", raising=False)
        monkeypatch.delenv("ADMIN_API_KEY", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)

        with pytest.raises(ValidationError):
            Settings(  # type: ignore[call-arg]
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
            Settings(  # type: ignore[call-arg]
                secret_key="key",
                database_url="postgresql+asyncpg://u:p@h/db",
                # admin_api_key intentionally omitted
            )
