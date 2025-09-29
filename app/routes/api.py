from typing import Dict
from urllib.parse import urljoin
from fastapi import APIRouter

from app.settings import settings
from app.models.common_responses import DetailResponse
from app.routes import config, documents, folders, telegram, users


router = APIRouter(prefix="/api")


@router.get("", response_model=Dict[str, str], tags=["root"])
def info() -> Dict[str, str]:
    return {
        "title": settings.APP_TITLE,
        "version": settings.APP_VERSION,
        "docs_url": urljoin(str(settings.API_URL), "/docs"),
    }


@router.get("/health", response_model=DetailResponse, tags=["root"])
def health_check() -> DetailResponse:
    return DetailResponse(detail="ok")


router.include_router(telegram.router)
router.include_router(users.router)
router.include_router(folders.router)
router.include_router(documents.router)
router.include_router(config.router)
