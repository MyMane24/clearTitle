"""
Combine all routers into a single router.
main.py imports this as the single pipeline_router.
"""

from fastapi import APIRouter
from backend.routers.cases import router as cases_router
from backend.routers.documents import router as documents_router
from backend.routers.verification import router as verification_router

router = APIRouter()
router.include_router(cases_router)
router.include_router(documents_router)
router.include_router(verification_router)
