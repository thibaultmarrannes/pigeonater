import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterator

from app.schemas import DetectionBox, DetectionEvent, DetectorSettings


class Storage:
    def __init__(self, database_path: Path, snapshot_dir: Path) -> None:
        self.database_path = database_path
        self.snapshot_dir = snapshot_dir
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.init_db()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_db(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    label TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    box_json TEXT NOT NULL,
                    snapshot_path TEXT NOT NULL,
                    webhook_sent INTEGER NOT NULL DEFAULT 0,
                    webhook_error TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            if not self._settings_exist(conn):
                self._write_settings(conn, DetectorSettings())

    def _settings_exist(self, conn: sqlite3.Connection) -> bool:
        row = conn.execute("SELECT 1 FROM settings WHERE key = 'detector'").fetchone()
        return row is not None

    def _write_settings(self, conn: sqlite3.Connection, settings: DetectorSettings) -> None:
        conn.execute(
            """
            INSERT INTO settings (key, value)
            VALUES ('detector', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (settings.model_dump_json(),),
        )

    def get_settings(self) -> DetectorSettings:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = 'detector'").fetchone()
            if row is None:
                settings = DetectorSettings()
                self._write_settings(conn, settings)
                return settings
            return DetectorSettings.model_validate_json(row["value"])

    def update_settings(self, settings: DetectorSettings) -> DetectorSettings:
        with self.connect() as conn:
            self._write_settings(conn, settings)
        return settings

    def create_event(
        self,
        *,
        label: str,
        confidence: float,
        box: DetectionBox,
        snapshot_path: Path,
        created_at: datetime | None = None,
        webhook_sent: bool = False,
        webhook_error: str | None = None,
    ) -> DetectionEvent:
        created_at = created_at or datetime.now(UTC)
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO events (
                    created_at, label, confidence, box_json, snapshot_path,
                    webhook_sent, webhook_error
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    created_at.isoformat(),
                    label,
                    confidence,
                    box.model_dump_json(),
                    str(snapshot_path),
                    int(webhook_sent),
                    webhook_error,
                ),
            )
            event_id = int(cursor.lastrowid)
        event = self.get_event(event_id)
        if event is None:
            raise RuntimeError("Created event could not be read back")
        return event

    def get_event(self, event_id: int) -> DetectionEvent | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        return self._row_to_event(row) if row else None

    def list_events(self, limit: int = 100) -> list[DetectionEvent]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM events ORDER BY created_at DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def latest_event_at(self) -> datetime | None:
        with self.connect() as conn:
            row = conn.execute("SELECT created_at FROM events ORDER BY created_at DESC LIMIT 1").fetchone()
        return datetime.fromisoformat(row["created_at"]) if row else None

    def cleanup_old_events(self, retention_days: int, now: datetime | None = None) -> int:
        cutoff = (now or datetime.now(UTC)) - timedelta(days=retention_days)
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id, snapshot_path FROM events WHERE created_at < ?",
                (cutoff.isoformat(),),
            ).fetchall()
            for row in rows:
                path = Path(row["snapshot_path"])
                if path.exists():
                    path.unlink()
            conn.executemany("DELETE FROM events WHERE id = ?", [(row["id"],) for row in rows])
        return len(rows)

    def _row_to_event(self, row: sqlite3.Row) -> DetectionEvent:
        snapshot_path = row["snapshot_path"]
        return DetectionEvent(
            id=row["id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            label=row["label"],
            confidence=row["confidence"],
            box=DetectionBox.model_validate(json.loads(row["box_json"])),
            snapshot_path=snapshot_path,
            snapshot_url=f"/snapshots/{Path(snapshot_path).name}",
            webhook_sent=bool(row["webhook_sent"]),
            webhook_error=row["webhook_error"],
        )

