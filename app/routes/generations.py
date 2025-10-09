import os
from typing import Any, Dict, Optional, Union
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
)
from beanie import PydanticObjectId, SortDirection
from fastapi.responses import FileResponse, JSONResponse

from app.enums import UserRole
from app.limiter import limiter
from app.models.common_responses import DetailResponse, PaginationMeta
from app.services.google_drive import (
    format_drive_file_metadata,
    get_drive_item_metadata,
)
from app.services.documents import generate_document
from app.models.auth import AuthorizedUser
from app.models.database import Result
from app.models.generations import PaginatedResults
from app.dependencies import get_authorized_user, authorize_user_or_admin_query
from app.utils import validate_document_generation_request, validate_document_mime_type
from app.exceptions import ValidationErrorsException


router = APIRouter(prefix="/generations", tags=["generations"])

common_responses: Dict[Union[int, str], Dict[str, Any]] = {
    404: {
        "description": "Generated document not found",
        "content": {
            "application/json": {"example": {"detail": "Generated document not found"}}
        },
    },
    403: {
        "description": "Forbidden",
        "content": {"application/json": {"example": {"detail": "Forbidden"}}},
    },
    401: {
        "description": "Unauthorized",
        "content": {"application/json": {"example": {"detail": "Invalid token"}}},
    },
}


@router.get(
    "",
    response_model=PaginatedResults,
    responses={401: common_responses[401], 403: common_responses[403]},
)
@limiter.limit("10/minute")
async def get_results_documents(
    request: Request,
    response: Response,
    user_id: Optional[str] = Query(None),
    template_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    authorized_user: AuthorizedUser = Depends(authorize_user_or_admin_query),
) -> PaginatedResults:
    query: Dict[str, Union[str, PydanticObjectId, None]] = {}

    if user_id is None:
        if authorized_user.role == UserRole.USER:
            raise HTTPException(status_code=403, detail="Forbidden")
    else:
        if isinstance(user_id, str) and user_id.lower() == "null":
            if authorized_user.role == UserRole.USER:
                raise HTTPException(status_code=403, detail="Forbidden")

            query["user"] = None

        else:
            if (
                authorized_user.role == UserRole.USER
                and authorized_user.user_id != user_id
            ):
                raise HTTPException(status_code=403, detail="Forbidden")

            try:
                query["user._id"] = PydanticObjectId(user_id)
            except Exception:
                raise HTTPException(
                    status_code=422,
                    detail='User id should be PydanticObjectId or "null"',
                )

    if template_id:
        query["template_id"] = template_id

    total_items = await Result.find(query).count()
    total_pages = max((total_items + page_size - 1) // page_size, 1)
    skip = (page - 1) * page_size

    results = (
        await Result.find(query, fetch_links=True)
        .sort([("_id", SortDirection.DESCENDING)])
        .skip(skip)
        .limit(page_size)
        .to_list()
    )

    meta = PaginationMeta(
        total_items=total_items,
        total_pages=total_pages,
        current_page=page,
        page_size=page_size,
    )

    return PaginatedResults(data=results, meta=meta)


@router.get(
    "/{result_id}",
    response_model=Result,
    responses=common_responses,
)
@limiter.limit("10/minute")
async def get_result_document_by_id(
    result_id: PydanticObjectId,
    request: Request,
    response: Response,
    authorized_user: AuthorizedUser = Depends(get_authorized_user),
) -> Result:
    result = await Result.find_one(Result.id == result_id, fetch_links=True)
    if not result:
        raise HTTPException(status_code=404, detail="Generated document not found")

    user = result.user

    if user:
        if authorized_user.role == UserRole.USER and authorized_user.user_id != user.id:
            raise HTTPException(status_code=403, detail="Forbidden")

    elif authorized_user.role == UserRole.USER:
        raise HTTPException(status_code=403, detail="Forbidden")

    return result


@router.post(
    "/{result_id}/regenerate",
    response_model=Result,
    responses=common_responses,
)
@limiter.limit("5/minute")
async def regenerate_result_by_id(
    result_id: PydanticObjectId,
    background_tasks: BackgroundTasks,
    request: Request,
    response: Response,
    old_constants: bool = Query(False),
    authorized_user: AuthorizedUser = Depends(get_authorized_user),
) -> Union[FileResponse, JSONResponse]:
    result = await Result.find_one(Result.id == result_id, fetch_links=True)
    if not result:
        raise HTTPException(status_code=404, detail="Generated document not found")

    user = result.user

    if user:
        if authorized_user.role == UserRole.USER and authorized_user.user_id != user.id:
            raise HTTPException(status_code=403, detail="Forbidden")

    elif authorized_user.role == UserRole.USER:
        raise HTTPException(status_code=403, detail="Forbidden")

    validate_document_generation_request(result.variables)

    try:
        file_metadata = get_drive_item_metadata(result.template_id)
    except Exception:
        raise HTTPException(
            status_code=404, detail="Template not found or access denied"
        )

    file = format_drive_file_metadata(file_metadata)
    validate_document_mime_type(file.mime_type)

    try:
        pdf_file_path, context = generate_document(
            file, result.variables, not old_constants
        )
    except ValidationErrorsException as e:
        return JSONResponse(status_code=400, content={"errors": e.errors})

    background_tasks.add_task(os.remove, pdf_file_path)

    if file.mime_type == "application/vnd.google-apps.document":
        filename = file.name
    else:
        filename, _ = os.path.splitext(file.name)

    await Result(
        template_id=result.template_id,
        template_name=filename,
        variables=context,
        user=authorized_user.user_id,
    ).insert()

    return FileResponse(
        path=pdf_file_path,
        filename=f"{result.template_id}.pdf",
        media_type="application/pdf",
    )


@router.delete(
    "/{result_id}",
    response_model=DetailResponse,
    responses=common_responses,
)
@limiter.limit("5/minute")
async def delete_result_document_by_id(
    result_id: PydanticObjectId,
    request: Request,
    response: Response,
    authorized_user: AuthorizedUser = Depends(get_authorized_user),
) -> DetailResponse:
    result = await Result.find_one(Result.id == result_id, fetch_links=True)
    if not result:
        raise HTTPException(status_code=404, detail="Generated document not found")

    user = result.user

    if user:
        if (
            (user.role == UserRole.ADMIN or user.role == UserRole.GOD)
            and authorized_user.user_id != user.id
            and authorized_user.role != UserRole.GOD
        ):
            raise HTTPException(status_code=403, detail="Forbidden")

        if authorized_user.role == UserRole.USER and authorized_user.user_id != user.id:
            raise HTTPException(status_code=403, detail="Forbidden")

    elif authorized_user.role == UserRole.USER:
        raise HTTPException(status_code=403, detail="Forbidden")

    await result.delete()

    return DetailResponse(detail="Deleted successfully")
