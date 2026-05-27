import time

from fastapi.testclient import TestClient

from app.main import app, config, detector, storage
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


def test_cameras_endpoint_times_out_quickly(monkeypatch):
    storage.update_settings(DetectorSettings(enabled=False, camera_device="/dev/video0"))
    monkeypatch.setattr(config, "camera_discovery_timeout_seconds", 0.05)

    def slow_camera_discovery(*args, **kwargs):
        time.sleep(0.2)
        return []

    monkeypatch.setattr("app.main.list_camera_devices", slow_camera_discovery)

    start = time.monotonic()
    with TestClient(app) as client:
        response = client.get("/api/cameras")
    elapsed = time.monotonic() - start

    assert response.status_code == 200
    assert elapsed < 0.5
    assert response.json() == [{"path": "/dev/video0", "selected": True, "available": False}]
