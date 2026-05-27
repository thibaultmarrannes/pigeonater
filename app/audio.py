from dataclasses import dataclass

import numpy as np

from app.schemas import AudioOutputDevice

sd = None


@dataclass
class TestBeepResult:
    ok: bool
    error: str | None = None


def list_audio_output_devices(selected_id: str) -> list[AudioOutputDevice]:
    sounddevice = _sounddevice()
    default_output = _resolve_default_output_device_id(sounddevice)
    devices = [
        AudioOutputDevice(
            id="default",
            name=_default_output_label(sounddevice, default_output),
            selected=selected_id == "default",
            available=default_output is not None,
        )
    ]

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
    try:
        device = _resolve_output_device(sounddevice, output_device)
    except RuntimeError as exc:
        return TestBeepResult(ok=False, error=f"Test beep failed: {exc}")
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


def _resolve_output_device(sounddevice, output_device: str) -> int:
    if output_device != "default":
        return int(output_device)

    default_output = _resolve_default_output_device_id(sounddevice)
    if default_output is not None:
        return default_output

    for index, device in enumerate(sounddevice.query_devices()):
        if int(device.get("max_output_channels", 0)) > 0:
            return index

    raise RuntimeError("No output device available")


def _resolve_default_output_device_id(sounddevice) -> int | None:
    default_device = getattr(sounddevice.default, "device", None)
    default_output = _extract_output_device(default_device)

    if default_output in (None, -1):
        return None

    try:
        device_info = sounddevice.query_devices(default_output, "output")
    except Exception:
        return None

    if int(device_info.get("max_output_channels", 0)) <= 0:
        return None
    return int(default_output)


def _default_output_label(sounddevice, default_output: int | None) -> str:
    if default_output is None:
        return "System default output"
    try:
        device_info = sounddevice.query_devices(default_output, "output")
    except Exception:
        return "System default output"
    return f"System default output ({device_info.get('name', default_output)})"


def _extract_output_device(default_device) -> int | None:
    if default_device is None:
        return None

    output_attr = getattr(default_device, "output", None)
    if output_attr is not None:
        return output_attr

    try:
        return default_device[1]
    except Exception:
        pass

    return default_device
