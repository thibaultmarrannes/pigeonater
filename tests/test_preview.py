import numpy as np

from app.preview import _capture_preview_frame


class PreviewCapture:
    def __init__(self, opened=True, readable=True):
        self.opened = opened
        self.readable = readable
        self.released = False

    def isOpened(self):
        return self.opened

    def read(self):
        if not self.readable:
            return False, None
        return True, np.zeros((20, 20, 3), dtype=np.uint8)

    def release(self):
        self.released = True


def test_capture_preview_frame_returns_jpeg(monkeypatch):
    capture = PreviewCapture()
    monkeypatch.setattr("app.preview.cv2.VideoCapture", lambda _: capture)

    result = _capture_preview_frame("/dev/video0")

    assert result.ok is True
    assert result.image.startswith(b"\xff\xd8")
    assert capture.released is True


def test_capture_preview_frame_reports_open_failure(monkeypatch):
    capture = PreviewCapture(opened=False)
    monkeypatch.setattr("app.preview.cv2.VideoCapture", lambda _: capture)

    result = _capture_preview_frame("/dev/video9")

    assert result.ok is False
    assert result.error == "Could not open camera device /dev/video9"
    assert capture.released is True
