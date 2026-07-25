"""
SQLAlchemy ORM model registry.

Every model module must be imported here so that Base.metadata is fully
populated when Alembic autogenerate runs.
"""

from netacheck.models import (  # noqa: F401
    affidavit,
    assets,
    attendance,
    audit,
    correction,
    criminal,
    election,
    geography,
    grading,
    legislative,
    legislature,
    politician,
    source,
)

__all__ = [
    "affidavit",
    "assets",
    "attendance",
    "audit",
    "correction",
    "criminal",
    "election",
    "geography",
    "grading",
    "legislative",
    "legislature",
    "politician",
    "source",
]
