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
from app.models import Result, User
from app.schemas.google import DriveFile, DriveFileListResponse
from app.schemas.documents import (
    DocumentDetails,
    DocumentVariables,
    GenerateDocumentRequest,
    ValidationErrorsResponse,
    DocumentVariable,
)
from app.services.documents import (
    download_template_as_format,
    get_all_documents,
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
from app.exceptions import ValidationErrorsException
from app.limiter import limiter
from beanie import Link
from app.enums import FORMAT_TO_MIME, DocumentResponseFormat
from app.schemas.auth import AuthorizedUser

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
    415: {
        "description": "Requested document mime type not supported",
        "content": {
            "application/json": {
                "example": {"detail": "Requested document mime type not supported"}
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


@router.get("", response_model=DriveFileListResponse)
@limiter.limit("5/minute")
async def get_documents(request: Request, response: Response) -> DriveFileListResponse:
    return DriveFileListResponse(files=get_all_documents())


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
    try:
        file_metadata = get_drive_item_metadata(document_id)
    except Exception:
        raise HTTPException(
            status_code=404, detail="Document not found or access denied"
        )

    file = format_drive_file_metadata(file_metadata)
    validate_document_mime_type(file.mime_type)

    user_id = authorized_user.user_id if authorized_user else None
    template_variables, variables_info = await get_document_variables_info(
        file, user_id
    )

    # Convert to response format
    variables_list = []
    for var_name in template_variables:
        var_info = variables_info.get(var_name, {})
        variables_list.append(
            DocumentVariable(
                variable=var_name,
                in_database=var_info.get("in_database", False),
                value=var_info.get("value"),
                validation_schema=var_info.get("validation_schema"),
                required=var_info.get("required", False),
                allow_save=var_info.get("allow_save", False),
                scope=var_info.get("scope"),
                saved_value=var_info.get("saved_value"),
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
    document_id: str, request: Request, response: Response
) -> DriveFile:
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
    try:
        file_metadata = get_drive_item_metadata(document_id)
    except Exception:
        raise HTTPException(
            status_code=404, detail="Document not found or access denied"
        )

    file = format_drive_file_metadata(file_metadata)
    validate_document_mime_type(file.mime_type)

    user_id = authorized_user.user_id if authorized_user else None
    template_variables, variables_info = await get_document_variables_info(
        file, user_id
    )

    # Convert to response format
    variables_list = []
    for var_name in template_variables:
        var_info = variables_info.get(var_name, {})
        variables_list.append(
            DocumentVariable(
                variable=var_name,
                in_database=var_info.get("in_database", False),
                value=var_info.get("value"),
                validation_schema=var_info.get("validation_schema"),
                required=var_info.get("required", False),
                allow_save=var_info.get("allow_save", False),
                scope=var_info.get("scope"),
                saved_value=var_info.get("saved_value"),
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
    document_id: str, request: Request, response: Response
) -> StreamingResponse:
    try:
        file_metadata = get_drive_item_metadata(document_id)
    except Exception:
        raise HTTPException(
            status_code=404, detail="Document not found or access denied"
        )

    file = format_drive_file_metadata(file_metadata)
    validate_document_mime_type(file.mime_type)

    content = BytesIO()

    if file.mime_type == "application/vnd.google-apps.document":
        media_type = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        download_file(file.id, content, media_type, file.size)
    else:
        media_type = file.mime_type
        download_file(file.id, content, None, file.size)

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
) -> FileResponse:
    format = resolve_format(accept, format)

    try:
        file_metadata = get_drive_item_metadata(document_id)
    except Exception:
        raise HTTPException(
            status_code=404, detail="Document not found or access denied"
        )

    file = format_drive_file_metadata(file_metadata)
    validate_document_mime_type(file.mime_type)

    file_path = download_template_as_format(file, format)
    background_tasks.add_task(os.remove, file_path)

    return FileResponse(
        path=file_path,
        filename=f"{document_id}_template.{format.value}",
        media_type=FORMAT_TO_MIME[format],
    )


@router.post(
    "/{document_id}/validate",
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
    validate_document_generation_request(body.variables)

    try:
        file_metadata = get_drive_item_metadata(document_id)
    except Exception:
        raise HTTPException(
            status_code=404, detail="Document not found or access denied"
        )

    file = format_drive_file_metadata(file_metadata)
    validate_document_mime_type(file.mime_type)

    user_id = authorized_user.user_id if authorized_user else None

    try:
        await validate_variables_for_document(
            file, body.variables, user_id, body.bypass_validation
        )
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

    Variable resolution priority:
    1. Constants from database (cannot be overridden)
    2. User-provided values (validated against schema if configured)
    3. User's saved values (if authenticated)

    If bypass_validation=true, skips all validation and uses user values as-is.
    """
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

    user_id = authorized_user.user_id if authorized_user else None

    try:
        file_path, context = await generate_document(
            file, body.variables, user_id, body.bypass_validation, format
        )
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

    await Result(**result_data).insert()

    return FileResponse(
        path=file_path,
        filename=f"{document_id}.{format.value}",
        media_type=FORMAT_TO_MIME[format],
    )
