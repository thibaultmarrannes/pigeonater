import numpy as np
import pytest

from app.config import AppConfig
from app.detector import CandidateDetection, DetectorWorker
from app.schemas import DetectionBox
from app.storage import Storage


class FakeModel:
    def __init__(self, detections):
        self.detections = detections

    def detect(self, frame, confidence_threshold):
        return [item for item in self.detections if item.confidence >= confidence_threshold]


@pytest.mark.asyncio
async def test_process_frame_creates_event(tmp_path):
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

    created = await worker.process_frame(np.zeros((40, 40, 3), dtype=np.uint8), 0.35, 60)

    events = storage.list_events()
    assert created is True
    assert len(events) == 1
    assert events[0].label == "bird"
    assert list((tmp_path / "snapshots").glob("*.jpg"))


@pytest.mark.asyncio
async def test_process_frame_respects_cooldown(tmp_path):
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
    frame = np.zeros((40, 40, 3), dtype=np.uint8)

    first = await worker.process_frame(frame, 0.35, 60)
    second = await worker.process_frame(frame, 0.35, 60)

    assert first is True
    assert second is False
    assert len(storage.list_events()) == 1


@pytest.mark.asyncio
async def test_process_frame_ignores_low_confidence(tmp_path):
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

    created = await worker.process_frame(np.zeros((40, 40, 3), dtype=np.uint8), 0.35, 60)

    assert created is False
    assert storage.list_events() == []
