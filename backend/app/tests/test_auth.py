from fastapi.testclient import TestClient


def test_login_fails_with_wrong_credentials(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "wrong-password"},
    )

    assert response.status_code == 401


def test_login_works_with_seeded_admin(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "correct-password"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["admin"]["email"] == "admin@example.com"
    assert "admin_session" in response.cookies


def test_protected_endpoint_rejects_unauthenticated_request(client: TestClient) -> None:
    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401


def test_protected_endpoint_accepts_authenticated_request(client: TestClient) -> None:
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "correct-password"},
    )
    assert login.status_code == 200

    response = client.get("/api/v1/auth/me")

    assert response.status_code == 200
    assert response.json()["data"]["admin"]["email"] == "admin@example.com"
