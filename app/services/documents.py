import os
import tempfile
from typing import Any
from docxtpl import DocxTemplate
from fastapi import HTTPException  # type: ignore[import-untyped]

from app.schemas.google import DriveFile
from app.services.google_drive import (
    format_drive_file_metadata,
    download_file,
    get_accessible_documents,
)
from app.services.jinja import jinja_env
from app.services.soffice import convert_file
from app.exceptions import ValidationErrorsException
from app.enums import DocumentResponseFormat, MIME_TO_FORMAT
from app.settings import settings
from app.constants import DOC_COMPATIBLE_MIME_TYPES


def get_all_documents() -> list[DriveFile]:
    documents = get_accessible_documents()

    return [format_drive_file_metadata(document) for document in documents]


def download_docx_document(document: DriveFile) -> str:
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


def download_document_and_get_variables(document: DriveFile) -> tuple[str, set[str]]:
    docx_path: str | None = None

    try:
        docx_path = download_docx_document(document)
        doc = DocxTemplate(docx_path)
        variables = doc.get_undeclared_template_variables(jinja_env)

        return docx_path, variables
    except Exception as e:
        if docx_path and os.path.exists(docx_path):
            os.remove(docx_path)

        raise e


def validate_document_variables(
    document_variables: set[str],
) -> tuple[list[Variable], list[str]]:
    available_variables = get_variables_dict()

    found_variables: list[Variable] = []
    unknown_variables: list[str] = []

    for var_name in document_variables:
        if var_name in available_variables:
            found_variables.append(available_variables[var_name])
        else:
            unknown_variables.append(var_name)

    return found_variables, unknown_variables


def get_validated_document_variables(
    document: DriveFile,
) -> tuple[list[Variable], list[str]]:
    docx_path, variables = download_document_and_get_variables(document)
    os.remove(docx_path)

    return validate_document_variables(variables)


def generate_preview(
    document: DriveFile,
    format: DocumentResponseFormat = DocumentResponseFormat.PDF,
) -> tuple[str, set[str]]:
    docx_path: str | None = None
    rendered_path: str | None = None

    try:
        docx_path = download_docx_document(document)
        doc = DocxTemplate(docx_path)

        variables = doc.get_undeclared_template_variables(jinja_env)
        context = get_preview_variables()

        doc.render(context, jinja_env, autoescape=True)

        rendered_fd, rendered_path = tempfile.mkstemp(suffix=".docx")
        os.close(rendered_fd)
        doc.save(rendered_path)

        if format == DocumentResponseFormat.DOCX:
            return rendered_path, variables

        converted_path = convert_file(rendered_path, format.value)

        return converted_path, variables
    finally:
        if docx_path and os.path.exists(docx_path):
            os.remove(docx_path)

        if (
            format != DocumentResponseFormat.DOCX
            and rendered_path
            and os.path.exists(rendered_path)
        ):
            os.remove(rendered_path)


def get_document_and_prepare_context(
    document: DriveFile,
    variables: dict[str, str],
    exclude_constants: bool | None = None,
) -> tuple[str, dict[str, str]]:
    available_variables = get_variables_dict()
    docx_path, document_variables = download_document_and_get_variables(document)

    try:
        errors: dict[str, Any] = {}
        for var_name in variables:
            if var_name not in document_variables:
                continue

            variable = available_variables.get(var_name)
            if not variable:
                continue

            if exclude_constants is None and isinstance(variable, ConstantVariable):
                errors[var_name] = "Cannot set constant variable"
                continue

        context: dict[str, str] = {}
        for var_name in document_variables:
            variable = available_variables.get(var_name)
            if variable is None:
                continue

            if (exclude_constants is None or exclude_constants) and isinstance(
                variable, ConstantVariable
            ):
                context[var_name] = variable.value
                continue

            value = variables.get(var_name)
            if value is None:
                if not variable.nullable:
                    errors[var_name] = "Missing required variable"

                continue

            if not isinstance(variable, ConstantVariable):
                error = validate_variable(variable, value)
                if error:
                    errors[var_name] = error
                    continue

        if errors:
            raise ValidationErrorsException(errors)

        for var_name, var_value in variables.items():
            if var_name not in context:
                context[var_name] = var_value

        return docx_path, context
    except Exception as e:
        if docx_path and os.path.exists(docx_path):
            os.remove(docx_path)

        raise e


def validate_variables_for_document(
    document: DriveFile, variables: dict[str, str]
) -> None:
    docx_path, context = get_document_and_prepare_context(document, variables)

    try:
        doc = DocxTemplate(docx_path)
        doc.render(context, jinja_env, autoescape=True)
        undeclared = doc.get_undeclared_template_variables(jinja_env, context)
    finally:
        os.remove(docx_path)

    errors: dict[str, str] = {}
    for variable in undeclared:
        errors[variable] = "Undeclared variable"

    if errors:
        raise ValidationErrorsException(errors)


def generate_document(
    document: DriveFile,
    variables: dict[str, str],
    exclude_constants: bool | None = None,
    format: DocumentResponseFormat = DocumentResponseFormat.PDF,
) -> tuple[str, dict[str, str]]:
    rendered_path: str | None = None
    docx_path, context = get_document_and_prepare_context(
        document, variables, exclude_constants
    )

    try:
        doc = DocxTemplate(docx_path)
        doc.render(context, jinja_env, autoescape=True)

        rendered_fd, rendered_path = tempfile.mkstemp(suffix=".docx")
        os.close(rendered_fd)
        doc.save(rendered_path)

        if format == DocumentResponseFormat.DOCX:
            return rendered_path, context

        converted_path = convert_file(rendered_path, str(format.value))

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


def validate_saved_variables_count(variables_count: int) -> None:
    if variables_count > settings.MAX_SAVED_VARIABLES:
        raise HTTPException(
            status_code=422,
            detail=f"Cannot store more than {settings.MAX_SAVED_VARIABLES} variables",
        )


def validate_document_generation_request(variables: dict[str, Any]) -> None:
    if len(variables) > settings.MAX_DOCUMENT_VARIABLES:
        raise HTTPException(
            status_code=422,
            detail=f"Documents can not have more than {settings.MAX_DOCUMENT_VARIABLES} variables",
        )

    for variable, value in variables.items():
        validate_variable_name(variable)
        validate_variable_value(value)


def validate_document_mime_type(mime_type: str) -> None:
    if mime_type not in DOC_COMPATIBLE_MIME_TYPES:
        raise HTTPException(
            status_code=415,
            detail="Requested document mime type not supported",
        )


def ensure_folder(mime_type: str) -> None:
    if mime_type != "application/vnd.google-apps.folder":
        raise HTTPException(
            status_code=400,
            detail="The requested resource is not a folder",
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
