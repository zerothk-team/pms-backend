from datetime import datetime, timezone

from fastapi import Request
from fastapi.responses import JSONResponse


class NotFoundException(Exception):
    def __init__(self, detail: str = "Resource not found") -> None:
        self.detail = detail
        self.code = "NOT_FOUND"


class ConflictException(Exception):
    def __init__(self, detail: str = "Resource already exists") -> None:
        self.detail = detail
        self.code = "CONFLICT"


class ForbiddenException(Exception):
    def __init__(self, detail: str = "Access denied") -> None:
        self.detail = detail
        self.code = "FORBIDDEN"


class UnauthorisedException(Exception):
    def __init__(self, detail: str = "Invalid or expired token") -> None:
        self.detail = detail
        self.code = "UNAUTHORISED"


class ValidationException(Exception):
    def __init__(self, detail: str = "Validation error") -> None:
        self.detail = detail
        self.code = "VALIDATION_ERROR"


class BadRequestException(Exception):
    def __init__(self, detail: str = "Bad request") -> None:
        self.detail = detail
        self.code = "BAD_REQUEST"


def _error_response(detail: str, code: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "detail": detail,
            "code": code,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


async def not_found_handler(request: Request, exc: NotFoundException) -> JSONResponse:
    return _error_response(exc.detail, exc.code, 404)


async def conflict_handler(request: Request, exc: ConflictException) -> JSONResponse:
    return _error_response(exc.detail, exc.code, 409)


async def forbidden_handler(request: Request, exc: ForbiddenException) -> JSONResponse:
    return _error_response(exc.detail, exc.code, 403)


async def unauthorised_handler(request: Request, exc: UnauthorisedException) -> JSONResponse:
    return _error_response(exc.detail, exc.code, 401)


async def validation_handler(request: Request, exc: ValidationException) -> JSONResponse:
    return _error_response(exc.detail, exc.code, 422)


async def bad_request_handler(request: Request, exc: BadRequestException) -> JSONResponse:
    return _error_response(exc.detail, exc.code, 400)
