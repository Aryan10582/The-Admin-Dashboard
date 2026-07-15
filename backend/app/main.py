from uuid import uuid4
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.errors import register_exception_handlers
from app.core.http_security import apply_security_headers, validate_state_changing_origin
from app.core.logging import configure_logging
from app.core.product_secrets import validate_product_secret_encryption_key
from app.core.security import hash_password
from app.models.admin import Admin


def seed_admin(db: Session) -> None:
    if not settings.admin_email or not settings.admin_password:
        return
    existing_admin = db.scalar(select(Admin).limit(1))
    if existing_admin:
        return
    admin = Admin(
        email=settings.admin_email,
        username=settings.admin_email.split("@")[0],
        password_hash=hash_password(settings.admin_password),
        is_active=True,
    )
    db.add(admin)
    db.commit()


def create_app() -> FastAPI:
    configure_logging()
    settings.validate_security_settings()
    validate_product_secret_encryption_key()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        with SessionLocal() as db:
            seed_admin(db)
        yield

    app = FastAPI(
        title=settings.app_name,
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        openapi_url=None if settings.is_production else "/openapi.json",
    )

    if settings.trusted_hosts:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def security_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid4()))
        request.state.request_id = request_id
        csrf_response = validate_state_changing_origin(request)
        if csrf_response is not None:
            csrf_response.headers["X-Request-ID"] = request_id
            return apply_security_headers(csrf_response)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return apply_security_headers(response)

    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.api_v1_prefix)
    return app


app = create_app()
