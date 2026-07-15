from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import AuditResultStatus, ProductHealthStatus
from app.core.product_secrets import ProductSecretEncryptionError, decrypt_product_secret, encrypt_product_secret, validate_product_secret_encryption_key
from app.integrations.product_admin_client import ProductHealthResult
from app.models.audit import AuditLog
from app.models.failure_log import FailureLog
from app.models.product import ProductDeployment


def login(client: TestClient) -> None:
    response = client.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": "correct-password"})
    assert response.status_code == 200


def product_payload(**overrides) -> dict:
    payload = {
        "product_name": "Core CRM",
        "region": "us-east",
        "environment": "staging",
        "currency": "usd",
        "api_base_url": "https://product.example.com/",
        "health_check_url": "https://product.example.com/health/",
        "admin_api_version": "v1",
        "is_active": True,
        "is_under_maintenance": False,
        "admin_api_secret": "super-secret-token",
    }
    payload.update(overrides)
    return payload


def create_product(client: TestClient, **overrides) -> dict:
    response = client.post("/api/v1/products", json=product_payload(**overrides))
    assert response.status_code == 201
    return response.json()["data"]


class StubProductClient:
    def __init__(self, result: ProductHealthResult) -> None:
        self.result = result

    async def health_check(self) -> ProductHealthResult:
        return self.result


def stub_health(monkeypatch, result: ProductHealthResult) -> None:
    def build_client(product: ProductDeployment, api_secret: str | None = None) -> StubProductClient:
        assert api_secret == "super-secret-token"
        return StubProductClient(result)

    monkeypatch.setattr("app.services.product_service.build_product_client", build_client)


def test_product_endpoints_require_authentication(client: TestClient) -> None:
    assert client.get("/api/v1/products").status_code == 401
    assert client.post("/api/v1/products", json=product_payload()).status_code == 401
    assert client.get(f"/api/v1/products/{UUID(int=0)}").status_code == 401
    assert client.patch(f"/api/v1/products/{UUID(int=0)}", json={"product_name": "Updated"}).status_code == 401
    assert client.post(f"/api/v1/products/{UUID(int=0)}/health-check").status_code == 401


def test_product_create_list_detail_and_update_work(client: TestClient, db_session: Session) -> None:
    login(client)
    created = create_product(client, token_usage_list_path="/api/v1/admin/ai-usage")

    assert created["product_name"] == "Core CRM"
    assert created["currency"] == "USD"
    assert created["api_base_url"] == "https://product.example.com"
    assert created["health_check_url"] == "https://product.example.com/health"
    assert created["token_usage_list_path"] == "/api/v1/admin/ai-usage"
    assert created["token_usage_configured"] is True
    assert created["ai_usage_sync_configured"] is True
    assert created["secret_configured"] is True
    assert "admin_api_secret" not in created

    list_response = client.get("/api/v1/products")
    assert list_response.status_code == 200
    assert list_response.json()["data"][0]["id"] == created["id"]
    assert list_response.json()["data"][0]["token_usage_list_path"] == "/api/v1/admin/ai-usage"
    assert list_response.json()["data"][0]["ai_usage_sync_configured"] is True

    detail_response = client.get(f"/api/v1/products/{created['id']}")
    assert detail_response.status_code == 200
    assert detail_response.json()["data"]["id"] == created["id"]
    assert detail_response.json()["data"]["token_usage_list_path"] == "/api/v1/admin/ai-usage"

    update_response = client.patch(
        f"/api/v1/products/{created['id']}",
        json={"product_name": "Core CRM Updated", "is_active": False, "token_usage_list_path": "/internal/admin/token-usage"},
    )
    assert update_response.status_code == 200
    updated = update_response.json()["data"]
    assert updated["product_name"] == "Core CRM Updated"
    assert updated["is_active"] is False
    assert updated["token_usage_list_path"] == "/internal/admin/token-usage"

    clear_response = client.patch(f"/api/v1/products/{created['id']}", json={"token_usage_list_path": None})
    assert clear_response.status_code == 200
    assert clear_response.json()["data"]["token_usage_list_path"] is None
    assert clear_response.json()["data"]["ai_usage_sync_configured"] is False

    audit_actions = db_session.scalars(select(AuditLog.action).order_by(AuditLog.created_at)).all()
    assert "product.created" in audit_actions
    assert "product.updated" in audit_actions


