from typing import Any, cast
from io import BytesIO
import os
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Header,
    Query,
    Request,
    Response,
)
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from app.dependencies import get_authorized_user_optional
from app.models import Generation, User
from app.schemas.google import DriveFile
from app.schemas.documents import (
    DocumentDetails,
    DocumentVariables,
    GenerateDocumentRequest,
    ValidationErrorsResponse,
    DocumentVariable,
)
from app.services.documents import (
    download_template_as_format,
    get_document_variables_info,
    generate_document,
    resolve_format,
    validate_document_generation_request,
    validate_document_mime_type,
    validate_variables_for_document,
)
from app.services.google_drive import (
    download_file,
    get_drive_item_metadata,
    format_drive_file_metadata,
)
from app.services.resource_limits import (
    ResourceLimitError,
    TimeoutError,
    MemoryLimitError,
    validate_file_size,
)
from app.exceptions import ValidationErrorsException
from app.limiter import limiter
from beanie import Link
from app.enums import FORMAT_TO_MIME, DocumentResponseFormat
from app.schemas.auth import AuthorizedUser
from app.services.scopes import require_document_access
from app.constants import DEFAULT_VARIABLE_ORDER

router = APIRouter(prefix="/documents", tags=["documents"])

common_responses: dict[int | str, dict[str, Any]] = {
    404: {
        "description": "Document not found or access denied",
        "content": {
            "application/json": {
                "example": {"detail": "Document not found or access denied"}
            }
        },
    },
    403: {
        "description": "Access denied",
        "content": {
            "application/json": {"example": {"detail": "Admin access required"}}
        },
    },
    415: {
        "description": "Requested document mime type not supported",
        "content": {
            "application/json": {
                "example": {"detail": "Requested document mime type not supported"}
            }
        },
    },
    413: {
        "description": "File too large",
        "content": {
            "application/json": {
                "example": {"detail": "File size exceeds maximum allowed size"}
            }
        },
    },
    422: {
        "description": "Processing failed due to resource limits",
        "content": {
            "application/json": {
                "example": {"detail": "Document processing exceeded resource limits"}
            }
        },
    },
}

common_responses_with_validation: dict[int | str, dict[str, Any]] = {
    **common_responses,
    400: {
        "description": "Validation error",
        "content": {
            "application/json": {
                "example": {
                    "errors": {
                        "company_name": "Cannot override constant variable",
                        "employee_name": "Missing required variable",
                        "email": "Validation error: 'invalid' is not of type 'string'",
                    }
                }
            }
        },
    },
}


def handle_resource_limit_error(e: ResourceLimitError) -> HTTPException:
    """Convert resource limit errors to appropriate HTTP exceptions."""
    if isinstance(e, TimeoutError):
        return HTTPException(
            status_code=422,
            detail="Document processing exceeded time limit. Please try with a smaller document.",
        )
    elif isinstance(e, MemoryLimitError):
        return HTTPException(
            status_code=422,
            detail="Document processing exceeded memory limit. Please try with a smaller document.",
        )
    else:
        return HTTPException(
            status_code=422,
            detail=f"Document processing failed: {str(e)}",
        )


@router.get(
    "/{document_id}",
    response_model=DocumentDetails,
    responses=common_responses,
)
@limiter.limit("5/minute")
async def get_document(
    document_id: str,
    request: Request,
    response: Response,
    authorized_user: AuthorizedUser | None = Depends(get_authorized_user_optional),
) -> DocumentDetails:
    await require_document_access(document_id, authorized_user)

    try:
        file_metadata = get_drive_item_metadata(document_id)
    except Exception:
        raise HTTPException(
            status_code=404, detail="Document not found or access denied"
        )

    file = format_drive_file_metadata(file_metadata)
    validate_document_mime_type(file.mime_type)

    try:
        validate_file_size(file.size)
    except ResourceLimitError as e:
        raise HTTPException(status_code=413, detail=str(e))

    user_id = authorized_user.user_id if authorized_user else None

    try:
        template_variables, variables_info = await get_document_variables_info(
            file, user_id, file.parent
        )
    except ResourceLimitError as e:
        raise handle_resource_limit_error(e)

    # Convert to response format
    variables_list = []
    for var_name in template_variables:
        var_info = variables_info.get(var_name, {})
        variables_list.append(
            DocumentVariable(
                id=var_info.get("id"),
                variable=var_name,
                value=var_info.get("value"),
                validation_schema=var_info.get("validation_schema"),
                required=var_info.get("required", False),
                allow_save=var_info.get("allow_save", False),
                scope=var_info.get("scope"),
                saved_value=var_info.get("saved_value"),
                order=var_info.get("order", DEFAULT_VARIABLE_ORDER),
            )
        )

    return DocumentDetails(
        file=file,
        variables=DocumentVariables(
            template_variables=list(template_variables),
            variables=variables_list,
        ),
    )


