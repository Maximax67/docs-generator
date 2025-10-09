from typing import Any, Dict, Union
from io import BytesIO
import os
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
    Response,
)
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from app.dependencies import authorize_user_or_admin
from app.models.database import Result, User
from app.models.google import DriveFile, DriveFileListResponse
from app.models.documents import (
    DocumentDetails,
    DocumentVariables,
    GenerateDocumentRequest,
    ValidationErrorsResponse,
)
from app.services.documents import (
    generate_preview,
    get_all_documents,
    get_validated_document_variables,
    generate_document,
    validate_variables_for_document,
)
from app.services.google_drive import (
    download_file,
    get_drive_item_metadata,
    format_drive_file_metadata,
)
from app.exceptions import ValidationErrorsException
from app.limiter import limiter
from beanie import PydanticObjectId
from app.utils import (
    validate_document_generation_request,
    validate_document_mime_type,
)

router = APIRouter(prefix="/documents", tags=["documents"])

common_responses: Dict[Union[int, str], Dict[str, Any]] = {
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

common_responses_with_validation: Dict[Union[int, str], Dict[str, Any]] = {
    **common_responses,
    400: {
        "description": "Validation error",
        "content": {
            "application/json": {
                "example": {
                    "errors": {
                        "random_variable": "Variable is not used in the document",
                        "pi": "Cannot set constant variable",
                        "surname": "Missing required variable",
                        "gender": "Value must be one of the allowed choices",
                        "phone": "Regex evaluation failed",
                        "asdf": "Unknown variable",
                    },
                    "is_valid": False,
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
    document_id: str, request: Request, response: Response
) -> DocumentDetails:
    try:
        file_metadata = get_drive_item_metadata(document_id)
    except Exception:
        raise HTTPException(
            status_code=404, detail="Document not found or access denied"
        )

    file = format_drive_file_metadata(file_metadata)
    validate_document_mime_type(file.mime_type)

    variables, unknown_variables = get_validated_document_variables(file)
    is_valid = len(unknown_variables) == 0

    return DocumentDetails(
        file=file,
        variables=variables,
        unknown_variables=unknown_variables,
        is_valid=is_valid,
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
    document_id: str, request: Request, response: Response
) -> DocumentVariables:
    try:
        file_metadata = get_drive_item_metadata(document_id)
    except Exception:
        raise HTTPException(
            status_code=404, detail="Document not found or access denied"
        )

    file = format_drive_file_metadata(file_metadata)
    validate_document_mime_type(file.mime_type)

    variables, unknown_variables = get_validated_document_variables(file)
    is_valid = len(unknown_variables) == 0

    return DocumentVariables(
        variables=variables, unknown_variables=unknown_variables, is_valid=is_valid
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
            "description": "Returns preview PDF file",
            "content": {"application/pdf": {}, "application/json": None},
        },
    },
)
@limiter.limit("5/minute")
async def preview_document(
    document_id: str,
    background_tasks: BackgroundTasks,
    request: Request,
    response: Response,
) -> FileResponse:
    try:
        file_metadata = get_drive_item_metadata(document_id)
    except Exception:
        raise HTTPException(
            status_code=404, detail="Document not found or access denied"
        )

    file = format_drive_file_metadata(file_metadata)
    validate_document_mime_type(file.mime_type)

    pdf_file_path, _ = generate_preview(file)
    background_tasks.add_task(os.remove, pdf_file_path)

    return FileResponse(
        path=pdf_file_path,
        filename=f"{document_id}.pdf",
        media_type="application/pdf",
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
) -> Union[ValidationErrorsResponse, JSONResponse]:
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
        validate_variables_for_document(file, body.variables)
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
            "description": "Returns generated PDF file",
            "content": {"application/pdf": {}, "application/json": None},
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
) -> Union[JSONResponse, FileResponse]:
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
        pdf_file_path, context = generate_document(file, body.variables)
    except ValidationErrorsException as e:
        return JSONResponse(status_code=400, content={"errors": e.errors})

    background_tasks.add_task(os.remove, pdf_file_path)

    if file.mime_type == "application/vnd.google-apps.document":
        filename = file.name
    else:
        filename, _ = os.path.splitext(file.name)

    await Result(
        template_id=document_id, template_name=filename, variables=context
    ).insert()

    return FileResponse(
        path=pdf_file_path,
        filename=f"{document_id}.pdf",
        media_type="application/pdf",
    )


@router.post(
    "/{document_id}/generate/{user_id}",
    dependencies=[Depends(authorize_user_or_admin)],
    response_model=None,
    responses={
        **common_responses_with_validation,
        200: {
            "description": "Returns generated PDF file",
            "content": {"application/pdf": {}, "application/json": None},
        },
        403: {
            "description": "Forbidden",
            "content": {"application/json": {"example": {"detail": "Invalid token"}}},
        },
    },
)
@limiter.limit("5/minute")
async def generate_document_with_variables_for_user(
    document_id: str,
    user_id: PydanticObjectId,
    body: GenerateDocumentRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    response: Response,
) -> Union[JSONResponse, FileResponse]:
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
        pdf_file_path, context = generate_document(file, body.variables)
    except ValidationErrorsException as e:
        return JSONResponse(status_code=400, content={"errors": e.errors})

    background_tasks.add_task(os.remove, pdf_file_path)

    user_exists = await User.find_one(User.id == user_id)
    if not user_exists:
        raise HTTPException(status_code=404, detail="User not found")

    if file.mime_type == "application/vnd.google-apps.document":
        filename = file.name
    else:
        filename, _ = os.path.splitext(file.name)

    await Result(
        user=user_id,
        template_id=document_id,
        template_name=filename,
        variables=context,
    ).insert()

    return FileResponse(
        path=pdf_file_path,
        filename=f"{document_id}.pdf",
        media_type="application/pdf",
    )
