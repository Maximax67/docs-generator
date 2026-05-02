from __future__ import annotations

import os
import tempfile
from typing import Any
from urllib.parse import urlparse

import httpx
from beanie import PydanticObjectId
from docx.shared import Inches, Mm, Pt
from docxtpl import DocxTemplate, InlineImage, RichText, RichTextParagraph  # type: ignore[import-untyped]
from fastapi import HTTPException

from app.constants import DOC_COMPATIBLE_MIME_TYPES
from app.enums import MIME_TO_FORMAT, DocumentResponseFormat
from app.schemas.google import DriveFile
from app.services.google_drive import download_file
from app.services.jinja import jinja_env
from app.services.resource_limits import run_with_limits, validate_file_size
from app.services.soffice import convert_file
from app.services.variables import (
    get_effective_variables_for_document,
    resolve_variables_for_generation,
)
from app.settings import settings

# Mapping of every accepted string representation to the python-docx length
# class.  The lookup is performed on the lower-cased, stripped user input so
# any capitalisation variant works transparently.
_UNIT_CLASS_MAP: dict[str, type[Mm] | type[Inches] | type[Pt]] = {
    # millimetres
    "mm": Mm,
    "millimeter": Mm,
    "millimeters": Mm,
    # inches
    "in": Inches,
    "inch": Inches,
    "inches": Inches,
    # points
    "pt": Pt,
    "point": Pt,
    "points": Pt,
}

_ACCEPTED_UNITS_DISPLAY = "mm / millimeters, inches / in, pt / points"


def _parse_dimension(raw: Any, field_name: str) -> Mm | Inches | Pt | None:
    """
    Parse and validate a width/height dimension specification.

    Expected shape::

        {"value": <positive number>, "unit": "<mm|inches|pt>"}

    Returns the appropriate python-docx length object, or ``None`` when
    *raw* itself is ``None``.

    Raises :class:`ValueError` with a human-readable message on every
    validation failure so callers can surface it directly to the user.
    """
    if raw is None:
        return None

    if not isinstance(raw, dict):
        raise ValueError(
            f"'{field_name}' must be an object with 'value' (positive number) "
            f"and 'unit' ({_ACCEPTED_UNITS_DISPLAY}) fields; "
            f"received {type(raw).__name__!r} instead."
        )

    if "value" not in raw:
        raise ValueError(f"'{field_name}' is missing the required 'value' field.")

    raw_value = raw["value"]

    if not isinstance(raw_value, (int, float)):
        raise ValueError(
            f"'{field_name}.value' must be a positive number; "
            f"received {type(raw_value).__name__!r} ({raw_value!r})."
        )

    if isinstance(raw_value, bool):
        # bool is a subclass of int in Python; reject it explicitly.
        raise ValueError(
            f"'{field_name}.value' must be a positive number, not a boolean."
        )

    if raw_value <= 0:
        raise ValueError(
            f"'{field_name}.value' must be strictly positive; "
            f"received {raw_value!r}."
        )

    if "unit" not in raw:
        raise ValueError(
            f"'{field_name}' is missing the required 'unit' field. "
            f"Accepted values: {_ACCEPTED_UNITS_DISPLAY}."
        )

    unit_raw = raw["unit"]

    if not isinstance(unit_raw, str):
        raise ValueError(
            f"'{field_name}.unit' must be a string; "
            f"received {type(unit_raw).__name__!r} ({unit_raw!r})."
        )

    unit_key = unit_raw.strip().lower()
    unit_cls = _UNIT_CLASS_MAP.get(unit_key)

    if unit_cls is None:
        raise ValueError(
            f"'{field_name}.unit' value {unit_raw!r} is not supported. "
            f"Accepted values (case-insensitive): {_ACCEPTED_UNITS_DISPLAY}."
        )

    return unit_cls(raw_value)


def _validate_image_url(url: str) -> None:
    """
    Perform lightweight structural validation of *url*.

    Raises :class:`ValueError` with a descriptive message on failure.
    """
    try:
        parsed = urlparse(url)
    except Exception as exc:
        raise ValueError(f"'_props.url' could not be parsed: {exc}") from exc

    if parsed.scheme not in {"http", "https"}:
        raise ValueError(
            f"'_props.url' must use the http or https scheme; "
            f"received scheme {parsed.scheme!r}."
        )

    if not parsed.netloc:
        raise ValueError("'_props.url' is not valid: the host component is missing.")


