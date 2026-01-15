from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


class ValidationErrorsException(Exception):
    def __init__(self, errors: dict[str, Any]):
        self.errors = errors
        super().__init__(errors)


async def document_validation_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"detail": {"error_type": exc.__class__.__name__, "error": str(exc)}},
    )