def test_product_create_without_token_usage_path_remains_valid(client: TestClient) -> None:
    login(client)
    created = create_product(client)
    assert created["token_usage_list_path"] is None
    assert created["token_usage_configured"] is False
    assert created["ai_usage_sync_configured"] is False


def test_unsafe_token_usage_paths_are_rejected(client: TestClient) -> None:
    login(client)
    unsafe_paths = [
        "https://other-domain.com/usage",
        "http://other-domain.com/usage",
        "//other-domain.com/usage",
        "../usage",
        "/api/../private",
        "/api/%2e%2e/private",
        "user:password@example.com/usage",
        "javascript:alert(1)",
        "data:text/plain,test",
        "/api/v1/admin/ai-usage?cursor=stored",
        "/api/v1/admin/ai-usage#fragment",
        "/api/v1/admin/ai-usage\x00",
    ]
    for path in unsafe_paths:
        response = client.post("/api/v1/products", json=product_payload(token_usage_list_path=path))
        assert response.status_code == 422, path


def test_secrets_are_encrypted_never_returned_or_logged_and_patch_preserves_secret(
    client: TestClient,
    db_session: Session,
    caplog,
) -> None:
    login(client)
    created = create_product(client)

    raw_create_response = client.get(f"/api/v1/products/{created['id']}").text
    assert "super-secret-token" not in raw_create_response
    assert "admin_api_secret" not in raw_create_response

    client.patch(f"/api/v1/products/{created['id']}", json={"region": "eu-west"})
    product = db_session.get(ProductDeployment, UUID(created["id"]))
    assert product is not None
    assert product.admin_api_secret_encrypted != "super-secret-token"
    assert decrypt_product_secret(product.admin_api_secret_encrypted) == "super-secret-token"

    empty_secret_response = client.patch(f"/api/v1/products/{created['id']}", json={"admin_api_secret": ""})
    assert empty_secret_response.status_code == 422

    client.patch(f"/api/v1/products/{created['id']}", json={"admin_api_secret": None})
    db_session.refresh(product)
    assert decrypt_product_secret(product.admin_api_secret_encrypted) == "super-secret-token"

    client.patch(f"/api/v1/products/{created['id']}", json={"admin_api_secret": "replacement-secret"})
    db_session.refresh(product)
    assert product.admin_api_secret_encrypted != "replacement-secret"
    assert decrypt_product_secret(product.admin_api_secret_encrypted) == "replacement-secret"

    audit_logs = db_session.scalars(select(AuditLog)).all()
    for audit_log in audit_logs:
        assert "super-secret-token" not in str(audit_log.old_value)
        assert "super-secret-token" not in str(audit_log.new_value)
        assert "super-secret-token" not in str(audit_log.failure_message)
        assert "replacement-secret" not in str(audit_log.old_value)
        assert "replacement-secret" not in str(audit_log.new_value)
        assert "replacement-secret" not in str(audit_log.failure_message)

    for log_record in caplog.records:
        assert "super-secret-token" not in log_record.getMessage()
        assert "replacement-secret" not in log_record.getMessage()


def test_secret_configured_is_false_when_secret_is_omitted(client: TestClient) -> None:
    login(client)
    created = create_product(client, admin_api_secret=None)
    assert created["secret_configured"] is False


def test_product_client_receives_decrypted_secret(client: TestClient, db_session: Session, monkeypatch) -> None:
    login(client)
    created = create_product(client)
    captured = {}

    def build_client(product: ProductDeployment, api_secret: str | None = None) -> StubProductClient:
        captured["api_secret"] = api_secret
        return StubProductClient(ProductHealthResult(is_success=True, response_time_ms=40, status_code=200))

    monkeypatch.setattr("app.services.product_service.build_product_client", build_client)
    response = client.post(f"/api/v1/products/{created['id']}/health-check")

    assert response.status_code == 200
    assert captured["api_secret"] == "super-secret-token"
    product = db_session.get(ProductDeployment, UUID(created["id"]))
    assert product is not None
    assert product.admin_api_secret_encrypted != "super-secret-token"


