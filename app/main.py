import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.cameras import list_camera_devices
from app.config import get_config, resolve_version
from app.detector import DetectorWorker
from app.preview import capture_preview_frame
from app.audio import (
    list_audio_sounds,
    get_audio_diagnostics,
    list_audio_output_devices,
    play_selected_sound,
    play_test_beep,
    save_uploaded_sound,
)
from app.hardware import (
    cached_hardware_status,
    flash_arduino_firmware,
    list_hardware_devices,
    send_led_blink,
    send_relay_pulse,
    send_servo_sweep,
)
from app.schemas import (
    AudioDiagnostics,
    AudioOutputDevice,
    AudioSound,
    CameraDevice,
    DetectionEvent,
    DetectorSettings,
    HardwareDevice,
    HardwareStatus,
    StatusResponse,
)
from app.storage import Storage

config = get_config()
version_info = resolve_version(config)
storage = Storage(config.database_path, config.snapshot_dir)
config.sound_dir.mkdir(parents=True, exist_ok=True)
detector = DetectorWorker(config, storage)
templates = Jinja2Templates(directory="app/templates")


@asynccontextmanager
async def lifespan(_: FastAPI):
    await detector.refresh_audio_status(storage.get_settings().output_device)
    if storage.get_settings().enabled:
        await detector.start()
    yield
    await detector.stop()


app = FastAPI(title="Pigeonater", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.mount("/snapshots", StaticFiles(directory=str(config.snapshot_dir)), name="snapshots")


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse(request, "dashboard.html", {"version_info": version_info})


@app.get("/events", response_class=HTMLResponse)
async def events_page(request: Request):
    return templates.TemplateResponse(request, "events.html", {"version_info": version_info})


@app.get("/live", response_class=HTMLResponse)
async def live_page(request: Request):
    return templates.TemplateResponse(request, "live.html", {"version_info": version_info})


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    return templates.TemplateResponse(request, "settings.html", {"version_info": version_info})


@app.get("/api/status", response_model=StatusResponse)
async def api_status() -> StatusResponse:
    return _build_status_response()


def _build_status_response() -> StatusResponse:
    settings = storage.get_settings()
    return StatusResponse(
        detector_enabled=settings.enabled,
        worker_running=detector.worker_running,
        camera_connected=detector.camera_connected,
        camera_device=settings.camera_device,
        audio_ready=detector.audio_ready,
        audio_backend=detector.audio_backend,
        audio_output_label=detector.audio_output_label,
        audio_status=detector.audio_status,
        last_frame_at=detector.last_frame_at,
        last_error=detector.last_error,
        last_event_at=storage.latest_event_at(),
        model_name=config.model_name,
        settings=settings,
        performance=detector.performance_stats(),
    )


@app.get("/api/version")
async def api_version():
    return version_info


@app.get("/api/events")
async def api_events(limit: int = 100):
    limit = min(max(limit, 1), 500)
    return storage.list_events(limit=limit)


@app.get("/api/stream")
async def api_stream(request: Request, limit: int = 100, once: bool = False):
    limit = min(max(limit, 1), 500)

    async def event_stream():
        while True:
            payload = {
                "status": _build_status_response().model_dump(mode="json"),
                "events": [event.model_dump(mode="json") for event in storage.list_events(limit=limit)],
            }
            yield f"event: update\ndata: {json.dumps(payload)}\n\n"
            if once:
                break
            if await request.is_disconnected():
                break
            await asyncio.sleep(2.0)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/cameras", response_model=list[CameraDevice])
async def api_cameras():
    settings = storage.get_settings()
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                list_camera_devices,
                settings.camera_device,
                probe_timeout_seconds=min(config.camera_discovery_timeout_seconds, 0.5),
            ),
            timeout=config.camera_discovery_timeout_seconds,
        )
    except TimeoutError:
        detector.last_error = "Camera discovery timed out"
        return [CameraDevice(path=settings.camera_device, selected=True, available=False)]
    except Exception as exc:
        detector.last_error = f"Camera discovery failed: {exc}"
        return [CameraDevice(path=settings.camera_device, selected=True, available=False)]


@app.get("/api/audio/devices", response_model=list[AudioOutputDevice])
async def api_audio_devices():
    settings = storage.get_settings()
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(list_audio_output_devices, settings.output_device),
            timeout=config.audio_discovery_timeout_seconds,
        )
    except TimeoutError:
        detector.last_error = "Audio output discovery timed out"
        return [AudioOutputDevice(id=settings.output_device, name=settings.output_device, selected=True, available=False)]
    except Exception as exc:
        detector.last_error = f"Audio output discovery failed: {exc}"
        return [AudioOutputDevice(id=settings.output_device, name=settings.output_device, selected=True, available=False)]


@app.get("/api/audio/sounds", response_model=list[AudioSound])
async def api_audio_sounds():
    settings = storage.get_settings()
    return list_audio_sounds(config.sound_dir, settings.selected_sound)


