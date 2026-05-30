import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import uuid4

import cv2
import numpy as np

from app.config import AppConfig
from app.audio import get_audio_diagnostics, play_test_beep
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
        self.audio_ready = False
        self.audio_backend: str | None = None
        self.audio_output_label: str | None = None
        self.audio_status = "Unknown"
        self.last_frame_at: datetime | None = None
        self.last_error: str | None = None
        self._latest_preview_jpeg: bytes | None = None
        self._latest_frame: np.ndarray | None = None
        self._latest_preview_at: datetime | None = None
        self._latest_preview_sequence = 0
        self._preview_lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._sound_task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._last_event_at: datetime | None = None
        self._sound_queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=1)
        self._video_tasks: set[asyncio.Task[None]] = set()

    async def start(self) -> None:
        settings = self.storage.get_settings()
        if not settings.enabled:
            self.storage.update_settings(settings.model_copy(update={"enabled": True}))
        await self.refresh_audio_status(settings.output_device)
        self._ensure_sound_worker()
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
        await self._stop_sound_worker()
        await self._stop_video_tasks()

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
                await self.update_preview_frame(frame)
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

    async def update_preview_frame(self, frame: np.ndarray) -> None:
        encoded = await asyncio.to_thread(self.encode_preview_frame, frame)
        async with self._preview_lock:
            self._latest_preview_jpeg = encoded
            self._latest_frame = frame.copy()
            self._latest_preview_at = datetime.now(UTC)
            self._latest_preview_sequence += 1

    async def latest_preview_jpeg(self) -> bytes | None:
        async with self._preview_lock:
            return self._latest_preview_jpeg

    async def latest_preview(self) -> tuple[int, bytes | None]:
        async with self._preview_lock:
            return self._latest_preview_sequence, self._latest_preview_jpeg

    async def latest_frame_copy(self) -> np.ndarray | None:
        async with self._preview_lock:
            return None if self._latest_frame is None else self._latest_frame.copy()

    def encode_preview_frame(self, frame: np.ndarray) -> bytes:
        preview = self._resize_preview_frame(frame)
        encoded, image = cv2.imencode(
            ".jpg",
            preview,
            [int(cv2.IMWRITE_JPEG_QUALITY), int(self.config.live_preview_jpeg_quality)],
        )
        if not encoded:
            raise RuntimeError("Camera preview JPEG encode failed")
        return image.tobytes()

    def _resize_preview_frame(self, frame: np.ndarray) -> np.ndarray:
        max_width = int(self.config.live_preview_max_width)
        height, width = frame.shape[:2]
        if width <= max_width:
            return frame
        scale = max_width / float(width)
        return cv2.resize(frame, (max_width, max(int(height * scale), 1)), interpolation=cv2.INTER_AREA)

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
        self.enqueue_event_video(event.id)

        settings = self.storage.get_settings()
        if settings.sound_on_detection:
            self.enqueue_detection_sound(settings.output_device)

        if self.config.action_webhook_url:
            sent, error = await send_detection_webhook(self.config.action_webhook_url, event)
            with self.storage.connect() as conn:
                conn.execute(
                    "UPDATE events SET webhook_sent = ?, webhook_error = ? WHERE id = ?",
                    (int(sent), error, event.id),
                )
        return True

    def enqueue_event_video(self, event_id: int) -> None:
        task = asyncio.create_task(self.record_event_video(event_id))
        self._video_tasks.add(task)
        task.add_done_callback(self._video_tasks.discard)

    async def record_event_video(self, event_id: int) -> None:
        try:
            video_path = await self._record_event_video(event_id)
        except Exception as exc:
            self.last_error = str(exc)
            return
        if video_path is not None:
            self.storage.update_event_video_path(event_id, video_path)

    async def _record_event_video(self, event_id: int) -> Path | None:
        first_frame = await self.latest_frame_copy()
        if first_frame is None:
            return None

        path = self.config.snapshot_dir / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}-{event_id}-{uuid4().hex}.mp4"
        path.parent.mkdir(parents=True, exist_ok=True)
        fps = max(float(self.config.event_video_fps), 1.0)
        total_frames = max(int(float(self.config.event_video_seconds) * fps), 1)
        height, width = first_frame.shape[:2]
        writer = cv2.VideoWriter(
            str(path),
            cv2.VideoWriter_fourcc(*"mp4v"),
            fps,
            (width, height),
        )
        if not writer.isOpened():
            raise RuntimeError(f"Could not write event video to {path}")

        try:
            frame_interval = 1.0 / fps
            next_frame_at = asyncio.get_running_loop().time()
            last_frame = first_frame
            for _ in range(total_frames):
                frame = await self.latest_frame_copy()
                if frame is not None:
                    if frame.shape[:2] != (height, width):
                        frame = cv2.resize(frame, (width, height))
                    last_frame = frame
                writer.write(last_frame)
                next_frame_at += frame_interval
                await asyncio.sleep(max(0.0, next_frame_at - asyncio.get_running_loop().time()))
        finally:
            writer.release()

        return path

    async def _stop_video_tasks(self) -> None:
        if not self._video_tasks:
            return
        for task in list(self._video_tasks):
            task.cancel()
        await asyncio.gather(*self._video_tasks, return_exceptions=True)
        self._video_tasks.clear()

    async def play_detection_sound(self, output_device: str) -> None:
        try:
            result = await self._call_blocking(
                "Play detection sound",
                lambda: play_test_beep(output_device),
                self.config.audio_playback_timeout_seconds,
            )
        except Exception as exc:
            self.last_error = str(exc)
            return
        if not result.ok:
            self.last_error = result.error
        else:
            await self.refresh_audio_status(output_device)

    async def refresh_audio_status(self, output_device: str | None = None) -> None:
        selected_output = output_device or self.storage.get_settings().output_device
        try:
            diagnostics = await self._call_blocking(
                "Discover audio outputs",
                lambda: get_audio_diagnostics(selected_output),
                self.config.audio_discovery_timeout_seconds + 1.0,
            )
        except Exception as exc:
            self.audio_ready = False
            self.audio_backend = None
            self.audio_output_label = None
            self.audio_status = str(exc)
            return

        self.audio_ready = diagnostics.selected_output_available
        self.audio_backend = diagnostics.resolved_backend
        self.audio_output_label = diagnostics.default_output_name
        if diagnostics.selected_output_available:
            label = diagnostics.default_output_name if selected_output == "auto" else selected_output
            backend = diagnostics.resolved_backend or "unknown"
            self.audio_status = f"Ready via {backend}: {label}"
        else:
            self.audio_status = diagnostics.recommended_fix or "No usable audio output"

    def enqueue_detection_sound(self, output_device: str) -> None:
        self._ensure_sound_worker()
        try:
            self._sound_queue.put_nowait(output_device)
        except asyncio.QueueFull:
            self.last_error = "Detection sound skipped because playback is already pending"

    def _ensure_sound_worker(self) -> None:
        if self._sound_task and not self._sound_task.done():
            return
        self._sound_task = asyncio.create_task(self._sound_worker())

    async def _sound_worker(self) -> None:
        while True:
            output_device = await self._sound_queue.get()
            if output_device is None:
                break
            await self.play_detection_sound(output_device)

    async def _stop_sound_worker(self) -> None:
        if self._sound_task and not self._sound_task.done():
            try:
                self._sound_queue.put_nowait(None)
            except asyncio.QueueFull:
                try:
                    _ = self._sound_queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                self._sound_queue.put_nowait(None)
            try:
                await asyncio.wait_for(asyncio.shield(self._sound_task), timeout=self.config.detector_stop_timeout_seconds)
            except TimeoutError:
                self.last_error = "Audio worker did not stop before timeout"
                self._sound_task.cancel()

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