def _fetch_image_to_temp(url: str) -> str:
    """
    Download the image at *url* to a fresh temporary file and return its path.

    Enforces :attr:`~app.settings.Settings.MAX_IMAGE_FETCH_TIME` and
    :attr:`~app.settings.Settings.MAX_IMAGE_SIZE` from the application
    settings.

    The caller is responsible for deleting the returned file.  If this
    function raises, the temporary file is guaranteed to have been removed
    before the exception propagates.
    """
    fetch_timeout = settings.MAX_IMAGE_FETCH_TIME
    max_size = settings.MAX_IMAGE_SIZE

    temp_fd, temp_path = tempfile.mkstemp(prefix="docgen_img_")
    # Close the raw file descriptor immediately; we will reopen via open().
    os.close(temp_fd)

    try:
        timeout = httpx.Timeout(
            connect=min(fetch_timeout, 5) if fetch_timeout else 5.0,
            read=float(fetch_timeout) if fetch_timeout else None,
            write=5.0,
            pool=5.0,
        )

        with httpx.Client(
            timeout=timeout, follow_redirects=True, max_redirects=5
        ) as client:
            with client.stream("GET", url) as response:
                # Surface HTTP-level errors before reading the body.
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise ValueError(
                        f"Image server returned HTTP {exc.response.status_code} "
                        f"for URL {url!r}."
                    ) from exc

                # Honour Content-Length as an early size gate.
                content_length_header = response.headers.get("content-length")
                if content_length_header is not None and max_size is not None:
                    try:
                        declared_size = int(content_length_header)
                    except ValueError:
                        declared_size = None

                    if declared_size is not None and declared_size > max_size:
                        max_mb = max_size / (1024 * 1024)
                        declared_mb = declared_size / (1024 * 1024)
                        raise ValueError(
                            f"Image at {url!r} reports Content-Length of "
                            f"{declared_mb:.1f} MiB which exceeds the "
                            f"{max_mb:.1f} MiB limit."
                        )

                downloaded = 0
                with open(temp_path, "wb") as fh:
                    for chunk in response.iter_bytes(chunk_size=65_536):
                        downloaded += len(chunk)
                        if max_size is not None and downloaded > max_size:
                            max_mb = max_size / (1024 * 1024)
                            raise ValueError(
                                f"Image download from {url!r} exceeded the "
                                f"{max_mb:.1f} MiB size limit after "
                                f"{downloaded} bytes."
                            )
                        fh.write(chunk)

        if downloaded == 0:
            raise ValueError(
                f"Image server at {url!r} returned an empty response body."
            )

    except Exception:
        # Guarantee the temp file is removed before re-raising.
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except OSError:
            pass
        raise

    return temp_path


def _create_image(
    config: dict[str, Any],
    doc: DocxTemplate,
    temp_image_paths: list[str],
) -> InlineImage:
    """
    Build a :class:`docxtpl.InlineImage` from an ``_type: "image"`` descriptor.

    *temp_image_paths* is a mutable list maintained by
    :func:`_render_document_worker`.  Every temporary file successfully
    created is appended to it so the worker can clean up unconditionally in
    its ``finally`` block, even when the process is terminated abnormally.

    Raises :class:`ValueError` with actionable messages on validation errors.
    """
    props = config.get("_props")

    if props is None:
        raise ValueError(
            "Image object is missing the '_props' field. "
            "Expected: {'_props': {'url': '...', 'width': ..., 'height': ...}}"
        )

    if not isinstance(props, dict):
        raise ValueError(
            f"Image '_props' must be an object; "
            f"received {type(props).__name__!r} instead."
        )

    url = props.get("url")

    if url is None:
        raise ValueError("Image '_props.url' is required.")

    if not isinstance(url, str):
        raise ValueError(
            f"Image '_props.url' must be a string; "
            f"received {type(url).__name__!r} ({url!r})."
        )

    url = url.strip()
    if not url:
        raise ValueError("Image '_props.url' must not be an empty string.")

    _validate_image_url(url)

    width = _parse_dimension(props.get("width"), "width")
    height = _parse_dimension(props.get("height"), "height")

    # _fetch_image_to_temp raises with a descriptive ValueError on failure and
    # guarantees no file is left behind.  Once it returns successfully the path
    # is registered in temp_image_paths so the worker's finally block handles
    # cleanup from this point forward.
    image_path = _fetch_image_to_temp(url)
    temp_image_paths.append(image_path)

    kwargs: dict[str, Any] = {"image_descriptor": image_path}
    if width is not None:
        kwargs["width"] = width
    if height is not None:
        kwargs["height"] = height

    return InlineImage(doc, **kwargs)


