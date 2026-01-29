import os
from typing import Any, cast
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
)
from beanie import Link, PydanticObjectId, SortDirection
from fastapi.responses import FileResponse, JSONResponse

from app.enums import DocumentResponseFormat, UserRole, FORMAT_TO_MIME
from app.limiter import limiter
from app.schemas.common_responses import DetailResponse, PaginationMeta
from app.services.google_drive import (
    format_drive_file_metadata,
    get_drive_item_metadata,
)
from app.services.documents import (
    generate_document,
    validate_document_generation_request,
    validate_document_mime_type,
)
from app.schemas.auth import AuthorizedUser
from app.schemas.documents import GenerateDocumentRequest
from app.models import Result, User
from app.schemas.common_responses import Paginated
from app.dependencies import get_authorized_user, require_admin
from app.exceptions import ValidationErrorsException


router = APIRouter(prefix="/generations", tags=["generations"])

common_responses: dict[int | str, dict[str, Any]] = {
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
    response_model=Paginated[Result],
    responses={401: common_responses[401], 403: common_responses[403]},
)
@limiter.limit("10/minute")
async def get_generations(
    request: Request,
    response: Response,
    user_id: str | None = Query(None),
    template_id: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    authorized_user: AuthorizedUser = Depends(require_admin),
) -> Paginated[Result]:
    query: dict[str, str | PydanticObjectId | None] = {}

    if user_id is None:
        if authorized_user.role == UserRole.USER:
            raise HTTPException(status_code=403, detail="Forbidden")
    else:
        if isinstance(user_id, str) and user_id.lower() == "null":
            if authorized_user.role == UserRole.USER:
                raise HTTPException(status_code=403, detail="Forbidden")

            query["user"] = None

        else:
            try:
                user_id_object = PydanticObjectId(user_id)
            except Exception:
                raise HTTPException(
                    status_code=422,
                    detail='User id should be PydanticObjectId or "null"',
                )

            if (
                authorized_user.role == UserRole.USER
                and authorized_user.user_id != user_id_object
            ):
                raise HTTPException(status_code=403, detail="Forbidden")

            query["user.$id"] = user_id_object

    if template_id:
        query["template_id"] = template_id

    total_items = await Result.find(query).count()
    total_pages = max((total_items + page_size - 1) // page_size, 1)
    skip = (page - 1) * page_size

    user_id_query = query.get("user.$id")
    if user_id_query:
        del query["user.$id"]
        query["user._id"] = user_id_query

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

    return Paginated(data=results, meta=meta)


@router.delete(
    "",
    response_model=DetailResponse,
    responses=common_responses,
)
@limiter.limit("5/minute")
async def delete_user_generated_documents(
    request: Request,
    response: Response,
    user_id: PydanticObjectId = Query(),
    authorized_user: AuthorizedUser = Depends(require_admin),
) -> DetailResponse:
    user = await User.find_one(User.id == user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if (
        user.role == UserRole.ADMIN or user.role == UserRole.GOD
    ) and authorized_user.role != UserRole.GOD:
        raise HTTPException(status_code=403, detail="Forbidden")

    result = await Result.find(Result.user.id == user.id).delete()  # type: ignore[attr-defined]
    if not result:
        raise HTTPException(status_code=404, detail="Generations not found")

    return DetailResponse(detail=f"Deleted: {result.deleted_count}")


@router.get(
    "/{result_id}",
    response_model=Result,
    responses=common_responses,
)
@limiter.limit("10/minute")
async def get_generation_by_id(
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
        if (
            authorized_user.role == UserRole.USER
            and authorized_user.user_id != user.id  # type: ignore[attr-defined]
        ):
            raise HTTPException(status_code=403, detail="Forbidden")

    elif authorized_user.role == UserRole.USER:
        raise HTTPException(status_code=403, detail="Forbidden")

    return result


@router.post(
    "/{result_id}/regenerate",
    response_model=None,
    responses={
        **common_responses,
        200: {
            "description": "Returns regenerated file",
            "content": {
                "application/pdf": {},
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {},
                "application/json": None,
            },
        },
    },
)
@limiter.limit("5/minute")
async def regenerate_by_id(
    result_id: PydanticObjectId,
    body: GenerateDocumentRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    response: Response,
    format: DocumentResponseFormat = Query(DocumentResponseFormat.PDF),
    authorized_user: AuthorizedUser = Depends(get_authorized_user),
) -> FileResponse | JSONResponse:
    result = await Result.find_one(Result.id == result_id, fetch_links=True)
    if not result:
        raise HTTPException(status_code=404, detail="Generated document not found")

    user = result.user

    if user:
        if (
            authorized_user.role == UserRole.USER
            and authorized_user.user_id != user.id  # type: ignore[attr-defined]
        ):
            raise HTTPException(status_code=403, detail="Forbidden")

    elif authorized_user.role == UserRole.USER:
        raise HTTPException(status_code=403, detail="Forbidden")

    # Use provided variables or fall back to original variables
    variables_to_use = body.variables if body.variables else result.variables
    validate_document_generation_request(variables_to_use)

    try:
        file_metadata = get_drive_item_metadata(result.template_id)
    except Exception:
        raise HTTPException(
            status_code=404, detail="Template not found or access denied"
        )

    file = format_drive_file_metadata(file_metadata)
    validate_document_mime_type(file.mime_type)

    user_id = authorized_user.user_id if authorized_user else None

    try:
        file_path, context = await generate_document(
            file, variables_to_use, user_id, body.bypass_validation, format
        )
    except ValidationErrorsException as e:
        return JSONResponse(status_code=400, content={"errors": e.errors})

    background_tasks.add_task(os.remove, file_path)

    if file.mime_type == "application/vnd.google-apps.document":
        filename = file.name
    else:
        filename, _ = os.path.splitext(file.name)

    new_result_data: dict[str, Any] = {
        "template_id": result.template_id,
        "template_name": filename,
        "variables": context,
        "format": format,
    }

    if user:
        new_result_data["user"] = cast(Link[User], authorized_user.user_id)

    await Result(**new_result_data).insert()

    return FileResponse(
        path=file_path,
        filename=f"{result.template_id}.{format.value}",
        media_type=FORMAT_TO_MIME[format],
    )


@router.delete(
    "/{result_id}",
    response_model=DetailResponse,
    responses=common_responses,
)
@limiter.limit("5/minute")
async def delete_generation_by_id(
    result_id: PydanticObjectId,
    request: Request,
    response: Response,
    authorized_user: AuthorizedUser = Depends(require_admin),
) -> DetailResponse:
    result = await Result.find_one(Result.id == result_id, fetch_links=True)
    if not result:
        raise HTTPException(status_code=404, detail="Generated document not found")

    user = cast(User | None, result.user)

    if user:
        if (
            (user.role == UserRole.ADMIN or user.role == UserRole.GOD)
            and authorized_user.user_id != user.id
            and authorized_user.role != UserRole.GOD
        ):
            raise HTTPException(status_code=403, detail="Forbidden")

    await result.delete()

    return DetailResponse(detail="Deleted successfully")
