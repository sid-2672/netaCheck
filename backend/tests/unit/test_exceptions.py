"""
Unit tests for domain exceptions.

Verifies that exceptions carry the correct detail messages,
context dictionaries, and inheritance hierarchy.
"""

from __future__ import annotations

from netacheck.core.exceptions import (
    AuthorizationError,
    DataConflictError,
    DuplicateSnapshotError,
    GradingError,
    IngestionError,
    InsufficientDataError,
    InvalidApiKeyError,
    NetaCheckError,
    NotFoundError,
    ParseError,
    PdfGenerationError,
    PoliticianNotFoundError,
    RobotsDisallowedError,
    ScraperBlockedError,
    SourceMissingError,
    StateNotFoundError,
)


class TestExceptionHierarchy:
    def test_politician_not_found_is_not_found(self) -> None:
        exc = PoliticianNotFoundError(slug="narendra-modi")
        assert isinstance(exc, NotFoundError)
        assert isinstance(exc, NetaCheckError)

    def test_source_missing_is_netacheck_error(self) -> None:
        exc = SourceMissingError(field="criminal_cases")
        assert isinstance(exc, NetaCheckError)

    def test_scraper_blocked_is_ingestion_error(self) -> None:
        exc = ScraperBlockedError(url="https://example.com", status_code=429)
        assert isinstance(exc, IngestionError)
        assert isinstance(exc, NetaCheckError)

    def test_insufficient_data_is_grading_error(self) -> None:
        exc = InsufficientDataError(metric="attendance", politician_slug="test-mp")
        assert isinstance(exc, GradingError)
        assert isinstance(exc, NetaCheckError)

    def test_invalid_api_key_is_authorization_error(self) -> None:
        exc = InvalidApiKeyError()
        assert isinstance(exc, AuthorizationError)
        assert isinstance(exc, NetaCheckError)


class TestExceptionMessages:
    def test_politician_not_found_message_contains_slug(self) -> None:
        exc = PoliticianNotFoundError(slug="narendra-modi")
        assert "narendra-modi" in exc.detail
        assert exc.context["slug"] == "narendra-modi"

    def test_source_missing_message_contains_field(self) -> None:
        exc = SourceMissingError(field="criminal_cases", politician_slug="test-mp")
        assert "criminal_cases" in exc.detail
        assert exc.context["field"] == "criminal_cases"
        assert exc.context["politician_slug"] == "test-mp"

    def test_source_missing_without_politician_slug(self) -> None:
        exc = SourceMissingError(field="assets")
        assert "assets" in exc.detail
        assert exc.context["politician_slug"] is None

    def test_scraper_blocked_carries_status_code(self) -> None:
        exc = ScraperBlockedError(url="https://example.com", status_code=403)
        assert exc.context["status_code"] == 403
        assert exc.context["url"] == "https://example.com"

    def test_data_conflict_carries_both_sources(self) -> None:
        exc = DataConflictError(
            field="assets_value",
            source_a="adr_2024",
            source_b="eci_2024",
        )
        assert exc.context["source_a"] == "adr_2024"
        assert exc.context["source_b"] == "eci_2024"

    def test_robots_disallowed_message_contains_url(self) -> None:
        url = "https://myneta.info/private/page"
        exc = RobotsDisallowedError(url=url)
        assert url in exc.detail

    def test_parse_error_carries_source_and_reason(self) -> None:
        exc = ParseError(source="adr_html", reason="missing table")
        assert exc.context["source"] == "adr_html"
        assert exc.context["reason"] == "missing table"

    def test_pdf_error_carries_slug_and_reason(self) -> None:
        exc = PdfGenerationError(politician_slug="test-mp", reason="timeout")
        assert exc.context["politician_slug"] == "test-mp"
        assert exc.context["reason"] == "timeout"

    def test_state_not_found(self) -> None:
        exc = StateNotFoundError(slug="maharashtra")
        assert "maharashtra" in exc.detail

    def test_duplicate_snapshot_carries_hash(self) -> None:
        exc = DuplicateSnapshotError(url="https://ex.com", content_hash="abc123")
        assert exc.context["content_hash"] == "abc123"

    def test_insufficient_data_carries_metric(self) -> None:
        exc = InsufficientDataError(metric="attendance", politician_slug="test-slug")
        assert exc.context["metric"] == "attendance"
        assert exc.context["politician_slug"] == "test-slug"

    def test_invalid_api_key_detail_message(self) -> None:
        exc = InvalidApiKeyError()
        assert "API key" in exc.detail


class TestExceptionRepr:
    def test_repr_includes_class_name(self) -> None:
        exc = PoliticianNotFoundError(slug="test-slug")
        r = repr(exc)
        assert "PoliticianNotFoundError" in r
        assert "test-slug" in r

    def test_netacheck_error_str_is_detail(self) -> None:
        exc = NetaCheckError("something went wrong", key="value")
        assert str(exc) == "something went wrong"
