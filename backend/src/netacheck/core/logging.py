"""
Structured logging with structlog.

Design decisions:
- JSON output in production (machine-parseable for log aggregators).
- Console (human-friendly) output in development.
- Every log entry carries `environment` and `app_version` automatically.
- No print() statements anywhere in the codebase — use `get_logger()`.

Usage:
    from netacheck.core.logging import get_logger
    log = get_logger(__name__)
    log.info("politician_fetched", slug="narendra-modi", source="adr")
"""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING, cast

import structlog

from netacheck.core.config import settings

if TYPE_CHECKING:
    from structlog.types import EventDict, Processor


def _add_app_context(logger: object, method: str, event_dict: EventDict) -> EventDict:
    """Inject application-level context into every log entry."""
    event_dict["app"] = settings.app_name
    event_dict["version"] = settings.app_version
    event_dict["env"] = settings.environment
    return event_dict


def _drop_color_message_key(logger: object, method: str, event_dict: EventDict) -> EventDict:
    """Remove Uvicorn's internal `color_message` key from access logs."""
    event_dict.pop("color_message", None)
    return event_dict


def configure_logging() -> None:
    """
    Configure structlog and the stdlib `logging` root logger.

    Must be called once at application startup (in `main.py` lifespan).
    Safe to call multiple times — subsequent calls are no-ops.
    """
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _add_app_context,
        _drop_color_message_key,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
    ]

    if settings.log_format == "json":
        renderer: Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(settings.log_level)

    # Quiet noisy libraries in production
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.database_echo else logging.WARNING
    )


def get_logger(name: str) -> structlog.BoundLogger:
    """
    Return a bound structlog logger for the given module name.

    Intended to be called at module level:
        log = get_logger(__name__)
    """
    return cast("structlog.BoundLogger", structlog.get_logger(name))