@router.get(
    "/{document_id}/file",
    response_model=DriveFile,
    responses=common_responses,
)
@limiter.limit("5/minute")
async def get_document_file(
    document_id: str,
    request: Request,
    response: Response,
    authorized_user: AuthorizedUser | None = Depends(get_authorized_user_optional),
) -> DriveFile:
    await require_document_access(document_id, authorized_user)

    try:
        file_metadata = get_drive_item_metadata(document_id)
    except Exception:
        raise HTTPException(
            status_code=404, detail="Document not found or access denied"
        )

    file = format_drive_file_metadata(file_metadata)
    validate_document_mime_type(file.mime_type)

    return file


@router.get(
    "/{document_id}/variables",
    response_model=DocumentVariables,
    responses=common_responses,
)
@limiter.limit("5/minute")
async def get_variables_for_document(
    document_id: str,
    request: Request,
    response: Response,
    authorized_user: AuthorizedUser | None = Depends(get_authorized_user_optional),
) -> DocumentVariables:
    await require_document_access(document_id, authorized_user)

    try:
        file_metadata = get_drive_item_metadata(document_id)
    except Exception:
        raise HTTPException(
            status_code=404, detail="Document not found or access denied"
        )

    file = format_drive_file_metadata(file_metadata)
    validate_document_mime_type(file.mime_type)

    # Validate file size early
    try:
        validate_file_size(file.size)
    except ResourceLimitError as e:
        raise HTTPException(status_code=413, detail=str(e))

    user_id = authorized_user.user_id if authorized_user else None

    try:
        template_variables, variables_info = await get_document_variables_info(
            file, user_id, file.parent
        )
    except ResourceLimitError as e:
        raise handle_resource_limit_error(e)

    # Convert to response format
    variables_list = []
    for var_name in template_variables:
        var_info = variables_info.get(var_name, {})
        variables_list.append(
            DocumentVariable(
                id=var_info.get("id"),
                variable=var_name,
                value=var_info.get("value"),
                validation_schema=var_info.get("validation_schema"),
                required=var_info.get("required", False),
                allow_save=var_info.get("allow_save", False),
                scope=var_info.get("scope"),
                saved_value=var_info.get("saved_value"),
                order=var_info.get("order", DEFAULT_VARIABLE_ORDER),
            )
        )

    return DocumentVariables(
        template_variables=list(template_variables),
        variables=variables_list,
    )


@router.get(
    "/{document_id}/raw",
    responses=common_responses,
)
@limiter.limit("5/minute")
async def get_raw_document(
    document_id: str,
    request: Request,
    response: Response,
    authorized_user: AuthorizedUser | None = Depends(get_authorized_user_optional),
) -> StreamingResponse:
    await require_document_access(document_id, authorized_user)

    try:
        file_metadata = get_drive_item_metadata(document_id)
    except Exception:
        raise HTTPException(
            status_code=404, detail="Document not found or access denied"
        )

    file = format_drive_file_metadata(file_metadata)
    validate_document_mime_type(file.mime_type)

    try:
        validate_file_size(file.size)
    except ResourceLimitError as e:
        raise HTTPException(status_code=413, detail=str(e))

    content = BytesIO()

    try:
        if file.mime_type == "application/vnd.google-apps.document":
            media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            download_file(file.id, content, media_type, file.size)
        else:
            media_type = file.mime_type
            download_file(file.id, content, None, file.size)
    except ResourceLimitError as e:
        raise HTTPException(status_code=413, detail=str(e))

    content.seek(0)

    return StreamingResponse(
        content,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename={file.id}"},
    )


@router.get(
    "/{document_id}/preview",
    responses={
        **common_responses,
        200: {
            "description": "Returns template preview (PDF or DOCX) without filled variables",
            "content": {
                "application/pdf": {},
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {},
                "application/json": None,
            },
        },
    },
)
@limiter.limit("5/minute")
async def preview_document(
    document_id: str,
    background_tasks: BackgroundTasks,
    request: Request,
    response: Response,
    format: DocumentResponseFormat = Query(DocumentResponseFormat.PDF),
    accept: str | None = Header(None),
    authorized_user: AuthorizedUser | None = Depends(get_authorized_user_optional),
) -> FileResponse:
    await require_document_access(document_id, authorized_user)

    format = resolve_format(accept, format)

    try:
        file_metadata = get_drive_item_metadata(document_id)
    except Exception:
        raise HTTPException(
            status_code=404, detail="Document not found or access denied"
        )

    file = format_drive_file_metadata(file_metadata)
    validate_document_mime_type(file.mime_type)

    try:
        validate_file_size(file.size)
    except ResourceLimitError as e:
        raise HTTPException(status_code=413, detail=str(e))

    try:
        file_path = download_template_as_format(file, format)
    except ResourceLimitError as e:
        raise handle_resource_limit_error(e)

    background_tasks.add_task(os.remove, file_path)

    return FileResponse(
        path=file_path,
        filename=f"{document_id}_template.{format.value}",
        media_type=FORMAT_TO_MIME[format],
    )


