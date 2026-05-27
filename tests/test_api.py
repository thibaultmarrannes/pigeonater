from fastapi.testclient import TestClient

from app.main import app, detector, storage
from app.schemas import DetectorSettings


def test_status_endpoint_returns_settings():
    storage.update_settings(DetectorSettings(enabled=False))
    with TestClient(app) as client:
        response = client.get("/api/status")

    assert response.status_code == 200
    body = response.json()
    assert body["settings"]["retention_days"] == storage.get_settings().retention_days
    assert body["model_name"]


def test_page_routes_render():
    storage.update_settings(DetectorSettings(enabled=False))
    with TestClient(app) as client:
        for path in ["/", "/events", "/settings"]:
            response = client.get(path)
            assert response.status_code == 200
            assert "Pigeonater" in response.text


def test_settings_endpoint_validates_payload():
    storage.update_settings(DetectorSettings(enabled=False))
    with TestClient(app) as client:
        response = client.patch(
            "/api/settings",
            json={
                "enabled": False,
                "confidence_threshold": 1.5,
                "cooldown_seconds": 60,
                "retention_days": 7,
            },
        )

    assert response.status_code == 422
    assert detector.worker_running is False
