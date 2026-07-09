from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin
from app.core.database import get_db
from app.core.security import verify_password
from app.core.sessions import clear_session_cookie, create_session_token, set_session_cookie
from app.models.admin import Admin
from app.schemas.auth import AdminPublic, AuthResponse, LoginRequest

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=dict)
async def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)) -> dict:
    admin = db.scalar(
        select(Admin).where(
            Admin.email == payload.email,
            Admin.is_active.is_(True),
        )
    )
    if not admin or not verify_password(payload.password, admin.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    set_session_cookie(response, create_session_token(admin.id))
    return {"success": True, "data": AuthResponse(admin=AdminPublic.model_validate(admin)).model_dump(mode="json")}


@router.post("/logout")
async def logout(response: Response) -> dict:
    clear_session_cookie(response)
    return {"success": True, "data": {"logged_out": True}}


@router.get("/me")
async def me(current_admin: Admin = Depends(get_current_admin)) -> dict:
    return {"success": True, "data": AuthResponse(admin=AdminPublic.model_validate(current_admin)).model_dump(mode="json")}