@app.post("/api/audio/sounds", response_model=AudioSound)
async def api_audio_upload_sound(file: UploadFile = File(...)):
    payload = await file.read(config.max_sound_upload_bytes + 1)
    if len(payload) > config.max_sound_upload_bytes:
        raise HTTPException(status_code=413, detail="Sound file is too large")
    try:
        sound = await asyncio.to_thread(
            save_uploaded_sound,
            config.sound_dir,
            file.filename or "sound",
            payload,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return sound


@app.get("/api/audio/diagnostics", response_model=AudioDiagnostics)
async def api_audio_diagnostics():
    settings = storage.get_settings()
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(get_audio_diagnostics, settings.output_device),
            timeout=config.audio_discovery_timeout_seconds + 1.0,
        )
    except TimeoutError:
        detector.last_error = "Audio diagnostics timed out"
        raise HTTPException(status_code=503, detail=detector.last_error)
    except Exception as exc:
        detector.last_error = f"Audio diagnostics failed: {exc}"
        raise HTTPException(status_code=503, detail=detector.last_error)


@app.get("/api/hardware/devices", response_model=list[HardwareDevice])
async def api_hardware_devices():
    settings = storage.get_settings()
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(list_hardware_devices, settings.hardware_serial_device),
            timeout=config.hardware_discovery_timeout_seconds,
        )
    except TimeoutError:
        detector.last_error = "Hardware device discovery timed out"
        return [
            HardwareDevice(
                path=settings.hardware_serial_device,
                name=settings.hardware_serial_device,
                selected=True,
                available=False,
            )
        ]
    except Exception as exc:
        detector.last_error = f"Hardware device discovery failed: {exc}"
        return [
            HardwareDevice(
                path=settings.hardware_serial_device,
                name=settings.hardware_serial_device,
                selected=True,
                available=False,
            )
        ]


@app.get("/api/hardware/status", response_model=HardwareStatus)
async def api_hardware_status():
    settings = storage.get_settings()
    return cached_hardware_status(settings.hardware_serial_device)


@app.post("/api/hardware/test-relay", response_model=HardwareStatus)
async def api_hardware_test_relay():
    settings = storage.get_settings()
    timeout_seconds = config.hardware_command_timeout_seconds + (settings.hardware_relay_pulse_ms / 1000.0)
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(
                send_relay_pulse,
                settings.hardware_serial_device,
                settings.hardware_relay_pulse_ms,
                timeout_seconds=timeout_seconds,
            ),
            timeout=timeout_seconds + 0.5,
        )
    except TimeoutError:
        detector.last_error = "Relay test timed out"
        raise HTTPException(status_code=503, detail=detector.last_error)

    if not result.ok:
        detector.last_error = result.error
        raise HTTPException(status_code=503, detail=result.error or "Relay test failed")

    return HardwareStatus(
        selected_device=settings.hardware_serial_device,
        available=True,
        connected=True,
        last_response=result.response,
    )


@app.post("/api/hardware/test-led", response_model=HardwareStatus)
async def api_hardware_test_led():
    settings = storage.get_settings()
    timeout_seconds = config.hardware_command_timeout_seconds + 1.0
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(
                send_led_blink,
                settings.hardware_serial_device,
                timeout_seconds=timeout_seconds,
            ),
            timeout=timeout_seconds + 0.5,
        )
    except TimeoutError:
        detector.last_error = "LED blink test timed out"
        raise HTTPException(status_code=503, detail=detector.last_error)

    if not result.ok:
        detector.last_error = result.error
        raise HTTPException(status_code=503, detail=result.error or "LED blink test failed")

    return HardwareStatus(
        selected_device=settings.hardware_serial_device,
        available=True,
        connected=True,
        last_response=result.response,
    )


@app.post("/api/hardware/test-servo", response_model=HardwareStatus)
async def api_hardware_test_servo():
    settings = storage.get_settings()
    sweep_seconds = abs(settings.hardware_servo_to_angle - settings.hardware_servo_from_angle) * (
        settings.hardware_servo_step_delay_ms / 1000.0
    )
    timeout_seconds = config.hardware_command_timeout_seconds + sweep_seconds
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(
                send_servo_sweep,
                settings.hardware_serial_device,
                settings.hardware_servo_from_angle,
                settings.hardware_servo_to_angle,
                settings.hardware_servo_step_delay_ms,
                timeout_seconds=timeout_seconds,
            ),
            timeout=timeout_seconds + 0.5,
        )
    except TimeoutError:
        detector.last_error = "Servo test timed out"
        raise HTTPException(status_code=503, detail=detector.last_error)

    if not result.ok:
        detector.last_error = result.error
        raise HTTPException(status_code=503, detail=result.error or "Servo test failed")

    return HardwareStatus(
        selected_device=settings.hardware_serial_device,
        available=True,
        connected=True,
        last_response=result.response,
    )


