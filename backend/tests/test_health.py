"""Tests for the health endpoints. No Postgres required: they degrade gracefully."""

from fastapi.testclient import TestClient

from app.main import app


def test_health_returns_ok() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == "0.1.0"
    # database may be "up" or "down" depending on the environment
    assert body["database"] in {"up", "down"}


def test_api_health_alias() -> None:
    """The /api/health alias must behave identically."""
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_openapi_contract() -> None:
    client = TestClient(app)
    schema = client.get("/openapi.json").json()
    assert "/health" in schema["paths"]
    assert "/api/health" in schema["paths"]
