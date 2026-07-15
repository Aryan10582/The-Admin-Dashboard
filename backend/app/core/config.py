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
    product_api_allowed_hosts: list[str] = Field(default_factory=list)
    product_api_response_size_limit_bytes: int = 1_000_000
    product_secret_encryption_key: str | None = None
    allow_destructive_test_purge: bool = False
    ai_pricing_mock_adapter_enabled: bool = False
    ai_pricing_http_timeout_seconds: float = 5
    ai_pricing_response_size_limit_bytes: int = 250000
    ai_pricing_allowed_hosts: list[str] = Field(default_factory=list)
    trusted_hosts: list[str] = Field(default_factory=list)

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("trusted_hosts", mode="before")
    @classmethod
    def parse_trusted_hosts(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [host.strip() for host in value.split(",") if host.strip()]
        return value

    @field_validator("product_api_allowed_hosts", mode="before")
    @classmethod
    def parse_product_api_allowed_hosts(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [host.strip().lower() for host in value.split(",") if host.strip()]
        return value

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}

    def validate_security_settings(self) -> None:
        if "*" in self.cors_origins:
            raise ValueError("CORS wildcard origins cannot be used with credentialed admin cookies")
        if self.is_production:
            if self.session_secret == "dev-only-change-me" or len(self.session_secret) < 32:
                raise ValueError("SESSION_SECRET must be set to a strong non-default value in production")
            if not self.cookie_secure:
                raise ValueError("COOKIE_SECURE must be true in production")
            if self.cookie_samesite.lower() not in {"lax", "strict"}:
                raise ValueError("COOKIE_SAMESITE must be lax or strict in production")
            if not self.cors_origins:
                raise ValueError("CORS_ORIGINS must explicitly list trusted frontend origins in production")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
