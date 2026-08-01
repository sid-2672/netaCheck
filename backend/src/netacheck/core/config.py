"""
Application configuration via Pydantic Settings.

All values are read from environment variables (or a .env file).
No hardcoded secrets or environment-specific values.

Usage:
    from netacheck.core.config import settings
    print(settings.database_url)
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Central configuration for the NetaCheck backend.

    Values are read from environment variables first, then from a .env file.
    All sensitive values (DB passwords, API keys) must come from environment —
    never committed to source control.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -------------------------------------------------------------------------
    # Application
    # -------------------------------------------------------------------------
    app_name: str = "NetaCheck"
    app_version: str = "0.1.0"
    environment: Literal["development", "staging", "production", "test"] = "development"
    debug: bool = False
    secret_key: str = Field(..., description="Secret key for signing tokens/sessions")

    # -------------------------------------------------------------------------
    # Server
    # -------------------------------------------------------------------------
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1
    reload: bool = False  # only True in development, set via env

    # -------------------------------------------------------------------------
    # Database (PostgreSQL via asyncpg)
    # -------------------------------------------------------------------------
    database_url: PostgresDsn = Field(
        ...,
        description="Async PostgreSQL DSN, e.g. postgresql+asyncpg://user:pass@host/db",
    )
    database_pool_size: int = 10
    database_max_overflow: int = 20
    database_pool_timeout: int = 30
    database_echo: bool = False  # set True to log all SQL in development

    # -------------------------------------------------------------------------
    # Redis (Dramatiq broker + future caching)
    # -------------------------------------------------------------------------
    redis_url: str = "redis://localhost:6379/0"

    # -------------------------------------------------------------------------
    # Storage (Cloudflare R2 / S3-compatible)
    # -------------------------------------------------------------------------
    storage_endpoint_url: str | None = None
    storage_access_key_id: str | None = None
    storage_secret_access_key: str | None = None
    storage_bucket_name: str = "netacheck-pdfs"
    storage_public_url: str | None = None

    @field_validator(
        "storage_public_url",
        "storage_endpoint_url",
        "storage_access_key_id",
        "storage_secret_access_key",
        mode="before",
    )
    @classmethod
    def empty_str_to_none(cls, v: object) -> object:
        """Coerce empty strings to None for optional fields."""
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

    # -------------------------------------------------------------------------
    # Admin authentication (API key strategy for MVP)
    # -------------------------------------------------------------------------
    admin_api_key: str = Field(
        ...,
        description="Static API key for admin endpoints. Use a strong random value.",
    )

    # -------------------------------------------------------------------------
    # Rate limiting
    # -------------------------------------------------------------------------
    rate_limit_requests_per_minute: int = 60
    rate_limit_burst: int = 20

    # -------------------------------------------------------------------------
    # Scraper / ingestion
    # -------------------------------------------------------------------------
    scraper_request_delay_seconds: float = 1.5
    scraper_max_retries: int = 3
    scraper_timeout_seconds: int = 30
    scraper_user_agent: str = (
        "NetaCheckBot/0.1 (+https://netacheck.in/about; civic-transparency-research)"
    )
    scraper_respect_robots_txt: bool = True

    # -------------------------------------------------------------------------
    # PDF generation
    # -------------------------------------------------------------------------
    pdf_generation_timeout_seconds: int = 60
    pdf_cache_ttl_seconds: int = 3600  # 1 hour

    # -------------------------------------------------------------------------
    # Logging
    # -------------------------------------------------------------------------
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_format: Literal["json", "console"] = "json"

    # -------------------------------------------------------------------------
    # CORS
    # -------------------------------------------------------------------------
    cors_allowed_origins: list[str] = ["http://localhost:3000"]

    # -------------------------------------------------------------------------
    # Feature flags
    # -------------------------------------------------------------------------
    feature_pdf_enabled: bool = True
    feature_compare_enabled: bool = True
    feature_corrections_enabled: bool = True

    # -------------------------------------------------------------------------
    # Validators
    # -------------------------------------------------------------------------
    @field_validator("database_url", mode="before")
    @classmethod
    def ensure_asyncpg_scheme(cls, v: str) -> str:
        """Ensure the DSN uses the asyncpg driver prefix."""
        v = str(v)
        if v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        if v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+asyncpg://", 1)
        return v

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def is_development(self) -> bool:
        return self.environment == "development"

    @property
    def is_test(self) -> bool:
        return self.environment == "test"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return the cached application settings singleton.

    Cached so environment variables are read only once per process.
    In tests, call `get_settings.cache_clear()` after patching env vars.
    """
    return Settings()


#: Module-level singleton for convenient import
settings: Settings = get_settings()
