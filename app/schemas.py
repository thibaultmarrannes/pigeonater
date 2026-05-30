from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DetectionBox(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float


class DetectionEvent(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    label: str
    confidence: float
    box: DetectionBox
    snapshot_path: str
    snapshot_url: str
    webhook_sent: bool = False
    webhook_error: str | None = None


class DetectorSettings(BaseModel):
    enabled: bool = True
    camera_device: str = Field(default="/dev/video0", min_length=1, max_length=255)
    output_device: str = Field(default="auto", min_length=1, max_length=255)
    sound_on_detection: bool = False
    confidence_threshold: float = Field(default=0.35, ge=0.05, le=0.95)
    cooldown_seconds: int = Field(default=60, ge=1, le=3600)
    retention_days: int = Field(default=7, ge=1, le=365)


class CameraDevice(BaseModel):
    path: str
    selected: bool
    available: bool


class AudioOutputDevice(BaseModel):
    id: str
    name: str
    selected: bool
    available: bool


class AudioDiagnostics(BaseModel):
    backend: str
    resolved_backend: str | None
    default_output_id: str | None
    default_output_name: str | None
    selected_output_id: str
    selected_output_available: bool
    available_output_count: int
    dev_snd_present: bool
    dev_snd_entries: list[str]
    pulse_server: str | None
    pulse_runtime_present: bool
    host_apis: list[str]
    aplay_devices: list[str]
    errors: list[str]
    recommended_fix: str | None


class StatusResponse(BaseModel):
    detector_enabled: bool
    worker_running: bool
    camera_connected: bool
    camera_device: str
    audio_ready: bool
    audio_backend: str | None
    audio_output_label: str | None
    audio_status: str
    last_frame_at: datetime | None
    last_error: str | None
    last_event_at: datetime | None
    model_name: str
    settings: DetectorSettings
