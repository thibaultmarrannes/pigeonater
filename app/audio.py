from dataclasses import dataclass

import numpy as np

from app.schemas import AudioOutputDevice

sd = None


@dataclass
class TestBeepResult:
    ok: bool
    error: str | None = None


def list_audio_output_devices(selected_id: str) -> list[AudioOutputDevice]:
    devices = [
        AudioOutputDevice(
            id="default",
            name="System default output",
            selected=selected_id == "default",
            available=True,
        )
    ]

    sounddevice = _sounddevice()
    for index, device in enumerate(sounddevice.query_devices()):
        if int(device.get("max_output_channels", 0)) <= 0:
            continue
        device_id = str(index)
        devices.append(
            AudioOutputDevice(
                id=device_id,
                name=str(device.get("name", f"Output {device_id}")),
                selected=selected_id == device_id,
                available=True,
            )
        )

    if selected_id not in {device.id for device in devices}:
        devices.append(
            AudioOutputDevice(
                id=selected_id,
                name=f"Unavailable output {selected_id}",
                selected=True,
                available=False,
            )
        )

    return devices


def play_test_beep(output_device: str, *, duration_seconds: float = 0.35, sample_rate: int = 44100) -> TestBeepResult:
    sounddevice = _sounddevice()
    device = None if output_device == "default" else int(output_device)
    samples = np.linspace(0, duration_seconds, int(sample_rate * duration_seconds), endpoint=False)
    wave = 0.2 * np.sin(2 * np.pi * 880 * samples)
    stereo_wave = np.column_stack([wave, wave]).astype(np.float32)

    try:
        sounddevice.play(stereo_wave, samplerate=sample_rate, device=device, blocking=True)
        return TestBeepResult(ok=True)
    except Exception as exc:
        return TestBeepResult(ok=False, error=f"Test beep failed: {exc}")
    finally:
        try:
            sounddevice.stop()
        except Exception:
            pass


def _sounddevice():
    global sd
    if sd is not None:
        return sd
    try:
        import sounddevice as imported_sounddevice
    except ImportError as exc:
        raise RuntimeError("sounddevice is not installed") from exc
    sd = imported_sounddevice
    return sd
