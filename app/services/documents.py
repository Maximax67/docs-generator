import os
import tempfile
from typing import Dict, List, Optional, Set, Tuple, Union
from docxtpl import DocxTemplate  # type: ignore[import-untyped]

from app.models.google import DriveFile
from app.models.variables import ConstantVariable, MultichoiceVariable, PlainVariable
from app.services.config import get_preview_variables, get_variables_dict
from app.services.google_drive import (
    format_drive_file_metadata,
    download_file,
    get_accessible_documents,
)
from app.services.jinja import jinja_env
from app.services.soffice import convert_file
from app.services.variables import validate_variable
from app.exceptions import ValidationErrorsException


def get_all_documents() -> List[DriveFile]:
    documents = get_accessible_documents()

    return [format_drive_file_metadata(document) for document in documents]


def download_docx_document(document: DriveFile) -> str:
    download_mime_type: Optional[str] = None

    if document.mime_type == "application/vnd.google-apps.document":
        download_mime_type = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        extension = ".docx"
    else:
        _, extension = os.path.splitext(document.name)
        if not extension:
            extension = ".docx"

    temp_path: Optional[str] = None
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


def download_document_and_get_variables(document: DriveFile) -> Tuple[str, Set[str]]:
    docx_path: Optional[str] = None

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
    document_variables: Set[str],
) -> Tuple[
    List[Union[PlainVariable, MultichoiceVariable, ConstantVariable]], List[str]
]:
    available_variables = get_variables_dict()

    found_variables: List[
        Union[PlainVariable, MultichoiceVariable, ConstantVariable]
    ] = []
    unknown_variables: List[str] = []

    for var_name in document_variables:
        if var_name in available_variables:
            found_variables.append(available_variables[var_name])
        else:
            unknown_variables.append(var_name)

    return found_variables, unknown_variables


def get_validated_document_variables(
    document: DriveFile,
) -> Tuple[
    List[Union[PlainVariable, MultichoiceVariable, ConstantVariable]], List[str]
]:
    docx_path, variables = download_document_and_get_variables(document)
    os.remove(docx_path)

    return validate_document_variables(variables)


def generate_preview(document: DriveFile) -> Tuple[str, Set[str]]:
    docx_path: Optional[str] = None
    rendered_path: Optional[str] = None

    try:
        docx_path = download_docx_document(document)
        doc = DocxTemplate(docx_path)

        variables = doc.get_undeclared_template_variables(jinja_env)
        context = get_preview_variables()

        doc.render(context, jinja_env, autoescape=True)

        rendered_fd, rendered_path = tempfile.mkstemp(suffix=".docx")
        os.close(rendered_fd)
        doc.save(rendered_path)

        pdf_path = convert_file(rendered_path, "pdf")

        return pdf_path, variables
    finally:
        if docx_path and os.path.exists(docx_path):
            os.remove(docx_path)
        if rendered_path and os.path.exists(rendered_path):
            os.remove(rendered_path)


def get_document_and_prepare_context(
    document: DriveFile,
    variables: Dict[str, str],
    exclude_constants: Optional[bool] = None,
) -> Tuple[str, Dict[str, str]]:
    available_variables = get_variables_dict()
    docx_path, document_variables = download_document_and_get_variables(document)

    try:
        errors: Dict[str, str] = {}
        for var_name in variables:
            if var_name not in document_variables:
                errors[var_name] = "Variable is not used in the document"
                continue

            variable = available_variables.get(var_name)
            if not variable:
                errors[var_name] = "Unknown variable"
                continue

            if exclude_constants is None and isinstance(variable, ConstantVariable):
                errors[var_name] = "Cannot set constant variable"
                continue

        context: Dict[str, str] = {}
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
                if not variable.allow_skip:
                    errors[var_name] = "Missing required variable"

                continue

            if not isinstance(variable, ConstantVariable):
                error = validate_variable(variable, value)
                if error:
                    errors[var_name] = error
                    continue

            context[var_name] = value

        if errors:
            raise ValidationErrorsException(errors)

        return docx_path, context
    except Exception as e:
        if docx_path and os.path.exists(docx_path):
            os.remove(docx_path)

        raise e


def validate_variables_for_document(
    document: DriveFile, variables: Dict[str, str]
) -> None:
    docx_path, _ = get_document_and_prepare_context(document, variables)
    os.remove(docx_path)


def generate_document(
    document: DriveFile,
    variables: Dict[str, str],
    exclude_constants: Optional[bool] = None,
) -> Tuple[str, Dict[str, str]]:
    rendered_path: Optional[str] = None
    docx_path, context = get_document_and_prepare_context(
        document, variables, exclude_constants
    )

    try:
        doc = DocxTemplate(docx_path)
        doc.render(context, jinja_env, autoescape=True)

        rendered_fd, rendered_path = tempfile.mkstemp(suffix=".docx")
        os.close(rendered_fd)
        doc.save(rendered_path)

        pdf_path = convert_file(rendered_path, "pdf")

        return pdf_path, context
    finally:
        if docx_path and os.path.exists(docx_path):
            os.remove(docx_path)
        if rendered_path and os.path.exists(rendered_path):
            os.remove(rendered_path)
