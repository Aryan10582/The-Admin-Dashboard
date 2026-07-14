from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.product_secrets import ProductSecretEncryptionError


def error_response(message: str, code: str, status_code: int, request_id: str | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "error": {
                "code": code,
                "message": message,
                "request_id": request_id,
            },
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return error_response(str(exc.detail), "http_error", exc.status_code, getattr(request.state, "request_id", None))

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "success": False,
                "error": {
                    "code": "validation_error",
                    "message": "Request validation failed",
                    "details": jsonable_encoder(exc.errors()),
                    "request_id": getattr(request.state, "request_id", None),
                },
            },
        )

    @app.exception_handler(ProductSecretEncryptionError)
    async def product_secret_exception_handler(request: Request, exc: ProductSecretEncryptionError) -> JSONResponse:
        return error_response(str(exc), "product_secret_encryption_error", 500, getattr(request.state, "request_id", None))

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        return error_response("Internal server error", "internal_server_error", 500, getattr(request.state, "request_id", None))
