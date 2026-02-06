from urllib.parse import urljoin
from fastapi import APIRouter, Request, Response

from app.settings import settings
from app.schemas.common_responses import DetailResponse
from app.routes import auth, users, generations, variables
from app.routes.drive import api as drive
from app.limiter import limiter


router = APIRouter(prefix="/api")


@router.get("", response_model=dict[str, str], tags=["root"])
@limiter.limit("20/minute")
def info(request: Request, response: Response) -> dict[str, str]:
    return {
        "title": settings.APP_TITLE,
        "version": settings.APP_VERSION,
        "docs_url": urljoin(str(settings.API_URL), "/docs"),
    }


@router.get("/health", response_model=DetailResponse, tags=["root"])
@limiter.limit("20/minute")
def health_check(request: Request, response: Response) -> DetailResponse:
    return DetailResponse(detail="ok")


router.include_router(auth.router)
router.include_router(users.router)
router.include_router(drive.router)
router.include_router(generations.router)
router.include_router(variables.router)
