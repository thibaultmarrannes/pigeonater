from datetime import UTC, datetime, timedelta

from app.schemas import DetectionBox, DetectorSettings
from app.storage import Storage


def test_settings_round_trip(tmp_path):
    storage = Storage(tmp_path / "test.sqlite3", tmp_path / "snapshots")

    settings = storage.update_settings(
        DetectorSettings(
            enabled=False,
            camera_device="/dev/video2",
            output_device="pa:1",
            sound_on_detection=True,
            confidence_threshold=0.5,
            cooldown_seconds=12,
            retention_days=7,
        )
    )

    assert settings == storage.get_settings()


def test_event_video_path_round_trip(tmp_path):
    storage = Storage(tmp_path / "test.sqlite3", tmp_path / "snapshots")
    snapshot = tmp_path / "snapshots" / "event.jpg"
    video = tmp_path / "snapshots" / "event.mp4"
    snapshot.write_bytes(b"snapshot")
    video.write_bytes(b"video")

    event = storage.create_event(
        label="bird",
        confidence=0.9,
        box=DetectionBox(x1=1, y1=2, x2=3, y2=4),
        snapshot_path=snapshot,
    )
    assert event.video_path is None
    assert event.video_url is None

    storage.update_event_video_path(event.id, video)
    updated = storage.get_event(event.id)

    assert updated is not None
    assert updated.video_path == str(video)
    assert updated.video_url == "/snapshots/event.mp4"


def test_cleanup_old_events_removes_records_and_snapshots(tmp_path):
    storage = Storage(tmp_path / "test.sqlite3", tmp_path / "snapshots")
    old_snapshot = tmp_path / "snapshots" / "old.jpg"
    old_video = tmp_path / "snapshots" / "old.mp4"
    fresh_snapshot = tmp_path / "snapshots" / "fresh.jpg"
    old_snapshot.write_bytes(b"old")
    old_video.write_bytes(b"old video")
    fresh_snapshot.write_bytes(b"fresh")

    storage.create_event(
        label="bird",
        confidence=0.9,
        box=DetectionBox(x1=1, y1=2, x2=3, y2=4),
        snapshot_path=old_snapshot,
        video_path=old_video,
        created_at=datetime.now(UTC) - timedelta(days=8),
    )
    storage.create_event(
        label="bird",
        confidence=0.8,
        box=DetectionBox(x1=5, y1=6, x2=7, y2=8),
        snapshot_path=fresh_snapshot,
        created_at=datetime.now(UTC),
    )

    deleted = storage.cleanup_old_events(retention_days=7)

    assert deleted == 1
    assert not old_snapshot.exists()
    assert not old_video.exists()
    assert fresh_snapshot.exists()
    assert len(storage.list_events()) == 1
