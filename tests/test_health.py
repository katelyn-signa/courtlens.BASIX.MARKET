from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_service_status() -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {
        "status": "ok",
        "service": "CourtLens Member 2 - Document Intelligence",
    }
