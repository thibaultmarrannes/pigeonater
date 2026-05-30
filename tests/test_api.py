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
    assert "audio_ready" in body


def test_version_endpoint_returns_version():
    with TestClient(app) as client:
        response = client.get("/api/version")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"version", "commit", "build_date"}
    assert body["version"]


def test_stream_endpoint_returns_event_stream():
    storage.update_settings(DetectorSettings(enabled=False))
    with TestClient(app) as client:
        response = client.get("/api/stream?limit=2&once=true")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: update" in response.text
    assert '"status"' in response.text
    assert '"events"' in response.text


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


def test_audio_devices_endpoint_times_out_quickly(monkeypatch):
    storage.update_settings(DetectorSettings(enabled=False, output_device="auto"))
    monkeypatch.setattr(config, "audio_discovery_timeout_seconds", 0.05)

    def slow_audio_discovery(*args, **kwargs):
        time.sleep(0.2)
        return []

    monkeypatch.setattr("app.main.list_audio_output_devices", slow_audio_discovery)

    start = time.monotonic()
    with TestClient(app) as client:
        response = client.get("/api/audio/devices")
    elapsed = time.monotonic() - start

    assert response.status_code == 200
    assert elapsed < 0.5
    assert response.json() == [{"id": "auto", "name": "auto", "selected": True, "available": False}]


def test_audio_test_beep_endpoint(monkeypatch):
    storage.update_settings(DetectorSettings(enabled=False, output_device="auto"))

    def fake_beep(output_device):
        from app.audio import TestBeepResult

        return TestBeepResult(ok=True)

    monkeypatch.setattr("app.main.play_test_beep", fake_beep)
    monkeypatch.setattr(detector, "refresh_audio_status", fake_async_refresh)

    with TestClient(app) as client:
        response = client.post("/api/audio/test-beep")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_audio_test_beep_endpoint_reports_failure(monkeypatch):
    storage.update_settings(DetectorSettings(enabled=False, output_device="auto"))

    def fake_beep(output_device):
        from app.audio import TestBeepResult

        return TestBeepResult(ok=False, error="beep failed")

    monkeypatch.setattr("app.main.play_test_beep", fake_beep)

    with TestClient(app) as client:
        response = client.post("/api/audio/test-beep")

    assert response.status_code == 503
    assert response.json()["detail"] == "beep failed"
    assert detector.last_error == "beep failed"


def test_audio_diagnostics_endpoint(monkeypatch):
    storage.update_settings(DetectorSettings(enabled=False, output_device="auto"))

    def fake_diagnostics(output_device):
        return {
            "backend": "auto",
            "resolved_backend": "alsa",
            "default_output_id": "auto",
            "default_output_name": "ALSA: USB Audio Device / USB Audio",
            "selected_output_id": output_device,
            "selected_output_available": True,
            "available_output_count": 1,
            "dev_snd_present": True,
            "dev_snd_entries": ["controlC0", "pcmC0D0p"],
            "pulse_server": None,
            "pulse_runtime_present": False,
            "host_apis": ["ALSA"],
            "aplay_devices": ["card 0: Device [USB Audio Device], device 0: USB Audio [USB Audio]"],
            "errors": [],
            "recommended_fix": None,
        }

    monkeypatch.setattr("app.main.get_audio_diagnostics", fake_diagnostics)

    with TestClient(app) as client:
        response = client.get("/api/audio/diagnostics")

    assert response.status_code == 200
    body = response.json()
    assert body["backend"] == "auto"
    assert body["resolved_backend"] == "alsa"
    assert body["selected_output_id"] == "auto"
    assert body["dev_snd_present"] is True


async def fake_async_refresh(output_device=None):
    return None


def test_camera_preview_endpoint_returns_jpeg(monkeypatch):
    storage.update_settings(DetectorSettings(enabled=False, camera_device="/dev/video0"))

    async def fake_preview(camera_device, timeout_seconds):
        from app.preview import PreviewResult

        return PreviewResult(ok=True, image=b"\xff\xd8jpeg")

    monkeypatch.setattr("app.main.capture_preview_frame", fake_preview)

    with TestClient(app) as client:
        response = client.get("/api/camera/preview")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content == b"\xff\xd8jpeg"


def test_camera_preview_endpoint_reports_failure(monkeypatch):
    storage.update_settings(DetectorSettings(enabled=False, camera_device="/dev/video0"))

    async def fake_preview(camera_device, timeout_seconds):
        from app.preview import PreviewResult

        return PreviewResult(ok=False, error="preview failed")

    monkeypatch.setattr("app.main.capture_preview_frame", fake_preview)

    with TestClient(app) as client:
        response = client.get("/api/camera/preview")

    assert response.status_code == 503
    assert response.json()["detail"] == "preview failed"
    assert detector.last_error == "preview failed"