def _extract_rich_text_params(obj: dict[str, Any], doc: DocxTemplate) -> dict[str, Any]:
    """
    Extract RichText formatting parameters from object config.
    Handles special cases like url_id for hyperlinks.
    """
    params: dict[str, Any] = {}

    supported_params = [
        "style",
        "color",
        "highlight",
        "size",
        "bold",
        "italic",
        "underline",
        "strike",
        "font",
        "subscript",
        "superscript",
        "rtl",
        "lang",
    ]

    for param in supported_params:
        if param in obj:
            params[param] = obj[param]

    if "url" in obj:
        params["url_id"] = doc.build_url_id(obj["url"])
    elif "url_id" in obj:
        params["url_id"] = obj["url_id"]

    return params


def _create_rich_text(config: dict[str, Any], doc: DocxTemplate) -> RichText:
    """
    Create a :class:`docxtpl.RichText` object from a configuration dict.

    Expected shape::

        {
            "_type": "rich_text",
            "_objects": [
                {"text": "Hello", "bold": True},
                {"text": "World", "italic": True, "url": "http://example.com"}
            ]
        }
    """
    objects = config.get("_objects", [])
    if not objects:
        return RichText()

    first_obj = objects[0]
    text = first_obj.get("text", "")

    if isinstance(text, dict) and text.get("_type") == "rich_text":
        rt: RichText = _create_rich_text(text, doc)
    else:
        params = _extract_rich_text_params(first_obj, doc)
        rt = RichText(text, **params)

    for obj in objects[1:]:
        text = obj.get("text", "")
        if isinstance(text, dict) and text.get("_type") == "rich_text":
            nested_rt = _create_rich_text(text, doc)
            rt.add(nested_rt)
        else:
            params = _extract_rich_text_params(obj, doc)
            rt.add(text, **params)

    return rt


def _create_rich_text_paragraph(
    config: dict[str, Any], doc: DocxTemplate
) -> RichTextParagraph:
    """
    Create a :class:`docxtpl.RichTextParagraph` from a configuration dict.

    Expected shape::

        {
            "_type": "rich_text_paragraph",
            "_objects": [
                {"text": {"_type": "rich_text", ...}, "parastyle": "Heading1"},
                {"text": "plain text"}
            ]
        }
    """
    rtp = RichTextParagraph()

    for obj in config.get("_objects", []):
        text: dict[str, Any] | str = obj.get("text", "")
        parastyle = obj.get("parastyle")

        if isinstance(text, dict) and text.get("_type") == "rich_text":
            rt: RichText = _create_rich_text(text, doc)
        elif isinstance(text, str):
            rt = RichText(text)
        else:
            continue

        if parastyle:
            rtp.add(rt, parastyle=parastyle)
        else:
            rtp.add(rt)

    return rtp


