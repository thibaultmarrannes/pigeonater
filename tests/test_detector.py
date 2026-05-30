import asyncio

import cv2
import numpy as np
import pytest

from app.config import AppConfig
from app.detector import CandidateDetection, DetectorWorker
from app.schemas import DetectionBox
from app.storage import Storage


class FakeModel:
    def __init__(self, detections):
        self.detections = detections
        self.calls = []

    def detect(self, frame, confidence_threshold):
        self.calls.append(frame)
        return [item for item in self.detections if item.confidence >= confidence_threshold]


class ClosedCapture:
    def isOpened(self):
        return False

    def release(self):
        pass


@pytest.mark.asyncio
async def test_start_records_error_when_camera_open_fails(tmp_path, monkeypatch):
    storage = Storage(tmp_path / "test.sqlite3", tmp_path / "snapshots")
    storage.update_settings(storage.get_settings().model_copy(update={"enabled": True, "camera_device": "/dev/video9"}))
    config = AppConfig(
        data_dir=tmp_path,
        snapshot_dir=tmp_path / "snapshots",
        database_path=tmp_path / "test.sqlite3",
        camera_open_timeout_seconds=0.1,
    )
    worker = DetectorWorker(config, storage, model=FakeModel([]))
    monkeypatch.setattr("app.detector.cv2.VideoCapture", lambda _: ClosedCapture())

    await worker.start()
    await asyncio.sleep(0.1)

    assert worker.worker_running is False
    assert worker.camera_connected is False
    assert worker.last_error == "Could not open camera device /dev/video9"


@pytest.mark.asyncio
async def test_process_frame_creates_event(tmp_path, monkeypatch):
    storage = Storage(tmp_path / "test.sqlite3", tmp_path / "snapshots")
    config = AppConfig(
        data_dir=tmp_path,
        snapshot_dir=tmp_path / "snapshots",
        database_path=tmp_path / "test.sqlite3",
    )
    worker = DetectorWorker(
        config,
        storage,
        model=FakeModel([CandidateDetection("bird", 0.8, DetectionBox(x1=1, y1=1, x2=20, y2=20))]),
    )
    monkeypatch.setattr(worker, "enqueue_event_video", lambda event_id: None)

    created = await worker.process_frame(np.zeros((40, 40, 3), dtype=np.uint8), 0.35, 60)

    events = storage.list_events()
    assert created is True
    assert len(events) == 1
    assert events[0].label == "bird"
    assert list((tmp_path / "snapshots").glob("*.jpg"))


@pytest.mark.asyncio
async def test_update_preview_frame_caches_jpeg(tmp_path):
    storage = Storage(tmp_path / "test.sqlite3", tmp_path / "snapshots")
    config = AppConfig(
        data_dir=tmp_path,
        snapshot_dir=tmp_path / "snapshots",
        database_path=tmp_path / "test.sqlite3",
    )
    worker = DetectorWorker(config, storage, model=FakeModel([]))

    await worker.update_preview_frame(np.zeros((40, 40, 3), dtype=np.uint8))

    image = await worker.latest_preview_jpeg()
    assert image is not None
    assert image.startswith(b"\xff\xd8")


