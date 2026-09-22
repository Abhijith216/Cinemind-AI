"""Tests for the health endpoint. No Postgres required: the endpoint degrades gracefully."""

from fastapi.testclient import TestClient

from cinemind.main import app


def test_health_returns_ok() -> None:
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == "0.1.0"
    # database may be "up" or "down" depending on the environment
    assert body["database"] in {"up", "down"}


def test_health_openapi_contract() -> None:
    client = TestClient(app)
    schema = client.get("/openapi.json").json()
    assert "/api/health" in schema["paths"]
    assert schema["paths"]["/api/health"]["get"]["responses"]["200"] is not None
