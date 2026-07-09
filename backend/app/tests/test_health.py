from fastapi.testclient import TestClient


def test_health_endpoint_works(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"success": True, "data": {"status": "ok"}}
