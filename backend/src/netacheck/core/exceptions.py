"""
Domain exception hierarchy.

Design philosophy:
- All domain errors inherit from `NetaCheckError` so callers can catch
  the entire hierarchy with a single except clause if needed.
- HTTP-specific exceptions live in the API layer, not here.
- Exception names describe *what went wrong*, not *where*.
- Exceptions carry `detail` (human-readable) and optionally `context`
  (machine-readable key-value pairs for logging).

Usage:
    raise PoliticianNotFoundError(slug="narendra-modi")
    raise SourceMissingError(field="criminal_cases", politician_slug="abc")
"""

from __future__ import annotations

from typing import Any


class NetaCheckError(Exception):
    """Base exception for all NetaCheck domain errors."""

    def __init__(self, detail: str, **context: Any) -> None:
        super().__init__(detail)
        self.detail = detail
        self.context: dict[str, Any] = context

    def __repr__(self) -> str:
        ctx = ", ".join(f"{k}={v!r}" for k, v in self.context.items())
        return f"{self.__class__.__name__}({self.detail!r}{', ' + ctx if ctx else ''})"


# ---------------------------------------------------------------------------
# Not Found
# ---------------------------------------------------------------------------


class NotFoundError(NetaCheckError):
    """A requested resource does not exist."""


class PoliticianNotFoundError(NotFoundError):
    def __init__(self, slug: str) -> None:
        super().__init__(f"Politician with slug '{slug}' not found.", slug=slug)


class PartyNotFoundError(NotFoundError):
    def __init__(self, slug: str) -> None:
        super().__init__(f"Party with slug '{slug}' not found.", slug=slug)


class StateNotFoundError(NotFoundError):
    def __init__(self, slug: str) -> None:
        super().__init__(f"State with slug '{slug}' not found.", slug=slug)


class SourceNotFoundError(NotFoundError):
    def __init__(self, source_id: str) -> None:
        super().__init__(f"Source snapshot '{source_id}' not found.", source_id=source_id)


class CorrectionNotFoundError(NotFoundError):
    def __init__(self, correction_id: str) -> None:
        super().__init__(
            f"Correction request '{correction_id}' not found.",
            correction_id=correction_id,
        )


# ---------------------------------------------------------------------------
# Source / Data integrity
# ---------------------------------------------------------------------------


class SourceMissingError(NetaCheckError):
    """
    Raised when code attempts to render or return data that has no source.

    This is the central enforcement mechanism for the platform's hard constraint:
    every displayed fact must have a traceable source.
    """

    def __init__(self, field: str, politician_slug: str | None = None) -> None:
        ctx = f" for politician '{politician_slug}'" if politician_slug else ""
        super().__init__(
            f"Field '{field}'{ctx} has no source reference. "
            "Data without sources cannot be displayed.",
            field=field,
            politician_slug=politician_slug,
        )


class DataConflictError(NetaCheckError):
    """Two authoritative sources disagree on the same fact."""

    def __init__(self, field: str, source_a: str, source_b: str, **ctx: Any) -> None:
        super().__init__(
            f"Conflicting values for '{field}' between sources " f"'{source_a}' and '{source_b}'.",
            field=field,
            source_a=source_a,
            source_b=source_b,
            **ctx,
        )


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------


class IngestionError(NetaCheckError):
    """Base for all scraper/ingestion failures."""


class ScraperBlockedError(IngestionError):
    """The target site blocked or rate-limited the scraper."""

    def __init__(self, url: str, status_code: int) -> None:
        super().__init__(
            f"Scraper blocked at '{url}' with HTTP {status_code}.",
            url=url,
            status_code=status_code,
        )


class RobotsDisallowedError(IngestionError):
    """robots.txt prohibits fetching this URL."""

    def __init__(self, url: str) -> None:
        super().__init__(
            f"robots.txt disallows fetching '{url}'.",
            url=url,
        )


class ParseError(IngestionError):
    """Parser could not extract expected structure from a document."""

    def __init__(self, source: str, reason: str, **ctx: Any) -> None:
        super().__init__(
            f"Failed to parse '{source}': {reason}",
            source=source,
            reason=reason,
            **ctx,
        )


class DuplicateSnapshotError(IngestionError):
    """An identical snapshot (same URL + content hash) already exists."""

    def __init__(self, url: str, content_hash: str) -> None:
        super().__init__(
            f"Snapshot already exists for '{url}' with hash '{content_hash}'.",
            url=url,
            content_hash=content_hash,
        )


# ---------------------------------------------------------------------------
# Grading
# ---------------------------------------------------------------------------


class GradingError(NetaCheckError):
    """Base for grading engine failures."""


class InsufficientDataError(GradingError):
    """Not enough sourced data to compute a meaningful grade."""

    def __init__(self, metric: str, politician_slug: str) -> None:
        super().__init__(
            f"Insufficient sourced data to grade '{metric}' "
            f"for politician '{politician_slug}'.",
            metric=metric,
            politician_slug=politician_slug,
        )


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


class AuthorizationError(NetaCheckError):
    """Caller lacks permission to perform the requested action."""

    def __init__(self, action: str) -> None:
        super().__init__(f"Not authorized to perform '{action}'.", action=action)


class InvalidApiKeyError(AuthorizationError):
    def __init__(self) -> None:
        super().__init__(action="admin access")
        self.detail = "Invalid or missing admin API key."


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


class PdfGenerationError(NetaCheckError):
    """PDF could not be generated."""

    def __init__(self, politician_slug: str, reason: str) -> None:
        super().__init__(
            f"PDF generation failed for '{politician_slug}': {reason}",
            politician_slug=politician_slug,
            reason=reason,
        )
