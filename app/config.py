from functools import lru_cache
import subprocess
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    data_dir: Path = Path("data")
    snapshot_dir: Path = Path("data/snapshots")
    sound_dir: Path = Path("data/sounds")
    database_path: Path = Path("data/pigeonater.sqlite3")
    model_name: str = "yolo11n.pt"
    action_webhook_url: str | None = None
    detector_poll_seconds: float = 0.2
    camera_discovery_timeout_seconds: float = 1.0
    camera_open_timeout_seconds: float = 3.0
    camera_read_timeout_seconds: float = 2.0
    model_detect_timeout_seconds: float = 10.0
    detector_stop_timeout_seconds: float = 2.0
    event_video_seconds: float = 10.0
    event_video_fps: float = 24.0
    live_stream_fps: float = 5.0
    live_preview_max_width: int = Field(default=960, ge=320, le=3840)
    live_preview_jpeg_quality: int = Field(default=65, ge=30, le=95)
    audio_discovery_timeout_seconds: float = 1.0
    audio_playback_timeout_seconds: float = 3.0
    max_sound_upload_bytes: int = 20 * 1024 * 1024
    hardware_discovery_timeout_seconds: float = 1.0
    hardware_command_timeout_seconds: float = 3.0
    hardware_flash_timeout_seconds: float = 120.0
    arduino_fqbn: str = "arduino:avr:uno"
    arduino_firmware_path: Path = Path("firmware/pigeonater_arduino")
    pigeonater_version: str = "dev"
    pigeonater_commit: str = "unknown"
    pigeonater_build_date: str = "unknown"


def resolve_version(config: AppConfig) -> dict[str, str]:
    commit = config.pigeonater_commit
    build_date = config.pigeonater_build_date
    version = config.pigeonater_version

    if commit == "unknown":
        commit = _git_output(["git", "rev-parse", "--short", "HEAD"]) or commit
    if build_date == "unknown":
        build_date = _git_output(["git", "show", "-s", "--format=%cs", "HEAD"]) or build_date
    if version == "dev" and commit != "unknown" and build_date != "unknown":
        version = f"{build_date}-{commit[:7]}"
        if _git_is_dirty():
            version = f"{version}-dirty"

    return {"version": version, "commit": commit, "build_date": build_date}


def _git_output(command: list[str]) -> str | None:
    try:
        result = subprocess.run(command, capture_output=True, check=False, text=True, timeout=1.0)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _git_is_dirty() -> bool:
    try:
        result = subprocess.run(
            ["git", "diff", "--quiet"],
            capture_output=True,
            check=False,
            timeout=1.0,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 1


@lru_cache
def get_config() -> AppConfig:
    return AppConfig()