@app.post("/api/hardware/flash", response_model=HardwareStatus)
async def api_hardware_flash():
    settings = storage.get_settings()
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(
                flash_arduino_firmware,
                settings.hardware_serial_device,
                firmware_path=config.arduino_firmware_path,
                fqbn=config.arduino_fqbn,
                timeout_seconds=config.hardware_flash_timeout_seconds,
            ),
            timeout=config.hardware_flash_timeout_seconds + 1.0,
        )
    except TimeoutError:
        detector.last_error = "Arduino firmware flash timed out"
        raise HTTPException(status_code=503, detail=detector.last_error)

    if not result.ok:
        detector.last_error = result.error
        raise HTTPException(
            status_code=503,
            detail={
                "error": result.error or "Arduino firmware flash failed",
                "log": result.log,
            },
        )

    return HardwareStatus(
        selected_device=settings.hardware_serial_device,
        available=True,
        connected=True,
        last_response=result.response,
        last_log=result.log,
    )


@app.post("/api/audio/test-beep")
async def api_audio_test_beep():
    settings = storage.get_settings()
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(play_test_beep, settings.output_device),
            timeout=config.audio_playback_timeout_seconds,
        )
    except TimeoutError:
        detector.last_error = "Test beep timed out"
        raise HTTPException(status_code=503, detail=detector.last_error)

    if not result.ok:
        detector.last_error = result.error
        raise HTTPException(status_code=503, detail=result.error)

    await detector.refresh_audio_status(settings.output_device)
    return {"ok": True}


@app.post("/api/audio/test-selected-sound")
async def api_audio_test_selected_sound():
    settings = storage.get_settings()
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(play_selected_sound, settings.output_device, config.sound_dir, settings.selected_sound),
            timeout=config.audio_playback_timeout_seconds + 2.0,
        )
    except TimeoutError:
        detector.last_error = "Selected sound test timed out"
        raise HTTPException(status_code=503, detail=detector.last_error)

    if not result.ok:
        detector.last_error = result.error
        raise HTTPException(status_code=503, detail=result.error)

    await detector.refresh_audio_status(settings.output_device)
    return {"ok": True}


@app.get("/api/camera/preview")
async def api_camera_preview():
    settings = storage.get_settings()
    cached_image = await detector.latest_preview_jpeg()
    if cached_image is not None:
        return Response(
            content=cached_image,
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store, max-age=0"},
        )

    result = await capture_preview_frame(settings.camera_device, config.camera_read_timeout_seconds)
    if not result.ok or result.image is None:
        detector.last_error = result.error
        raise HTTPException(status_code=503, detail=result.error)
    return Response(
        content=result.image,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.get("/api/live.mjpg")
async def api_live_stream(request: Request, once: bool = False):
    async def frame_stream():
        interval = 1.0 / max(float(config.live_stream_fps), 1.0)
        last_sequence = -1
        while True:
            sequence, image = await detector.latest_preview()
            if image is not None and sequence != last_sequence:
                last_sequence = sequence
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Cache-Control: no-store\r\n"
                    + f"Content-Length: {len(image)}\r\n\r\n".encode("ascii")
                    + image
                    + b"\r\n"
                )
                if once:
                    break
            if await request.is_disconnected():
                break
            await asyncio.sleep(interval)

    return StreamingResponse(
        frame_stream(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate", "X-Accel-Buffering": "no"},
    )


@app.get("/api/events/{event_id}")
async def api_event(event_id: int):
    event = storage.get_event(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@app.delete("/api/events/{event_id}/video", response_model=DetectionEvent)
async def api_delete_event_video(event_id: int) -> DetectionEvent:
    event = storage.delete_event_video(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@app.patch("/api/settings", response_model=DetectorSettings)
async def api_update_settings(settings: DetectorSettings):
    previous = storage.get_settings()
    if settings.selected_sound != "beep" and not (config.sound_dir / settings.selected_sound).exists():
        raise HTTPException(status_code=422, detail="Selected sound is not available")
    updated = storage.update_settings(settings)
    camera_changed = previous.camera_device != updated.camera_device
    audio_changed = previous.output_device != updated.output_device
    if audio_changed or previous.sound_on_detection != updated.sound_on_detection:
        await detector.refresh_audio_status(updated.output_device)
    if updated.enabled and camera_changed and detector.worker_running:
        await detector.restart()
    elif updated.enabled:
        await detector.start()
    else:
        await detector.stop()
    return updated


@app.post("/api/detector/start", response_model=StatusResponse)
async def api_start_detector():
    await detector.start()
    return await api_status()


@app.post("/api/detector/stop", response_model=StatusResponse)
async def api_stop_detector():
    await detector.stop()
    return await api_status()


@app.get("/healthz")
async def healthz():
    return {"ok": True, "data_dir": str(Path(config.data_dir))}
