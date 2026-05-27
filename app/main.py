from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.cameras import list_camera_devices
from app.config import get_config
from app.detector import DetectorWorker
from app.schemas import CameraDevice, DetectorSettings, StatusResponse
from app.storage import Storage

config = get_config()
storage = Storage(config.database_path, config.snapshot_dir)
detector = DetectorWorker(config, storage)
templates = Jinja2Templates(directory="app/templates")


@asynccontextmanager
async def lifespan(_: FastAPI):
    if storage.get_settings().enabled:
        await detector.start()
    yield
    await detector.stop()


app = FastAPI(title="Pigeonater", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.mount("/snapshots", StaticFiles(directory=str(config.snapshot_dir)), name="snapshots")


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})


@app.get("/events", response_class=HTMLResponse)
async def events_page(request: Request):
    return templates.TemplateResponse("events.html", {"request": request})


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    return templates.TemplateResponse("settings.html", {"request": request})


@app.get("/api/status", response_model=StatusResponse)
async def api_status() -> StatusResponse:
    settings = storage.get_settings()
    return StatusResponse(
        detector_enabled=settings.enabled,
        worker_running=detector.worker_running,
        camera_connected=detector.camera_connected,
        camera_device=settings.camera_device,
        last_frame_at=detector.last_frame_at,
        last_error=detector.last_error,
        last_event_at=storage.latest_event_at(),
        model_name=config.model_name,
        settings=settings,
    )


@app.get("/api/events")
async def api_events(limit: int = 100):
    limit = min(max(limit, 1), 500)
    return storage.list_events(limit=limit)


@app.get("/api/cameras", response_model=list[CameraDevice])
async def api_cameras():
    return list_camera_devices(storage.get_settings().camera_device)


@app.get("/api/events/{event_id}")
async def api_event(event_id: int):
    event = storage.get_event(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@app.patch("/api/settings", response_model=DetectorSettings)
async def api_update_settings(settings: DetectorSettings):
    previous = storage.get_settings()
    updated = storage.update_settings(settings)
    camera_changed = previous.camera_device != updated.camera_device
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
