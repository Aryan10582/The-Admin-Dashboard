from collections.abc import Generator

import pytest
import httpx
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.config import settings
from app.integrations.product_admin_client import ProductAdminClient
from app.main import create_app
from app.schemas.product import ProductDeploymentCreate
from app.tests.conftest import no_lifespan


def login(client: TestClient) -> None:
    response = client.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": "correct-password"})
    assert response.status_code == 200


def product_payload(**overrides) -> dict:
    payload = {
        "product_name": "Security Product",
        "region": "us",
        "environment": "staging",
        "currency": "USD",
        "api_base_url": "https://product.example.com",
        "admin_api_version": "v1",
        "admin_api_secret": "security-secret-value",
    }
    payload.update(overrides)
    return payload


def test_untrusted_origin_cannot_perform_state_changing_request(client: TestClient) -> None:
    login(client)

    response = client.post(
        "/api/v1/products",
        json=product_payload(),
        headers={"Origin": "https://evil.example.com"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_origin_rejected"


def test_trusted_origin_can_perform_state_changing_request(client: TestClient) -> None:
    login(client)
    trusted_origin = settings.cors_origins[0]

    response = client.post(
        "/api/v1/products",
        json=product_payload(),
        headers={"Origin": trusted_origin},
    )

    assert response.status_code == 201


def test_production_cookie_request_without_origin_or_referer_is_rejected(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    login(client)
    monkeypatch.setattr("app.core.http_security.settings.environment", "production")

    response = client.post("/api/v1/products", json=product_payload())

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_origin_rejected"


def test_validation_errors_do_not_echo_sensitive_inputs(client: TestClient) -> None:
    login(client)
    sensitive_secret = "do-not-echo-this-secret"

    response = client.post(
        "/api/v1/products",
        json=product_payload(admin_api_secret=sensitive_secret, token_usage_list_path="https://evil.example.com/usage"),
    )

    assert response.status_code == 422
    assert sensitive_secret not in response.text
    assert "https://evil.example.com/usage" not in response.text


def test_production_rejects_dangerous_product_api_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "product_api_allowed_hosts", [])

    for url in ("http://127.0.0.1:8000", "http://localhost:8000", "http://169.254.169.254/latest/meta-data"):
        with pytest.raises(ValueError):
            ProductDeploymentCreate(**product_payload(api_base_url=url))


def test_production_product_api_host_allowlist_supports_private_deployments(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "product_api_allowed_hosts", ["127.0.0.1"])

    payload = ProductDeploymentCreate(**product_payload(api_base_url="http://127.0.0.1:8000"))

    assert payload.api_base_url == "http://127.0.0.1:8000"


def test_product_client_response_size_guard() -> None:
    client = ProductAdminClient("https://product.example.com", token_usage_list_path="/usage")
    response = httpx.Response(200, content=b"x" * (settings.product_api_response_size_limit_bytes + 1))

    assert client._response_too_large(response) is True


def test_security_headers_are_set(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "same-origin"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "camera=()" in response.headers["Permissions-Policy"]


def test_production_security_settings_reject_unsafe_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "session_secret", "dev-only-change-me")
    monkeypatch.setattr(settings, "cookie_secure", False)
    monkeypatch.setattr(settings, "cors_origins", ["http://localhost:3000"])

    with pytest.raises(ValueError, match="SESSION_SECRET"):
        settings.validate_security_settings()

    monkeypatch.setattr(settings, "session_secret", "x" * 40)
    with pytest.raises(ValueError, match="COOKIE_SECURE"):
        settings.validate_security_settings()

    monkeypatch.setattr(settings, "cookie_secure", True)
    monkeypatch.setattr(settings, "cors_origins", ["*"])
    with pytest.raises(ValueError, match="CORS wildcard"):
        settings.validate_security_settings()


def test_production_session_cookie_uses_secure_flags(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "session_secret", "x" * 40)
    monkeypatch.setattr(settings, "cookie_secure", True)
    monkeypatch.setattr(settings, "cookie_samesite", "strict")
    monkeypatch.setattr(settings, "cors_origins", ["http://localhost:3000"])

    test_app = create_app()
    test_app.router.lifespan_context = no_lifespan

    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    test_app.dependency_overrides[get_db] = override_get_db
    with TestClient(test_app) as test_client:
        response = test_client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "correct-password"},
            headers={"Origin": "http://localhost:3000"},
        )

    assert response.status_code == 200
    set_cookie = response.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "secure" in set_cookie
    assert "samesite=strict" in set_cookie
    assert "max-age=" in set_cookie
