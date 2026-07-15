from urllib.parse import urlsplit

from fastapi import Request, status
from fastapi.responses import JSONResponse, Response

from app.core.config import settings


UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _origin_allowed(origin: str | None) -> bool:
    return bool(origin and origin in settings.cors_origins)


def _referer_origin(referer: str | None) -> str | None:
    if not referer:
        return None
    parsed = urlsplit(referer)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def _csrf_rejection(request: Request) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content={
            "success": False,
            "error": {
                "code": "csrf_origin_rejected",
                "message": "State-changing request origin is not trusted",
                "request_id": getattr(request.state, "request_id", None),
            },
        },
    )


def validate_state_changing_origin(request: Request) -> JSONResponse | None:
    if request.method.upper() not in UNSAFE_METHODS:
        return None

    origin = request.headers.get("origin")
    referer_origin = _referer_origin(request.headers.get("referer"))
    has_cookie = bool(request.headers.get("cookie"))

    if origin and not _origin_allowed(origin):
        return _csrf_rejection(request)
    if not origin and referer_origin and not _origin_allowed(referer_origin):
        return _csrf_rejection(request)
    if settings.is_production and has_cookie and not origin and not referer_origin:
        return _csrf_rejection(request)
    return None


def apply_security_headers(response: Response) -> Response:
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if settings.is_production:
        response.headers.setdefault("Cache-Control", "no-store")
        if settings.cookie_secure:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response
