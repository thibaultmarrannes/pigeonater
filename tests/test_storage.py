from datetime import UTC, datetime, timedelta

from app.schemas import DetectionBox, DetectorSettings
from app.storage import Storage


def test_settings_round_trip(tmp_path):
    storage = Storage(tmp_path / "test.sqlite3", tmp_path / "snapshots")

    settings = storage.update_settings(
        DetectorSettings(
            enabled=False,
            camera_device="/dev/video2",
            output_device="1",
            confidence_threshold=0.5,
            cooldown_seconds=12,
            retention_days=7,
        )
    )

    assert settings == storage.get_settings()


def test_cleanup_old_events_removes_records_and_snapshots(tmp_path):
    storage = Storage(tmp_path / "test.sqlite3", tmp_path / "snapshots")
    old_snapshot = tmp_path / "snapshots" / "old.jpg"
    fresh_snapshot = tmp_path / "snapshots" / "fresh.jpg"
    old_snapshot.write_bytes(b"old")
    fresh_snapshot.write_bytes(b"fresh")

    storage.create_event(
        label="bird",
        confidence=0.9,
        box=DetectionBox(x1=1, y1=2, x2=3, y2=4),
        snapshot_path=old_snapshot,
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
    assert fresh_snapshot.exists()
    assert len(storage.list_events()) == 1
