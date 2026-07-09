from typing import Any

from pydantic import BaseModel


class ApiResponse(BaseModel):
    success: bool = True
    data: Any | None = None


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str | None = None