@router.post(
    "/{document_id}/validation",
    response_model=ValidationErrorsResponse,
    responses={
        **common_responses_with_validation,
        200: {
            "description": "Validation successful",
            "content": {
                "application/json": {
                    "example": {
                        "errors": {},
                        "is_valid": True,
                    }
                }
            },
        },
    },
)
@limiter.limit("5/minute")
async def validate_provided_variables_for_document(
    document_id: str,
    body: GenerateDocumentRequest,
    request: Request,
    response: Response,
    authorized_user: AuthorizedUser | None = Depends(get_authorized_user_optional),
) -> ValidationErrorsResponse | JSONResponse:
    await require_document_access(document_id, authorized_user)

    validate_document_generation_request(body.variables)

    try:
        file_metadata = get_drive_item_metadata(document_id)
    except Exception:
        raise HTTPException(
            status_code=404, detail="Document not found or access denied"
        )

    file = format_drive_file_metadata(file_metadata)
    validate_document_mime_type(file.mime_type)

    try:
        validate_file_size(file.size)
    except ResourceLimitError as e:
        raise HTTPException(status_code=413, detail=str(e))

    user_id = authorized_user.user_id if authorized_user else None

    try:
        await validate_variables_for_document(
            file, body.variables, user_id, body.bypass_validation
        )
    except ResourceLimitError as e:
        raise handle_resource_limit_error(e)
    except ValidationErrorsException as e:
        return JSONResponse(
            status_code=400, content={"is_valid": False, "errors": e.errors}
        )

    return ValidationErrorsResponse(is_valid=True, errors={})


@router.post(
    "/{document_id}/generate",
    response_model=None,
    responses={
        **common_responses_with_validation,
        200: {
            "description": "Returns generated file",
            "content": {
                "application/pdf": {},
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {},
                "application/json": None,
            },
        },
    },
)
@limiter.limit("5/minute")
async def generate_document_with_variables(
    document_id: str,
    body: GenerateDocumentRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    response: Response,
    format: DocumentResponseFormat = Query(DocumentResponseFormat.PDF),
    accept: str | None = Header(None),
    authorized_user: AuthorizedUser | None = Depends(get_authorized_user_optional),
) -> JSONResponse | FileResponse:
    """
    Generate document with user-provided variables.

    Access control is enforced based on scope restrictions:
    - access_level=ANY: Anyone can generate
    - access_level=AUTHORIZED: Requires authentication
    - access_level=EMAIL_VERIFIED: Requires verified email
    - access_level=ADMIN: Requires admin/god role

    Max depth also applies - documents beyond the configured depth are inaccessible.

    Variable resolution priority:
    1. Constants from database (cannot be overridden)
    2. User-provided values (validated against schema if configured)
    3. User's saved values (if authenticated)

    If bypass_validation=true, skips all validation and uses user values as-is.
    """
    await require_document_access(document_id, authorized_user)

    format = resolve_format(accept, format)
    validate_document_generation_request(body.variables)

    try:
        file_metadata = get_drive_item_metadata(document_id)
    except Exception:
        raise HTTPException(
            status_code=404, detail="Document not found or access denied"
        )

    file = format_drive_file_metadata(file_metadata)
    validate_document_mime_type(file.mime_type)

    try:
        validate_file_size(file.size)
    except ResourceLimitError as e:
        raise HTTPException(status_code=413, detail=str(e))

    user_id = authorized_user.user_id if authorized_user else None

    try:
        file_path, context = await generate_document(
            file, body.variables, user_id, body.bypass_validation, format
        )
    except ResourceLimitError as e:
        raise handle_resource_limit_error(e)
    except ValidationErrorsException as e:
        return JSONResponse(status_code=400, content={"errors": e.errors})

    background_tasks.add_task(os.remove, file_path)

    if file.mime_type == "application/vnd.google-apps.document":
        filename = file.name
    else:
        filename, _ = os.path.splitext(file.name)

    result_data: dict[str, Any] = {
        "template_id": document_id,
        "template_name": filename,
        "variables": context,
        "format": format,
    }

    if authorized_user:
        result_data["user"] = cast(Link[User], authorized_user.user_id)

    await Generation(**result_data).insert()

    return FileResponse(
        path=file_path,
        filename=f"{document_id}.{format.value}",
        media_type=FORMAT_TO_MIME[format],
    )
