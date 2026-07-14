from functools import lru_cache

from pydantic import AnyHttpUrl, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Admin Dashboard"
    environment: str = "development"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "sqlite:///./admin_dashboard.db"

    admin_email: str | None = None
    admin_password: str | None = None

    session_secret: str = "dev-only-change-me"
    session_cookie_name: str = "admin_session"
    session_expire_minutes: int = 60 * 12
    cookie_secure: bool = False
    cookie_samesite: str = "lax"

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    product_health_timeout_seconds: float = 10
    product_health_slow_threshold_ms: int = 2000
    product_secret_encryption_key: str | None = None
    allow_destructive_test_purge: bool = False

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