def test_invalid_or_missing_encryption_key_fails_safely(monkeypatch) -> None:
    monkeypatch.setattr("app.core.product_secrets.settings.product_secret_encryption_key", None)
    try:
        validate_product_secret_encryption_key()
        raise AssertionError("missing key should fail")
    except ProductSecretEncryptionError as exc:
        assert "required" in str(exc)

    try:
        encrypt_product_secret("super-secret-token")
        raise AssertionError("missing key should fail on write")
    except ProductSecretEncryptionError as exc:
        assert "super-secret-token" not in str(exc)

    monkeypatch.setattr("app.core.product_secrets.settings.product_secret_encryption_key", "not-a-valid-fernet-key")
    try:
        validate_product_secret_encryption_key()
        raise AssertionError("invalid key should fail")
    except ProductSecretEncryptionError as exc:
        assert "invalid" in str(exc)
        assert "not-a-valid-fernet-key" not in str(exc)


def run_health_case(
    client: TestClient,
    db_session: Session,
    monkeypatch,
    result: ProductHealthResult,
    expected_status: ProductHealthStatus,
    *,
    maintenance: bool = False,
) -> ProductDeployment:
    login(client)
    created = create_product(client, is_under_maintenance=maintenance)
    stub_health(monkeypatch, result)

    response = client.post(f"/api/v1/products/{created['id']}/health-check")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["health_status"] == expected_status.value

    product = db_session.get(ProductDeployment, UUID(created["id"]))
    assert product is not None
    assert product.health_status == expected_status
    assert product.last_checked_at is not None
    return product


def test_fast_success_becomes_healthy(client: TestClient, db_session: Session, monkeypatch) -> None:
    product = run_health_case(
        client,
        db_session,
        monkeypatch,
        ProductHealthResult(is_success=True, response_time_ms=50, status_code=200),
        ProductHealthStatus.healthy,
    )
    assert product.last_health_response_time_ms == 50
    assert product.last_successful_health_check_at is not None
    assert product.last_error_message is None


def test_slow_success_becomes_slow(client: TestClient, db_session: Session, monkeypatch) -> None:
    product = run_health_case(
        client,
        db_session,
        monkeypatch,
        ProductHealthResult(is_success=True, response_time_ms=2500, status_code=200),
        ProductHealthStatus.slow,
    )
    assert product.last_health_response_time_ms == 2500


def test_timeout_becomes_not_responding(client: TestClient, db_session: Session, monkeypatch) -> None:
    product = run_health_case(
        client,
        db_session,
        monkeypatch,
        ProductHealthResult(
            is_success=False,
            response_time_ms=None,
            error_category="timeout",
            error_message="Product health check timed out",
        ),
        ProductHealthStatus.not_responding,
    )
    assert product.last_error_message == "Product health check timed out"


def test_connection_and_non_2xx_failures_become_down(
    client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    for make_result in (
        lambda: ProductHealthResult(
            is_success=False,
            response_time_ms=None,
            error_category="connection_error",
            error_message="Could not connect to product health endpoint",
        ),
        lambda: ProductHealthResult(
            is_success=False,
            response_time_ms=80,
            status_code=503,
            error_category="http_error",
            error_message="Product health endpoint returned HTTP 503",
        ),
    ):
        product = run_health_case(client, db_session, monkeypatch, make_result(), ProductHealthStatus.down)
        assert product.last_error_message is not None


def test_maintenance_mode_remains_under_maintenance(client: TestClient, db_session: Session, monkeypatch) -> None:
    product = run_health_case(
        client,
        db_session,
        monkeypatch,
        ProductHealthResult(is_success=True, response_time_ms=30, status_code=200),
        ProductHealthStatus.under_maintenance,
        maintenance=True,
    )
    assert product.last_error_message is None


def test_health_checks_create_audit_logs_and_failures_create_failure_logs(
    client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    product = run_health_case(
        client,
        db_session,
        monkeypatch,
        ProductHealthResult(
            is_success=False,
            response_time_ms=120,
            status_code=500,
            error_category="http_error",
            error_message="Product health endpoint returned HTTP 500",
        ),
        ProductHealthStatus.down,
    )

    audit_log = db_session.scalar(
        select(AuditLog).where(AuditLog.action == "product.health_check", AuditLog.product_deployment_id == product.id)
    )
    assert audit_log is not None
    assert audit_log.result_status == AuditResultStatus.failure
    assert audit_log.new_value["health_status"] == "down"
    assert audit_log.new_value["response_time_ms"] == 120

    failure_log = db_session.scalar(select(FailureLog).where(FailureLog.product_deployment_id == product.id))
    assert failure_log is not None
    assert failure_log.action_attempted == "product.health_check"
    assert failure_log.error_code == "http_error"
    assert "HTTP 500" in failure_log.error_message