def _transform_context_objects(
    context: dict[str, Any],
    doc: DocxTemplate,
    temp_image_paths: list[str],
) -> dict[str, Any]:
    """
    Recursively walk *context* and replace structured object descriptors with
    their corresponding python-docx / docxtpl instances.

    Supported ``_type`` values: ``"rich_text"``, ``"rich_text_paragraph"``,
    ``"image"``.

    *temp_image_paths* is passed through to :func:`_create_image` so that
    every temporary image file created during the traversal is registered for
    deferred cleanup by the caller.
    """

    def transform_value(value: Any) -> Any:
        if isinstance(value, dict):
            value_type = value.get("_type")
            if value_type == "rich_text":
                return _create_rich_text(value, doc)
            elif value_type == "rich_text_paragraph":
                return _create_rich_text_paragraph(value, doc)
            elif value_type == "image":
                return _create_image(value, doc, temp_image_paths)
            else:
                return {k: transform_value(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [transform_value(item) for item in value]
        return value

    return {k: transform_value(v) for k, v in context.items()}


def _get_template_variables_worker(docx_path: str) -> set[str]:
    """
    Worker: extract undeclared Jinja2 variables from *docx_path*.
    Executed inside a resource-limited child process.
    """
    doc = DocxTemplate(docx_path)
    variables: set[str] = doc.get_undeclared_template_variables(jinja_env)
    return variables


def get_template_variables(document: DriveFile) -> set[str]:
    """
    Return the set of undeclared variable names present in *document*'s
    template.  The extraction runs inside a resource-limited subprocess.
    """
    docx_path = download_docx_document(document)

    try:
        return run_with_limits(_get_template_variables_worker, docx_path, timeout=30)
    finally:
        if os.path.exists(docx_path):
            os.remove(docx_path)


def _render_document_worker(
    docx_path: str,
    context: dict[str, Any],
) -> str:
    """
    Worker: render the docxtpl template at *docx_path* with *context* and
    return the path to the rendered ``.docx`` file.

    Executed inside a resource-limited child process.  All temporary image
    files created during context transformation are collected in
    ``temp_image_paths`` and deleted in the ``finally`` block, ensuring
    cleanup even when an exception is raised mid-rendering.  Note that if the
    OS forcibly kills the process (e.g. OOM) the ``finally`` block will not
    run; this is an unavoidable limitation of the subprocess isolation model
    and is acceptable because the OS will reclaim the file-system resources
    when the process's file descriptors are closed.
    """
    doc = DocxTemplate(docx_path)
    temp_image_paths: list[str] = []

    try:
        enriched_context = _transform_context_objects(context, doc, temp_image_paths)
        doc.render(enriched_context, jinja_env, autoescape=True)

        rendered_fd, rendered_path = tempfile.mkstemp(suffix=".docx")
        os.close(rendered_fd)
        doc.save(rendered_path)

        return rendered_path

    finally:
        # Always attempt to remove every image temp file, regardless of whether
        # rendering succeeded or failed.  Errors during removal are suppressed
        # so they cannot mask the original exception.
        for path in temp_image_paths:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass


def download_docx_document(document: DriveFile) -> str:
    """
    Download *document* from Google Drive as a ``.docx`` file.

    The caller is responsible for deleting the returned path.

    Raises :class:`~app.services.resource_limits.ResourceLimitError` when
    the file exceeds :attr:`~app.settings.Settings.MAX_FILE_DOWNLOAD_SIZE`.
    """
    validate_file_size(document.size)

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

        if document.mime_type in {
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.google-apps.document",
        }:
            docx_path = temp_path
            temp_path = None  # ownership transferred to caller
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
    Download the template in *format* without filling any variables.

    For Google Docs, a direct export is used when possible (PDF/DOCX) to
    avoid unnecessary LibreOffice round-trips.

    The caller is responsible for deleting the returned path.
    """
    validate_file_size(document.size)

    if document.mime_type == "application/vnd.google-apps.document":
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
        docx_path = download_docx_document(document)

        if format == DocumentResponseFormat.DOCX:
            return docx_path

        try:
            return convert_file(docx_path, format.value)
        finally:
            if os.path.exists(docx_path):
                os.remove(docx_path)


async def get_document_variables_info(
    document: DriveFile,
    user_id: PydanticObjectId | None = None,
    file_parent: str | None = None,
) -> tuple[set[str], dict[str, dict[str, Any]]]:
    """
    Return ``(template_variables, variables_info)`` for *document*.

    *variables_info* maps each variable name to its database configuration
    (value, schema, required flag, saved value, …).
    """
    template_variables = get_template_variables(document)

    variables_info = await get_effective_variables_for_document(
        document.id, template_variables, user_id, file_parent
    )

    return template_variables, variables_info


async def validate_variables_for_document(
    document: DriveFile,
    user_variables: dict[str, Any],
    user_id: PydanticObjectId | None = None,
    bypass_validation: bool = False,
) -> None:
    """
    Validate *user_variables* against the template's variable definitions.

    Raises :class:`~app.exceptions.ValidationErrorsException` when one or
    more variables fail validation.  Does nothing when *bypass_validation* is
    ``True``.
    """
    if bypass_validation:
        return

    template_variables = get_template_variables(document)

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
    Generate a filled document and return ``(output_path, final_context)``.

    The output file must be deleted by the caller (typically via a FastAPI
    background task).
    """
    docx_path = download_docx_document(document)
    rendered_path: str | None = None

    try:
        template_variables = run_with_limits(
            _get_template_variables_worker, docx_path, timeout=30
        )

        context = await resolve_variables_for_generation(
            document.id,
            template_variables,
            user_variables,
            user_id,
            bypass_validation,
        )

        rendered_path = run_with_limits(
            _render_document_worker, docx_path, context, timeout=30
        )

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
    """Raise :class:`~fastapi.HTTPException` 422 when too many variables are supplied."""
    if len(variables) > settings.MAX_DOCUMENT_VARIABLES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Documents cannot have more than "
                f"{settings.MAX_DOCUMENT_VARIABLES} variables."
            ),
        )


def validate_document_mime_type(mime_type: str) -> None:
    """Raise :class:`~fastapi.HTTPException` 415 for unsupported MIME types."""
    if mime_type not in DOC_COMPATIBLE_MIME_TYPES:
        raise HTTPException(
            status_code=415,
            detail="Requested document mime type not supported.",
        )


def resolve_format(
    accept: str | None,
    format: DocumentResponseFormat | None,
) -> DocumentResponseFormat:
    """
    Determine the response format from the ``Accept`` header or explicit query
    parameter, falling back to PDF.
    """
    if accept:
        for mime in accept.split(","):
            mime = mime.split(";")[0].strip()
            if mime in MIME_TO_FORMAT:
                return MIME_TO_FORMAT[mime]

    if format:
        return format

    return DocumentResponseFormat.PDF
