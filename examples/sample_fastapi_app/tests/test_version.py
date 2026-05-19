from app.main import app
from fastapi.testclient import TestClient


def test_version_endpoint() -> None:
    client = TestClient(app)

    response = client.get("/version")

    assert response.status_code == 200
    assert response.json() == {"version": "0.1.0"}
