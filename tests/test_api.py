import time

from fastapi.testclient import TestClient

from app.main import app, config, detector, storage
from app.schemas import DetectionBox, DetectorSettings


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


def test_delete_event_video_endpoint_removes_video_but_keeps_event_and_snapshot():
    config.snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot = config.snapshot_dir / "api-delete-video.jpg"
    video = config.snapshot_dir / "api-delete-video.mp4"
    snapshot.write_bytes(b"snapshot")
    video.write_bytes(b"video")
    event = storage.create_event(
        label="bird",
        confidence=0.9,
        box=DetectionBox(x1=1, y1=2, x2=3, y2=4),
        snapshot_path=snapshot,
        video_path=video,
    )

    with TestClient(app) as client:
        response = client.delete(f"/api/events/{event.id}/video")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == event.id
    assert body["video_path"] is None
    assert body["video_url"] is None
    assert not video.exists()
    assert snapshot.exists()
    assert storage.get_event(event.id) is not None

    snapshot.unlink(missing_ok=True)


def test_delete_event_video_endpoint_reports_missing_event():
    with TestClient(app) as client:
        response = client.delete("/api/events/999999999/video")

    assert response.status_code == 404
    assert response.json()["detail"] == "Event not found"


def test_page_routes_render():
    storage.update_settings(DetectorSettings(enabled=False))
    with TestClient(app) as client:
        for path in ["/", "/events", "/live", "/settings"]:
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


def test_settings_endpoint_validates_hardware_payload():
    storage.update_settings(DetectorSettings(enabled=False))
    with TestClient(app) as client:
        response = client.patch(
            "/api/settings",
            json={
                "enabled": False,
                "camera_device": "/dev/video0",
                "output_device": "auto",
                "sound_on_detection": False,
                "hardware_serial_device": "/tmp/ttyACM0",
                "hardware_relay_pulse_ms": 20,
                "hardware_servo_from_angle": 30,
                "hardware_servo_to_angle": 150,
                "hardware_servo_step_delay_ms": 10,
                "confidence_threshold": 0.35,
                "cooldown_seconds": 60,
                "retention_days": 7,
            },
        )

    assert response.status_code == 422


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


def test_hardware_devices_endpoint(monkeypatch):
    storage.update_settings(DetectorSettings(enabled=False, hardware_serial_device="/dev/ttyACM0"))

    def fake_hardware_devices(selected_device):
        return [
            {
                "path": "none",
                "name": "Disabled",
                "selected": False,
                "available": True,
            },
            {
                "path": selected_device,
                "name": selected_device,
                "selected": True,
                "available": True,
            },
        ]

    monkeypatch.setattr("app.main.list_hardware_devices", fake_hardware_devices)

    with TestClient(app) as client:
        response = client.get("/api/hardware/devices")

    assert response.status_code == 200
    assert response.json()[1]["path"] == "/dev/ttyACM0"
    assert response.json()[1]["selected"] is True


def test_hardware_status_endpoint_does_not_open_serial():
    storage.update_settings(DetectorSettings(enabled=False, hardware_serial_device="/dev/ttyACM0"))

    with TestClient(app) as client:
        response = client.get("/api/hardware/status")

    assert response.status_code == 200
    body = response.json()
    assert body["selected_device"] == "/dev/ttyACM0"
    assert body["connected"] is False


def test_hardware_test_relay_endpoint(monkeypatch):
    storage.update_settings(
        DetectorSettings(
            enabled=False,
            hardware_serial_device="/dev/ttyACM0",
            hardware_relay_pulse_ms=750,
        )
    )

    def fake_relay(device, pulse_ms, *, timeout_seconds):
        from app.schemas import HardwareCommandResult

        assert device == "/dev/ttyACM0"
        assert pulse_ms == 750
        return HardwareCommandResult(ok=True, response="OK RELAY_PULSE")

    monkeypatch.setattr("app.main.send_relay_pulse", fake_relay)

    with TestClient(app) as client:
        response = client.post("/api/hardware/test-relay")

    assert response.status_code == 200
    assert response.json()["connected"] is True
    assert response.json()["last_response"] == "OK RELAY_PULSE"


def test_hardware_test_led_endpoint(monkeypatch):
    storage.update_settings(DetectorSettings(enabled=False, hardware_serial_device="/dev/ttyACM0"))

    def fake_led(device, *, timeout_seconds):
        from app.schemas import HardwareCommandResult

        assert device == "/dev/ttyACM0"
        return HardwareCommandResult(ok=True, response="OK LED_BLINK")

    monkeypatch.setattr("app.main.send_led_blink", fake_led)

    with TestClient(app) as client:
        response = client.post("/api/hardware/test-led")

    assert response.status_code == 200
    assert response.json()["connected"] is True
    assert response.json()["last_response"] == "OK LED_BLINK"


def test_hardware_test_servo_endpoint_reports_failure(monkeypatch):
    storage.update_settings(DetectorSettings(enabled=False, hardware_serial_device="/dev/ttyACM0"))

    def fake_servo(device, from_angle, to_angle, step_delay_ms, *, timeout_seconds):
        from app.schemas import HardwareCommandResult

        return HardwareCommandResult(ok=False, error="servo failed")

    monkeypatch.setattr("app.main.send_servo_sweep", fake_servo)

    with TestClient(app) as client:
        response = client.post("/api/hardware/test-servo")

    assert response.status_code == 503
    assert response.json()["detail"] == "servo failed"


def test_hardware_flash_endpoint(monkeypatch):
    storage.update_settings(DetectorSettings(enabled=False, hardware_serial_device="/dev/ttyACM0"))

    def fake_flash(device, *, firmware_path, fqbn, timeout_seconds):
        from app.schemas import HardwareCommandResult

        assert device == "/dev/ttyACM0"
        assert str(firmware_path).endswith("firmware/pigeonater_arduino")
        assert fqbn == "arduino:avr:uno"
        return HardwareCommandResult(ok=True, response="OK FIRMWARE_FLASHED")

    monkeypatch.setattr("app.main.flash_arduino_firmware", fake_flash)

    with TestClient(app) as client:
        response = client.post("/api/hardware/flash")

    assert response.status_code == 200
    assert response.json()["connected"] is True
    assert response.json()["last_response"] == "OK FIRMWARE_FLASHED"


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


def test_camera_preview_endpoint_uses_cached_detector_frame(monkeypatch):
    storage.update_settings(DetectorSettings(enabled=True, camera_device="/dev/video0"))

    async def fake_cached_preview():
        return b"\xff\xd8cached"

    async def fail_preview(camera_device, timeout_seconds):
        raise AssertionError("direct camera preview should not be opened")

    monkeypatch.setattr(detector, "latest_preview_jpeg", fake_cached_preview)
    monkeypatch.setattr("app.main.capture_preview_frame", fail_preview)

    with TestClient(app) as client:
        response = client.get("/api/camera/preview")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content == b"\xff\xd8cached"


def test_live_stream_endpoint_uses_cached_detector_frame(monkeypatch):
    async def fake_cached_preview():
        return 12, b"\xff\xd8live"

    monkeypatch.setattr(detector, "latest_preview", fake_cached_preview)

    with TestClient(app) as client:
        response = client.get("/api/live.mjpg?once=true")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("multipart/x-mixed-replace")
    assert b"Content-Type: image/jpeg" in response.content
    assert b"Content-Length: 6" in response.content
    assert b"\xff\xd8live" in response.content


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
