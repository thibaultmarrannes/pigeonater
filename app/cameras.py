from glob import glob

import cv2

from app.schemas import CameraDevice


def list_camera_devices(selected_path: str) -> list[CameraDevice]:
    paths = sorted(set(glob("/dev/video*") + [selected_path]))
    return [CameraDevice(path=path, selected=path == selected_path, available=is_camera_available(path)) for path in paths]


def is_camera_available(path: str) -> bool:
    capture = cv2.VideoCapture(path)
    try:
        return bool(capture.isOpened())
    finally:
        capture.release()
