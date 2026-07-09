from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.core.config import settings


serializer = URLSafeTimedSerializer(settings.session_secret, salt="admin-session")


def create_session_token(admin_id: UUID) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.session_expire_minutes)
    return serializer.dumps({"admin_id": str(admin_id), "expires_at": expires_at.isoformat()})


def decode_session_token(token: str) -> UUID | None:
    try:
        payload = serializer.loads(token, max_age=settings.session_expire_minutes * 60)
    except (BadSignature, SignatureExpired):
        return None
    expires_at = datetime.fromisoformat(payload["expires_at"])
    if expires_at < datetime.now(timezone.utc):
        return None
    return UUID(payload["admin_id"])


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        max_age=settings.session_expire_minutes * 60,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=settings.session_cookie_name, path="/")
