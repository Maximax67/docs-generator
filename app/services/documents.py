import os
import tempfile
from beanie import PydanticObjectId
from typing import Any
from docxtpl import DocxTemplate  # type: ignore[import-untyped]
from fastapi import HTTPException

from app.models.scope import Scope
from app.schemas.auth import AuthorizedUser
from app.schemas.google import DriveFile
from app.services.google_drive import (
    download_file,
    get_accessible_documents,
    format_drive_file_metadata,
    get_drive_item_metadata,
    get_item_path,
)
from app.services.jinja import jinja_env
from app.services.soffice import convert_file
from app.services.variables import (
    get_effective_variables_for_document,
    resolve_variables_for_generation,
)
from app.enums import MIME_TO_FORMAT, AccessLevel, DocumentResponseFormat, UserRole
from app.settings import settings
from app.constants import DOC_COMPATIBLE_MIME_TYPES, DRIVE_FOLDER_MIME_TYPE


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


async def check_document_access(
    document_id: str,
    authorized_user: AuthorizedUser | None,
) -> tuple[bool, str]:
    """
    Check if user has access to a document based on scope restrictions.

    Args:
        document_id: Google Drive document ID
        authorized_user: Current user (None if unauthenticated)

    Returns:
        Tuple of (has_access: bool, reason: str)
        - has_access: True if user can access the document
        - reason: Explanation if access is denied

    Examples:
        Document in scope with access_level=ANY, max_depth=None:
        → Everyone has access

        Document in scope with access_level=ADMIN, max_depth=2:
        → Only admins/gods have access if document is within 2 levels of scope

        Document 3 levels deep in scope with max_depth=2:
        → No one has access (beyond depth limit)
    """
    # Get all scopes
    all_scopes = await Scope.find_all(fetch_links=True).to_list()

    if not all_scopes:
        # No scopes configured = open access
        return False, "No scope restrictions configured"

    # Get document metadata to check if it's a folder
    try:
        doc_metadata = get_drive_item_metadata(document_id)
        is_folder = doc_metadata.get("mimeType") == DRIVE_FOLDER_MIME_TYPE
    except Exception:
        return False, "Document not found in Google Drive"

    # Get document's path in the drive hierarchy
    try:
        item_path = get_item_path(document_id)
    except Exception:
        # If we can't get the path, deny access
        return False, "Cannot determine document location"

    # Find the most specific scope that applies to this document
    applicable_scopes: list[tuple[Scope, int]] = []

    for scope in all_scopes:
        if scope.drive_id not in item_path:
            continue

        # Found a scope in the path
        scope_index = item_path.index(scope.drive_id)
        applicable_scopes.append((scope, scope_index))

    if not applicable_scopes:
        return False, "Document not under any scope"

    # Use the most specific scope (furthest down the tree)
    applicable_scopes.sort(key=lambda x: x[1], reverse=True)
    most_specific_scope, scope_index = applicable_scopes[0]

    # Calculate depth from scope to document
    current_depth = len(item_path) - scope_index - 1

    # Check depth restrictions
    max_depth = most_specific_scope.restrictions.max_depth

    if max_depth is not None:
        # For folders: accessible if current_depth <= max_depth
        # (we need to allow the folder to be accessible so we can access its children)
        # However, if max_depth is 0, folders at depth 1 should not be accessible
        if is_folder:
            # Special case: if we're AT the scope (depth 0), always accessible
            if current_depth == 0:
                pass  # Always accessible
            elif current_depth > max_depth:
                return (
                    False,
                    f"Folder exceeds maximum depth ({current_depth} > {max_depth})",
                )
        else:
            # For files: accessible if current_depth <= max_depth
            if current_depth > max_depth:
                return (
                    False,
                    f"Document exceeds maximum depth ({current_depth} > {max_depth})",
                )

    # Check access level
    access_level = most_specific_scope.restrictions.access_level

    if access_level == AccessLevel.ANY:
        return True, "Open access"

    # All other levels require authentication
    if not authorized_user:
        return False, f"Authentication required (access level: {access_level.value})"

    # Check specific access levels
    if access_level == AccessLevel.ADMIN:
        if authorized_user.role not in [UserRole.ADMIN, UserRole.GOD]:
            return False, "Admin access required"
        return True, "Admin access granted"

    if access_level == AccessLevel.EMAIL_VERIFIED:
        if not authorized_user.is_email_verified:
            return False, "Email verification required"
        return True, "Email verified access granted"

    if access_level == AccessLevel.AUTHORIZED:
        return True, "Authenticated access granted"

    return False, "Unknown access level"


async def require_document_access(
    document_id: str,
    authorized_user: AuthorizedUser | None,
) -> None:
    """
    Enforce document access or raise HTTPException.

    Raises:
        HTTPException: 403 if access denied, 404 if document not found
    """
    if authorized_user and authorized_user.role == UserRole.GOD:
        return

    has_access, reason = await check_document_access(document_id, authorized_user)

    if not has_access:
        if "not found" in reason.lower():
            raise HTTPException(
                status_code=404, detail="Document not found or access denied"
            )

        raise HTTPException(status_code=403, detail=reason)


# Helper function for testing depth calculations
def calculate_depth_from_path(
    item_path: list[str],
    scope_drive_id: str,
) -> int:
    """
    Calculate how deep an item is from a scope.

    Args:
        item_path: Path from root to item [root, ..., parent, item]
        scope_drive_id: The scope's drive_id

    Returns:
        Depth (0 = scope itself, 1 = direct child, etc.)
        Returns -1 if scope not in path

    Examples:
        item_path = ['root', 'folder_a', 'folder_b', 'doc']
        scope_drive_id = 'folder_a'
        → depth = 2 (folder_b is 1, doc is 2)

        item_path = ['root', 'folder_a']
        scope_drive_id = 'folder_a'
        → depth = 0 (the scope itself)
    """
    try:
        scope_index = item_path.index(scope_drive_id)
        return len(item_path) - scope_index - 1
    except ValueError:
        return -1
