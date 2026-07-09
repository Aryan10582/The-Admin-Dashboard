from uuid import UUID

from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class AdminPublic(BaseModel):
    id: UUID
    email: EmailStr
    username: str | None = None

    model_config = {"from_attributes": True}


class AuthResponse(BaseModel):
    admin: AdminPublic
