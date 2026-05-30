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
    video_path: str | None = None
    video_url: str | None = None
    webhook_sent: bool = False
    webhook_error: str | None = None


class DetectorSettings(BaseModel):
    enabled: bool = True
    camera_device: str = Field(default="/dev/video0", min_length=1, max_length=255)
    output_device: str = Field(default="auto", min_length=1, max_length=255)
    sound_on_detection: bool = False
    hardware_serial_device: str = Field(
        default="none",
        pattern=r"^(none|/dev/(serial/by-id/[^/]+|ttyACM\d+|ttyUSB\d+))$",
        max_length=255,
    )
    hardware_relay_pulse_ms: int = Field(default=500, ge=50, le=10000)
    hardware_servo_from_angle: int = Field(default=30, ge=0, le=180)
    hardware_servo_to_angle: int = Field(default=150, ge=0, le=180)
    hardware_servo_step_delay_ms: int = Field(default=10, ge=1, le=1000)
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


class HardwareDevice(BaseModel):
    path: str
    name: str
    selected: bool
    available: bool


class HardwareStatus(BaseModel):
    selected_device: str
    available: bool
    connected: bool
    last_response: str | None = None
    last_error: str | None = None


class HardwareCommandResult(BaseModel):
    ok: bool
    response: str | None = None
    error: str | None = None


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
