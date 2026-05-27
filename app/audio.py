from dataclasses import dataclass
import os
from pathlib import Path
import subprocess

import numpy as np

from app.schemas import AudioDiagnostics, AudioOutputDevice

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


def get_audio_diagnostics(selected_id: str) -> AudioDiagnostics:
    sounddevice = _sounddevice()
    errors: list[str] = []

    try:
        raw_devices = list(sounddevice.query_devices())
    except Exception as exc:
        raw_devices = []
        errors.append(f"query_devices failed: {exc}")

    output_devices: list[tuple[int, dict]] = []
    for index, device in enumerate(raw_devices):
        if int(device.get("max_output_channels", 0)) <= 0:
            continue
        output_devices.append((index, device))

    default_output_id = _resolve_default_output_device_id(sounddevice)
    default_output_name = _device_name(raw_devices, default_output_id)
    selected_output_available = _selected_output_available(selected_id, output_devices, default_output_id)
    host_apis = _host_api_names(sounddevice, errors)
    dev_snd_entries = _dev_snd_entries()
    pulse_server = os.environ.get("PULSE_SERVER")
    pulse_runtime_present = _pulse_runtime_present()
    aplay_devices = _aplay_devices(errors)

    return AudioDiagnostics(
        backend="portaudio",
        default_output_id=None if default_output_id is None else str(default_output_id),
        default_output_name=default_output_name,
        selected_output_id=selected_id,
        selected_output_available=selected_output_available,
        available_output_count=len(output_devices),
        dev_snd_present=bool(dev_snd_entries),
        dev_snd_entries=dev_snd_entries,
        pulse_server=pulse_server,
        pulse_runtime_present=pulse_runtime_present,
        host_apis=host_apis,
        aplay_devices=aplay_devices,
        errors=errors,
        recommended_fix=_recommended_fix(
            selected_id=selected_id,
            selected_output_available=selected_output_available,
            output_count=len(output_devices),
            dev_snd_present=bool(dev_snd_entries),
            pulse_server=pulse_server,
            pulse_runtime_present=pulse_runtime_present,
        ),
    )


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


def _device_name(raw_devices: list[dict], device_id: int | None) -> str | None:
    if device_id is None:
        return None
    if 0 <= device_id < len(raw_devices):
        return str(raw_devices[device_id].get("name", device_id))
    return str(device_id)


def _selected_output_available(selected_id: str, output_devices: list[tuple[int, dict]], default_output_id: int | None) -> bool:
    if selected_id == "default":
        return default_output_id is not None or bool(output_devices)
    return any(str(index) == selected_id for index, _ in output_devices)


def _host_api_names(sounddevice, errors: list[str]) -> list[str]:
    try:
        return [str(api.get("name", "unknown")) for api in sounddevice.query_hostapis()]
    except Exception as exc:
        errors.append(f"query_hostapis failed: {exc}")
        return []


def _dev_snd_entries() -> list[str]:
    dev_snd = Path("/dev/snd")
    if not dev_snd.exists() or not dev_snd.is_dir():
        return []
    return sorted(path.name for path in dev_snd.iterdir())


def _pulse_runtime_present() -> bool:
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime_dir:
        return False
    return Path(runtime_dir, "pulse", "native").exists()


def _aplay_devices(errors: list[str]) -> list[str]:
    try:
        result = subprocess.run(
            ["aplay", "-l"],
            capture_output=True,
            check=False,
            text=True,
            timeout=1.0,
        )
    except FileNotFoundError:
        errors.append("aplay is not installed")
        return []
    except (OSError, subprocess.SubprocessError) as exc:
        errors.append(f"aplay failed: {exc}")
        return []

    if result.returncode != 0:
        stderr = result.stderr.strip() or result.stdout.strip()
        if stderr:
            errors.append(f"aplay -l returned {result.returncode}: {stderr}")
        return []

    return [line.strip() for line in result.stdout.splitlines() if line.lstrip().startswith("card ")]


def _recommended_fix(
    *,
    selected_id: str,
    selected_output_available: bool,
    output_count: int,
    dev_snd_present: bool,
    pulse_server: str | None,
    pulse_runtime_present: bool,
) -> str | None:
    if not dev_snd_present and not pulse_server and not pulse_runtime_present:
        return "Container cannot see Linux audio devices. Mount /dev/snd into the container and restart it."
    if output_count == 0 and pulse_server and not pulse_runtime_present:
        return "PulseAudio is configured but its runtime socket is missing in the container. Prefer ALSA on the NUC or mount the Pulse/PipeWire socket explicitly."
    if output_count == 0:
        return "No output devices are visible. Check the host speaker setup, then reopen Settings and test again."
    if not selected_output_available:
        if selected_id == "default":
            return "The system default output is not usable from the container. Select a concrete output device instead."
        return "The saved output device is no longer visible. Select one of the available outputs and save settings."
    return None