@pytest.mark.asyncio
async def test_update_preview_frame_downscales_and_tracks_sequence(tmp_path):
    storage = Storage(tmp_path / "test.sqlite3", tmp_path / "snapshots")
    config = AppConfig(
        data_dir=tmp_path,
        snapshot_dir=tmp_path / "snapshots",
        database_path=tmp_path / "test.sqlite3",
        live_preview_max_width=320,
        live_preview_jpeg_quality=60,
    )
    worker = DetectorWorker(config, storage, model=FakeModel([]))

    await worker.update_preview_frame(np.zeros((480, 640, 3), dtype=np.uint8))

    sequence, image = await worker.latest_preview()
    assert sequence == 1
    assert image is not None
    decoded = cv2.imdecode(np.frombuffer(image, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decoded is not None
    assert decoded.shape[1] == 320
    assert decoded.shape[0] == 240


@pytest.mark.asyncio
async def test_record_event_video_updates_event(tmp_path):
    storage = Storage(tmp_path / "test.sqlite3", tmp_path / "snapshots")
    event = storage.create_event(
        label="bird",
        confidence=0.8,
        box=DetectionBox(x1=1, y1=1, x2=20, y2=20),
        snapshot_path=tmp_path / "snapshots" / "event.jpg",
    )
    config = AppConfig(
        data_dir=tmp_path,
        snapshot_dir=tmp_path / "snapshots",
        database_path=tmp_path / "test.sqlite3",
        event_video_seconds=0.2,
        event_video_fps=5.0,
    )
    worker = DetectorWorker(config, storage, model=FakeModel([]))
    await worker.update_preview_frame(np.zeros((40, 40, 3), dtype=np.uint8))

    await worker.record_event_video(event.id)

    updated = storage.get_event(event.id)
    assert updated is not None
    assert updated.video_path is not None
    assert updated.video_url is not None
    assert list((tmp_path / "snapshots").glob("*.mp4"))


@pytest.mark.asyncio
async def test_process_frame_plays_sound_when_enabled(tmp_path, monkeypatch):
    storage = Storage(tmp_path / "test.sqlite3", tmp_path / "snapshots")
    storage.update_settings(
        storage.get_settings().model_copy(update={"sound_on_detection": True, "output_device": "pa:1"})
    )
    config = AppConfig(
        data_dir=tmp_path,
        snapshot_dir=tmp_path / "snapshots",
        database_path=tmp_path / "test.sqlite3",
    )
    worker = DetectorWorker(
        config,
        storage,
        model=FakeModel([CandidateDetection("bird", 0.8, DetectionBox(x1=1, y1=1, x2=20, y2=20))]),
    )
    calls = []

    def fake_enqueue_detection_sound(output_device, selected_sound):
        calls.append((output_device, selected_sound))

    monkeypatch.setattr(worker, "enqueue_detection_sound", fake_enqueue_detection_sound)
    monkeypatch.setattr(worker, "enqueue_event_video", lambda event_id: None)

    created = await worker.process_frame(np.zeros((40, 40, 3), dtype=np.uint8), 0.35, 60)

    assert created is True
    assert calls == [("pa:1", "beep")]


@pytest.mark.asyncio
async def test_process_frame_does_not_play_sound_when_disabled(tmp_path, monkeypatch):
    storage = Storage(tmp_path / "test.sqlite3", tmp_path / "snapshots")
    storage.update_settings(storage.get_settings().model_copy(update={"sound_on_detection": False}))
    config = AppConfig(
        data_dir=tmp_path,
        snapshot_dir=tmp_path / "snapshots",
        database_path=tmp_path / "test.sqlite3",
    )
    worker = DetectorWorker(
        config,
        storage,
        model=FakeModel([CandidateDetection("bird", 0.8, DetectionBox(x1=1, y1=1, x2=20, y2=20))]),
    )
    calls = []

    def fake_enqueue_detection_sound(output_device, selected_sound):
        calls.append((output_device, selected_sound))

    monkeypatch.setattr(worker, "enqueue_detection_sound", fake_enqueue_detection_sound)
    monkeypatch.setattr(worker, "enqueue_event_video", lambda event_id: None)

    created = await worker.process_frame(np.zeros((40, 40, 3), dtype=np.uint8), 0.35, 60)

    assert created is True
    assert calls == []


@pytest.mark.asyncio
async def test_enqueue_detection_sound_drops_when_queue_is_full(tmp_path):
    storage = Storage(tmp_path / "test.sqlite3", tmp_path / "snapshots")
    config = AppConfig(
        data_dir=tmp_path,
        snapshot_dir=tmp_path / "snapshots",
        database_path=tmp_path / "test.sqlite3",
    )
    worker = DetectorWorker(config, storage, model=FakeModel([]))
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(worker, "_ensure_sound_worker", lambda: None)

    try:
        worker.enqueue_detection_sound("auto", "beep")
        worker.enqueue_detection_sound("auto", "beep")

        assert worker.last_error == "Detection sound skipped because playback is already pending"
    finally:
        monkeypatch.undo()


@pytest.mark.asyncio
async def test_process_frame_respects_cooldown(tmp_path, monkeypatch):
    storage = Storage(tmp_path / "test.sqlite3", tmp_path / "snapshots")
    config = AppConfig(
        data_dir=tmp_path,
        snapshot_dir=tmp_path / "snapshots",
        database_path=tmp_path / "test.sqlite3",
    )
    model = FakeModel([CandidateDetection("bird", 0.8, DetectionBox(x1=1, y1=1, x2=20, y2=20))])
    worker = DetectorWorker(
        config,
        storage,
        model=model,
    )
    monkeypatch.setattr(worker, "enqueue_event_video", lambda event_id: None)
    frame = np.zeros((40, 40, 3), dtype=np.uint8)

    first = await worker.process_frame(frame, 0.35, 60)
    second = await worker.process_frame(frame, 0.35, 60)

    assert first is True
    assert second is False
    assert len(storage.list_events()) == 1
    assert len(model.calls) == 1


@pytest.mark.asyncio
async def test_process_frame_ignores_low_confidence(tmp_path, monkeypatch):
    storage = Storage(tmp_path / "test.sqlite3", tmp_path / "snapshots")
    config = AppConfig(
        data_dir=tmp_path,
        snapshot_dir=tmp_path / "snapshots",
        database_path=tmp_path / "test.sqlite3",
    )
    worker = DetectorWorker(
        config,
        storage,
        model=FakeModel([CandidateDetection("bird", 0.2, DetectionBox(x1=1, y1=1, x2=20, y2=20))]),
    )
    monkeypatch.setattr(worker, "enqueue_event_video", lambda event_id: None)

    created = await worker.process_frame(np.zeros((40, 40, 3), dtype=np.uint8), 0.35, 60)

    assert created is False
    assert storage.list_events() == []


def test_should_run_detection_respects_detection_fps(tmp_path):
    storage = Storage(tmp_path / "test.sqlite3", tmp_path / "snapshots")
    config = AppConfig(
        data_dir=tmp_path,
        snapshot_dir=tmp_path / "snapshots",
        database_path=tmp_path / "test.sqlite3",
    )
    worker = DetectorWorker(config, storage, model=FakeModel([]))

    assert worker.should_run_detection(100.0, detection_fps=2.0, cooldown_seconds=60) is True
    assert worker.should_run_detection(100.2, detection_fps=2.0, cooldown_seconds=60) is False
    assert worker.performance_stats().detection_throttled is True
    assert worker.should_run_detection(100.6, detection_fps=2.0, cooldown_seconds=60) is True


def test_prepare_inference_frame_preserves_aspect_ratio(tmp_path):
    storage = Storage(tmp_path / "test.sqlite3", tmp_path / "snapshots")
    config = AppConfig(
        data_dir=tmp_path,
        snapshot_dir=tmp_path / "snapshots",
        database_path=tmp_path / "test.sqlite3",
    )
    worker = DetectorWorker(config, storage, model=FakeModel([]))

    resized, scale = worker.prepare_inference_frame(np.zeros((480, 1280, 3), dtype=np.uint8), 640)

    assert resized.shape[:2] == (240, 640)
    assert scale == 0.5


def test_scale_candidate_detection_to_original_frame(tmp_path):
    storage = Storage(tmp_path / "test.sqlite3", tmp_path / "snapshots")
    config = AppConfig(
        data_dir=tmp_path,
        snapshot_dir=tmp_path / "snapshots",
        database_path=tmp_path / "test.sqlite3",
    )
    worker = DetectorWorker(config, storage, model=FakeModel([]))
    detection = CandidateDetection("bird", 0.7, DetectionBox(x1=10, y1=20, x2=30, y2=40))

    scaled = worker.scale_candidate_detection(detection, 0.5)

    assert scaled.box == DetectionBox(x1=20, y1=40, x2=60, y2=80)


@pytest.mark.asyncio
async def test_process_frame_resizes_inference_and_scales_event_box(tmp_path, monkeypatch):
    storage = Storage(tmp_path / "test.sqlite3", tmp_path / "snapshots")
    config = AppConfig(
        data_dir=tmp_path,
        snapshot_dir=tmp_path / "snapshots",
        database_path=tmp_path / "test.sqlite3",
    )
    model = FakeModel([CandidateDetection("bird", 0.8, DetectionBox(x1=10, y1=20, x2=30, y2=40))])
    worker = DetectorWorker(config, storage, model=model)
    monkeypatch.setattr(worker, "enqueue_event_video", lambda event_id: None)

    created = await worker.process_frame(
        np.zeros((480, 1280, 3), dtype=np.uint8),
        confidence_threshold=0.35,
        cooldown_seconds=60,
        inference_max_width=640,
    )

    event = storage.list_events()[0]
    assert created is True
    assert model.calls[0].shape[:2] == (240, 640)
    assert event.box == DetectionBox(x1=20, y1=40, x2=60, y2=80)
    assert worker.performance_stats().inference_size == "640x240"
