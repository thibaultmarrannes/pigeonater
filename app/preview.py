import asyncio
from dataclasses import dataclass

import cv2


@dataclass
class PreviewResult:
    ok: bool
    image: bytes | None = None
    error: str | None = None


async def capture_preview_frame(camera_device: str, timeout_seconds: float) -> PreviewResult:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_capture_preview_frame, camera_device),
            timeout=timeout_seconds,
        )
    except TimeoutError:
        return PreviewResult(ok=False, error=f"Camera preview timed out after {timeout_seconds:g}s")
    except Exception as exc:
        return PreviewResult(ok=False, error=f"Camera preview failed: {exc}")


def _capture_preview_frame(camera_device: str) -> PreviewResult:
    capture = cv2.VideoCapture(camera_device)
    try:
        if not capture.isOpened():
            return PreviewResult(ok=False, error=f"Could not open camera device {camera_device}")

        ok, frame = capture.read()
        if not ok or frame is None:
            return PreviewResult(ok=False, error="Camera preview frame read failed")

        encoded, image = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        if not encoded:
            return PreviewResult(ok=False, error="Camera preview JPEG encode failed")

        return PreviewResult(ok=True, image=image.tobytes())
    finally:
        capture.release()
