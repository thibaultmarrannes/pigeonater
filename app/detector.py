import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import uuid4

import cv2
import numpy as np

from app.config import AppConfig
from app.schemas import DetectionBox
from app.storage import Storage
from app.webhook import send_detection_webhook


@dataclass
class CandidateDetection:
    label: str
    confidence: float
    box: DetectionBox


class ModelAdapter(Protocol):
    def detect(self, frame: np.ndarray, confidence_threshold: float) -> list[CandidateDetection]:
        ...


class YoloBirdModel:
    def __init__(self, model_name: str) -> None:
        from ultralytics import YOLO

        self.model = YOLO(model_name)

    def detect(self, frame: np.ndarray, confidence_threshold: float) -> list[CandidateDetection]:
        results = self.model.predict(frame, conf=confidence_threshold, verbose=False)
        detections: list[CandidateDetection] = []
        for result in results:
            names = result.names
            for box in result.boxes:
                class_id = int(box.cls.item())
                label = str(names.get(class_id, class_id)).lower()
                if label != "bird":
                    continue
                confidence = float(box.conf.item())
                xyxy = box.xyxy[0].tolist()
                detections.append(
                    CandidateDetection(
                        label=label,
                        confidence=confidence,
                        box=DetectionBox(x1=xyxy[0], y1=xyxy[1], x2=xyxy[2], y2=xyxy[3]),
                    )
                )
        return detections


class DetectorWorker:
    def __init__(self, config: AppConfig, storage: Storage, model: ModelAdapter | None = None) -> None:
        self.config = config
        self.storage = storage
        self.model = model
        self.worker_running = False
        self.camera_connected = False
        self.last_frame_at: datetime | None = None
        self.last_error: str | None = None
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._last_event_at: datetime | None = None

    async def start(self) -> None:
        settings = self.storage.get_settings()
        if not settings.enabled:
            self.storage.update_settings(settings.model_copy(update={"enabled": True}))
        if self._task and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        settings = self.storage.get_settings()
        if settings.enabled:
            self.storage.update_settings(settings.model_copy(update={"enabled": False}))
        await self.stop_worker()

    async def restart(self) -> None:
        await self.stop_worker()
        await self.start()

    async def stop_worker(self) -> None:
        self._stop_event.set()
        if self._task and not self._task.done():
            try:
                await asyncio.wait_for(asyncio.shield(self._task), timeout=self.config.detector_stop_timeout_seconds)
            except TimeoutError:
                self.last_error = "Detector did not stop before timeout"
                self._task.cancel()

    async def run(self) -> None:
        self.worker_running = True
        capture: cv2.VideoCapture | None = None
        try:
            await self._ensure_model()
            settings = self.storage.get_settings()
            capture = await self._call_blocking(
                "Open camera",
                lambda: self._open_capture(settings.camera_device),
                self.config.camera_open_timeout_seconds,
            )
            if capture is None:
                self.camera_connected = False
                self.last_error = f"Could not open camera device {settings.camera_device}"
                return
            self.camera_connected = True
            self.last_error = None

            while not self._stop_event.is_set():
                settings = self.storage.get_settings()
                if not settings.enabled:
                    await asyncio.sleep(1.0)
                    continue

                ok, frame = await self._call_blocking(
                    "Read camera frame",
                    capture.read,
                    self.config.camera_read_timeout_seconds,
                )
                if not ok or frame is None:
                    self.camera_connected = False
                    self.last_error = "Camera frame read failed"
                    await asyncio.sleep(1.0)
                    continue

                self.camera_connected = True
                self.last_frame_at = datetime.now(UTC)
                await self.process_frame(frame, settings.confidence_threshold, settings.cooldown_seconds)
                self.storage.cleanup_old_events(settings.retention_days)
                await asyncio.sleep(self.config.detector_poll_seconds)
        except Exception as exc:
            self.last_error = str(exc)
        finally:
            self.worker_running = False
            self.camera_connected = False
            if capture is not None:
                await asyncio.to_thread(capture.release)

    async def process_frame(
        self,
        frame: np.ndarray,
        confidence_threshold: float,
        cooldown_seconds: int,
    ) -> bool:
        await self._ensure_model()
        assert self.model is not None
        candidates = await self._call_blocking(
            "Run model detection",
            lambda: self.model.detect(frame, confidence_threshold),
            self.config.model_detect_timeout_seconds,
        )
        if not candidates:
            return False
        best = max(candidates, key=lambda item: item.confidence)
        now = datetime.now(UTC)
        if self._last_event_at and (now - self._last_event_at).total_seconds() < cooldown_seconds:
            return False

        snapshot_path = await asyncio.to_thread(self.write_snapshot, frame, best.box)
        event = self.storage.create_event(
            label=best.label,
            confidence=best.confidence,
            box=best.box,
            snapshot_path=snapshot_path,
            created_at=now,
        )
        self._last_event_at = now

        if self.config.action_webhook_url:
            sent, error = await send_detection_webhook(self.config.action_webhook_url, event)
            with self.storage.connect() as conn:
                conn.execute(
                    "UPDATE events SET webhook_sent = ?, webhook_error = ? WHERE id = ?",
                    (int(sent), error, event.id),
                )
        return True

    def write_snapshot(self, frame: np.ndarray, box: DetectionBox) -> Path:
        annotated = frame.copy()
        cv2.rectangle(
            annotated,
            (int(box.x1), int(box.y1)),
            (int(box.x2), int(box.y2)),
            (0, 200, 255),
            2,
        )
        path = self.config.snapshot_dir / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}-{uuid4().hex}.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(path), annotated):
            raise RuntimeError(f"Could not write snapshot to {path}")
        return path

    def _open_capture(self, camera_device: str) -> cv2.VideoCapture | None:
        capture = cv2.VideoCapture(camera_device)
        if not capture.isOpened():
            capture.release()
            return None
        return capture

    async def _ensure_model(self) -> None:
        if self.model is None:
            self.model = await self._call_blocking(
                "Load model",
                lambda: YoloBirdModel(self.config.model_name),
                self.config.model_detect_timeout_seconds,
            )

    async def _call_blocking(self, label: str, func, timeout_seconds: float):
        try:
            return await asyncio.wait_for(asyncio.to_thread(func), timeout=timeout_seconds)
        except TimeoutError as exc:
            raise RuntimeError(f"{label} timed out after {timeout_seconds:g}s") from exc
