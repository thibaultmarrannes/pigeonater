import re
import shutil
import subprocess
from glob import glob
from pathlib import Path

from app.schemas import CameraDevice

VIDEO_NODE_RE = re.compile(r"^video\d+$")


def list_camera_devices(
    selected_path: str,
    *,
    sys_class_path: Path = Path("/sys/class/video4linux"),
    probe_timeout_seconds: float = 0.5,
) -> list[CameraDevice]:
    candidates = discover_video_device_paths(sys_class_path)
    capture_paths = [path for path in candidates if has_capture_capability(path, timeout_seconds=probe_timeout_seconds)]
    paths = sorted(set(capture_paths + [selected_path]))
    return [
        CameraDevice(path=path, selected=path == selected_path, available=path in capture_paths)
        for path in paths
    ]


def discover_video_device_paths(sys_class_path: Path = Path("/sys/class/video4linux")) -> list[str]:
    if sys_class_path.exists():
        return sorted(f"/dev/{entry.name}" for entry in sys_class_path.iterdir() if VIDEO_NODE_RE.match(entry.name))
    return sorted(path for path in glob("/dev/video*") if VIDEO_NODE_RE.match(Path(path).name))


def has_capture_capability(path: str, *, timeout_seconds: float = 0.5) -> bool:
    v4l2_ctl = shutil.which("v4l2-ctl")
    if not v4l2_ctl:
        return True

    try:
        result = subprocess.run(
            [v4l2_ctl, "--device", path, "--info"],
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout_seconds,
        )
    except (subprocess.SubprocessError, OSError):
        return False

    if result.returncode != 0:
        return False

    output = f"{result.stdout}\n{result.stderr}"
    return "Video Capture" in output
