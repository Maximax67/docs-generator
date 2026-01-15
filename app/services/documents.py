import os
import tempfile
from beanie import PydanticObjectId
from typing import Any
from docxtpl import DocxTemplate  # type: ignore[import-untyped]
from fastapi import HTTPException

from app.schemas.google import DriveFile
from app.services.google_drive import (
    download_file,
    get_accessible_documents,
    format_drive_file_metadata,
)
from app.services.jinja import jinja_env
from app.services.soffice import convert_file
from app.services.variables import (
    get_effective_variables_for_document,
    resolve_variables_for_generation,
)
from app.enums import MIME_TO_FORMAT, DocumentResponseFormat
from app.settings import settings
from app.constants import DOC_COMPATIBLE_MIME_TYPES


def get_all_documents() -> list[DriveFile]:
    documents = get_accessible_documents()
    return [format_drive_file_metadata(document) for document in documents]


def download_docx_document(document: DriveFile) -> str:
    """Download document as DOCX format."""
    download_mime_type: str | None = None

    if document.mime_type == "application/vnd.google-apps.document":
        download_mime_type = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        extension = ".docx"
    else:
        _, extension = os.path.splitext(document.name)
        if not extension:
            extension = ".docx"

    temp_path: str | None = None
    temp_fd, temp_path = tempfile.mkstemp(suffix=extension)

    try:
        with os.fdopen(temp_fd, "wb") as f:
            download_file(document.id, f, download_mime_type, document.size)

        if document.mime_type in [
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.google-apps.document",
        ]:
            docx_path = temp_path
            temp_path = None
            return docx_path

        return convert_file(temp_path, "docx")
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


def download_template_as_format(
    document: DriveFile,
    format: DocumentResponseFormat = DocumentResponseFormat.PDF,
) -> str:
    """
    Download template document in specified format without filling variables.
    For Google Docs, can download directly as PDF for better performance.
    """
    if document.mime_type == "application/vnd.google-apps.document":
        # Google Docs can be exported directly to PDF
        if format == DocumentResponseFormat.PDF:
            temp_fd, temp_path = tempfile.mkstemp(suffix=".pdf")
            try:
                with os.fdopen(temp_fd, "wb") as f:
                    download_file(document.id, f, "application/pdf", document.size)
                return temp_path
            except Exception:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                raise
        else:
            # Download as DOCX
            temp_fd, temp_path = tempfile.mkstemp(suffix=".docx")
            try:
                with os.fdopen(temp_fd, "wb") as f:
                    download_file(
                        document.id,
                        f,
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        document.size,
                    )
                return temp_path
            except Exception:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                raise
    else:
        # For non-Google Docs, download as DOCX first
        docx_path = download_docx_document(document)

        if format == DocumentResponseFormat.DOCX:
            return docx_path

        # Convert to desired format
        try:
            converted_path = convert_file(docx_path, format.value)
            return converted_path
        finally:
            if os.path.exists(docx_path):
                os.remove(docx_path)


def get_template_variables(document: DriveFile) -> set[str]:
    """Get undeclared variables from document template."""
    docx_path = download_docx_document(document)

    try:
        doc = DocxTemplate(docx_path)
        variables: set[str] = doc.get_undeclared_template_variables(jinja_env)
        return variables
    finally:
        if os.path.exists(docx_path):
            os.remove(docx_path)


async def get_document_variables_info(
    document: DriveFile,
    user_id: PydanticObjectId | None = None,
) -> tuple[set[str], dict[str, dict[str, Any]]]:
    """
    Get template variables and their database configuration.

    Returns:
    - template_variables: Set of variable names from template
    - variables_info: Dict with configuration for each variable
    """
    template_variables = get_template_variables(document)

    variables_info = await get_effective_variables_for_document(
        document.id, template_variables, user_id
    )

    return template_variables, variables_info


async def validate_variables_for_document(
    document: DriveFile,
    user_variables: dict[str, Any],
    user_id: PydanticObjectId | None = None,
    bypass_validation: bool = False,
) -> None:
    """
    Validate user-provided variables for document generation.
    Raises ValidationErrorsException if validation fails.
    """
    if bypass_validation:
        return

    template_variables = get_template_variables(document)

    # Resolve and validate variables
    await resolve_variables_for_generation(
        document.id,
        template_variables,
        user_variables,
        user_id,
        bypass_validation,
    )


async def generate_document(
    document: DriveFile,
    user_variables: dict[str, Any],
    user_id: PydanticObjectId | None = None,
    bypass_validation: bool = False,
    format: DocumentResponseFormat = DocumentResponseFormat.PDF,
) -> tuple[str, dict[str, Any]]:
    """
    Generate document with user-provided variables.

    Returns:
    - file_path: Path to generated document
    - context: Final variable context used for generation
    """
    docx_path = download_docx_document(document)
    rendered_path: str | None = None

    try:
        doc = DocxTemplate(docx_path)
        template_variables = doc.get_undeclared_template_variables(jinja_env)

        # Resolve variables with validation
        context = await resolve_variables_for_generation(
            document.id,
            template_variables,
            user_variables,
            user_id,
            bypass_validation,
        )

        # Render document
        doc.render(context, jinja_env, autoescape=True)

        rendered_fd, rendered_path = tempfile.mkstemp(suffix=".docx")
        os.close(rendered_fd)
        doc.save(rendered_path)

        if format == DocumentResponseFormat.DOCX:
            return rendered_path, context

        converted_path = convert_file(rendered_path, format.value)
        return converted_path, context

    finally:
        if docx_path and os.path.exists(docx_path):
            os.remove(docx_path)

        if (
            format != DocumentResponseFormat.DOCX
            and rendered_path
            and os.path.exists(rendered_path)
        ):
            os.remove(rendered_path)


def validate_document_generation_request(variables: dict[str, Any]) -> None:
    """Validate the generation request parameters."""
    if len(variables) > settings.MAX_DOCUMENT_VARIABLES:
        raise HTTPException(
            status_code=422,
            detail=f"Documents cannot have more than {settings.MAX_DOCUMENT_VARIABLES} variables",
        )


def validate_document_mime_type(mime_type: str) -> None:
    """Validate that document mime type is supported."""
    if mime_type not in DOC_COMPATIBLE_MIME_TYPES:
        raise HTTPException(
            status_code=415,
            detail="Requested document mime type not supported",
        )


def resolve_format(
    accept: str | None,
    format: DocumentResponseFormat | None,
) -> DocumentResponseFormat:
    if accept:
        for mime in accept.split(","):
            mime = mime.split(";")[0].strip()
            if mime in MIME_TO_FORMAT:
                return MIME_TO_FORMAT[mime]

    if format:
        return format

    return DocumentResponseFormat.PDF
