from aiogram.types import FSInputFile
from io import BytesIO
import os
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from app.settings import settings
from app.dependencies import verify_token
from app.models.google import DriveFile, DriveFileListResponse
from app.models.documents import (
    DocumentDetails,
    DocumentVariables,
    GenerateDocumentForUserRequest,
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
    export_file,
    get_file_metadata,
    format_drive_file_metadata,
)
from app.exceptions import ValidationErrorsException
from app.models.database import Feedback, Result, User
from app.utils import (
    format_document_user_mention,
    validate_document_generation_request,
    validate_document_mime_type,
)
from bot.bot import bot

router = APIRouter(prefix="/documents", tags=["documents"])

common_responses = {
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

common_responses_with_validation = {
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
def get_documents() -> DriveFileListResponse:
    return DriveFileListResponse(files=get_all_documents())


@router.get(
    "/{document_id}",
    response_model=DocumentDetails,
    responses=common_responses,
)
def get_document(document_id: str):
    try:
        file_metadata = get_file_metadata(document_id)
    except Exception:
        raise HTTPException(
            status_code=404, detail="Document not found or access denied"
        )

    file = format_drive_file_metadata(file_metadata)
    validate_document_mime_type(file.mime_type)

    variables, is_valid = get_validated_document_variables(file)

    return DocumentDetails(file=file, variables=variables, is_valid=is_valid)


@router.get(
    "/{document_id}/file",
    response_model=DriveFile,
    responses=common_responses,
)
def get_document_file(document_id: str):
    try:
        file_metadata = get_file_metadata(document_id)
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
def get_variables_for_document(document_id: str):
    try:
        file_metadata = get_file_metadata(document_id)
    except Exception:
        raise HTTPException(
            status_code=404, detail="Document not found or access denied"
        )

    file = format_drive_file_metadata(file_metadata)
    validate_document_mime_type(file.mime_type)

    variables, is_valid = get_validated_document_variables(file)

    return DocumentVariables(variables=variables, is_valid=is_valid)


@router.get(
    "/{document_id}/raw",
    responses=common_responses,
)
def get_raw_document(document_id: str):
    try:
        file_metadata = get_file_metadata(document_id)
    except Exception:
        raise HTTPException(
            status_code=404, detail="Document not found or access denied"
        )

    file = format_drive_file_metadata(file_metadata)
    validate_document_mime_type(file.mime_type)

    if file.mime_type == "application/vnd.google-apps.document":
        media_type = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        content = export_file(file.id, media_type)
    else:
        media_type = file.mime_type
        content = download_file(file.id)

    return StreamingResponse(
        BytesIO(content),
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
def preview_document(document_id: str, background_tasks: BackgroundTasks):
    try:
        file_metadata = get_file_metadata(document_id)
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
def validate_provided_variables_for_document(
    document_id: str,
    request: GenerateDocumentRequest,
):
    validate_document_generation_request(request.variables)

    try:
        file_metadata = get_file_metadata(document_id)
    except Exception:
        raise HTTPException(
            status_code=404, detail="Document not found or access denied"
        )

    file = format_drive_file_metadata(file_metadata)
    validate_document_mime_type(file.mime_type)

    try:
        validate_variables_for_document(file, request.variables)
    except ValidationErrorsException as e:
        return JSONResponse(
            status_code=400, content={"valid": False, "errors": e.errors}
        )

    return JSONResponse(status_code=200, content={"valid": True, "errors": []})


@router.post(
    "/{document_id}/generate",
    responses={
        **common_responses_with_validation,
        200: {
            "description": "Returns generated PDF file",
            "content": {"application/pdf": {}, "application/json": None},
        },
    },
)
async def generate_document_with_variables(
    document_id: str,
    request: GenerateDocumentRequest,
    background_tasks: BackgroundTasks,
):
    validate_document_generation_request(request.variables)

    try:
        file_metadata = get_file_metadata(document_id)
    except Exception:
        raise HTTPException(
            status_code=404, detail="Document not found or access denied"
        )

    file = format_drive_file_metadata(file_metadata)
    validate_document_mime_type(file.mime_type)

    try:
        pdf_file_path, context = generate_document(file, request.variables)
    except ValidationErrorsException as e:
        return JSONResponse(status_code=400, content={"errors": e.errors})

    background_tasks.add_task(os.remove, pdf_file_path)

    if file.mime_type == "application/vnd.google-apps.document":
        filename = file.name
    else:
        filename, _ = os.path.splitext(file.name)

    admin_message = await bot.send_document(
        settings.ADMIN_CHAT_ID,
        FSInputFile(pdf_file_path, filename=f"{filename}.pdf"),
        message_thread_id=settings.ADMIN_DOCUMENTS_THREAD_ID,
        caption="Згенеровано через API",
    )

    await Result(
        template_id=document_id,
        variables=context,
        telegram_message_id=admin_message.message_id,
    ).insert()

    return FileResponse(
        path=pdf_file_path,
        filename=f"{document_id}.pdf",
        media_type="application/pdf",
    )


@router.post(
    "/{document_id}/generate_for_user",
    dependencies=[Depends(verify_token)],
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
async def generate_document_with_variables_for_user(
    document_id: str,
    request: GenerateDocumentForUserRequest,
    background_tasks: BackgroundTasks,
):
    validate_document_generation_request(request.variables)

    try:
        file_metadata = get_file_metadata(document_id)
    except Exception:
        raise HTTPException(
            status_code=404, detail="Document not found or access denied"
        )

    file = format_drive_file_metadata(file_metadata)
    validate_document_mime_type(file.mime_type)

    try:
        pdf_file_path, context = generate_document(file, request.variables)
    except ValidationErrorsException as e:
        return JSONResponse(status_code=400, content={"errors": e.errors})

    background_tasks.add_task(os.remove, pdf_file_path)

    user = await User.find_one(User.telegram_id == request.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    if file.mime_type == "application/vnd.google-apps.document":
        filename = file.name
    else:
        filename, _ = os.path.splitext(file.name)

    error = None
    try:
        message = await bot.send_document(
            user.telegram_id,
            FSInputFile(pdf_file_path, filename=f"{filename}.pdf"),
            caption="Згенеровано для тебе",
        )
    except Exception as e:
        error = str(e)

    user_mention = format_document_user_mention(
        user.telegram_id, user.first_name, user.last_name, user.username
    )

    base_caption = f"Згенеровано через API для {user_mention}"
    caption = (
        f"{base_caption}, однак не вдалось надіслати юзеру: {error}"
        if error
        else base_caption
    )

    admin_message = await bot.send_document(
        settings.ADMIN_CHAT_ID,
        FSInputFile(pdf_file_path, filename=f"{filename}.pdf"),
        message_thread_id=settings.ADMIN_DOCUMENTS_THREAD_ID,
        caption=caption,
    )

    admin_message_id = admin_message.message_id

    await Result(
        user=user,
        template_id=document_id,
        variables=context,
        telegram_message_id=admin_message_id,
    ).insert()

    if error is None:
        await Feedback(
            user_id=user.telegram_id,
            user_message_id=message.message_id,
            admin_message_id=admin_message_id,
        ).insert()

    return FileResponse(
        path=pdf_file_path,
        filename=f"{document_id}.pdf",
        media_type="application/pdf",
    )
