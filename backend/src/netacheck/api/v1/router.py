"""
V1 API router — aggregates all v1 sub-routers.

As features are added (politicians, search, PDF, etc.), their routers
are registered here. Each sub-router owns its own prefix and tags.
"""

from __future__ import annotations

from fastapi import APIRouter

from netacheck.api.v1.health import router as health_router

v1_router = APIRouter()

# Health (no prefix — /api/v1/health)
v1_router.include_router(health_router)

# Future routers (added in later phases):
# from netacheck.api.v1.politicians import router as politicians_router
# v1_router.include_router(politicians_router, prefix="/politicians")
#
# from netacheck.api.v1.search import router as search_router
# v1_router.include_router(search_router, prefix="/search")
#
# from netacheck.api.v1.report_card import router as report_card_router
# v1_router.include_router(report_card_router, prefix="/report-card")
#
# from netacheck.api.v1.pdf import router as pdf_router
# v1_router.include_router(pdf_router, prefix="/pdf")
#
# from netacheck.api.v1.corrections import router as corrections_router
# v1_router.include_router(corrections_router, prefix="/corrections")
#
# from netacheck.api.admin import router as admin_router
# v1_router.include_router(admin_router, prefix="/admin")
