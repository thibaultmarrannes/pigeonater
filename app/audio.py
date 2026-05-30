from __future__ import annotations

from dataclasses import dataclass
import math
import os
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import wave

import numpy as np

from app.schemas import AudioDiagnostics, AudioOutputDevice

sd = None

_ALSA_DEVICE_PATTERN = re.compile(
    r"^card\s+(?P<card_index>\d+):\s+(?P<card_id>[^ ]+)\s+\[(?P<card_name>.+?)\],\s+device\s+(?P<device_index>\d+):\s+(?P<device_id>[^ ]+)\s+\[(?P<device_name>.+?)\]$"
)


@dataclass(frozen=True)
class AudioTarget:
    backend: str
    target_id: str
    label: str
    play_device: str | int | None
    available: bool


@dataclass
class TestBeepResult:
    ok: bool
    error: str | None = None


def list_audio_output_devices(selected_id: str) -> list[AudioOutputDevice]:
    targets = discover_audio_targets()
    devices = [
        AudioOutputDevice(
            id="auto",
            name=_auto_label(targets),
            selected=selected_id == "auto",
            available=bool(targets),
        )
    ]

    for target in targets:
        devices.append(
            AudioOutputDevice(
                id=target.target_id,
                name=target.label,
                selected=selected_id == target.target_id,
                available=target.available,
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
    try:
        target = resolve_audio_target(output_device)
    except RuntimeError as exc:
        return TestBeepResult(ok=False, error=f"Test beep failed: {exc}")

    try:
        if target.backend == "pulse":
            _play_pulse_beep(target.play_device, duration_seconds=duration_seconds, sample_rate=sample_rate)
        elif target.backend == "alsa":
            _play_alsa_beep(target.play_device, duration_seconds=duration_seconds, sample_rate=sample_rate)
        elif target.backend == "portaudio":
            _play_portaudio_beep(target.play_device, duration_seconds=duration_seconds, sample_rate=sample_rate)
        else:
            raise RuntimeError(f"Unsupported audio backend {target.backend}")
        return TestBeepResult(ok=True)
    except Exception as exc:
        return TestBeepResult(ok=False, error=f"Test beep failed: {exc}")


def get_audio_diagnostics(selected_id: str) -> AudioDiagnostics:
    errors: list[str] = []
    targets = discover_audio_targets(errors)
    default_target = targets[0] if targets else None
    resolved_target = _resolved_target_for_selection(selected_id, targets)
    dev_snd_entries = _dev_snd_entries()
    pulse_server = os.environ.get("PULSE_SERVER")
    pulse_runtime_present = _pulse_runtime_present()
    host_apis = _portaudio_host_apis(errors)
    aplay_devices = _aplay_devices_from_parsed(_parse_aplay_devices([]))

    return AudioDiagnostics(
        backend="auto",
        resolved_backend=None if resolved_target is None else resolved_target.backend,
        default_output_id=None if default_target is None else default_target.target_id,
        default_output_name=None if default_target is None else default_target.label,
        selected_output_id=selected_id,
        selected_output_available=resolved_target is not None,
        available_output_count=len(targets),
        dev_snd_present=bool(dev_snd_entries),
        dev_snd_entries=dev_snd_entries,
        pulse_server=pulse_server,
        pulse_runtime_present=pulse_runtime_present,
        host_apis=host_apis,
        aplay_devices=aplay_devices,
        errors=errors,
        recommended_fix=_recommended_fix(
            selected_id=selected_id,
            resolved_target=resolved_target,
            output_count=len(targets),
            dev_snd_present=bool(dev_snd_entries),
            pulse_server=pulse_server,
            pulse_runtime_present=pulse_runtime_present,
        ),
    )


def resolve_audio_target(selected_id: str) -> AudioTarget:
    targets = discover_audio_targets()
    resolved = _resolved_target_for_selection(selected_id, targets)
    if resolved is None:
        raise RuntimeError("No output device available")
    return resolved


def discover_audio_targets(errors: list[str] | None = None) -> list[AudioTarget]:
    issues = errors if errors is not None else []
    targets: list[AudioTarget] = []
    seen_ids: set[str] = set()

    for target in _pulse_targets(issues):
        if target.target_id in seen_ids:
            continue
        seen_ids.add(target.target_id)
        targets.append(target)

    for target in _alsa_targets(issues):
        if target.target_id in seen_ids:
            continue
        seen_ids.add(target.target_id)
        targets.append(target)

    for target in _portaudio_targets(issues):
        if target.target_id in seen_ids:
            continue
        seen_ids.add(target.target_id)
        targets.append(target)

    return targets


def _resolved_target_for_selection(selected_id: str, targets: list[AudioTarget]) -> AudioTarget | None:
    if selected_id == "auto":
        return targets[0] if targets else None

    legacy_portaudio = None
    if selected_id.isdigit():
        legacy_portaudio = f"pa:{selected_id}"

    for target in targets:
        if target.target_id == selected_id or target.target_id == legacy_portaudio:
            return target
    return None


def _alsa_targets(errors: list[str]) -> list[AudioTarget]:
    devices = _parse_aplay_devices(errors)
    targets: list[AudioTarget] = []
    for device in devices:
        spec = f"plughw:CARD={device['card_id']},DEV={device['device_index']}"
        label = f"ALSA: {device['card_name']} / {device['device_name']}"
        targets.append(
            AudioTarget(
                backend="alsa",
                target_id=f"alsa:{spec}",
                label=label,
                play_device=spec,
                available=True,
            )
        )
    return targets


def _pulse_targets(errors: list[str]) -> list[AudioTarget]:
    sinks = _parse_pactl_sinks(errors)
    targets: list[AudioTarget] = []
    for sink in sinks:
        targets.append(
            AudioTarget(
                backend="pulse",
                target_id=f"pulse:{sink['name']}",
                label=f"Pulse: {sink['description']}",
                play_device=sink["name"],
                available=True,
            )
        )
    return targets


def _portaudio_targets(errors: list[str]) -> list[AudioTarget]:
    try:
        sounddevice = _sounddevice()
        devices = list(sounddevice.query_devices())
    except Exception as exc:
        errors.append(f"PortAudio query failed: {exc}")
        return []

    targets: list[AudioTarget] = []
    for index, device in enumerate(devices):
        if int(device.get("max_output_channels", 0)) <= 0:
            continue
        targets.append(
            AudioTarget(
                backend="portaudio",
                target_id=f"pa:{index}",
                label=f"PortAudio: {device.get('name', f'Output {index}')}",
                play_device=index,
                available=True,
            )
        )
    return targets


def _auto_label(targets: list[AudioTarget]) -> str:
    if not targets:
        return "Automatic (no output devices found)"
    first = targets[0]
    return f"Automatic ({first.label})"


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


def _play_portaudio_beep(device: str | int | None, *, duration_seconds: float, sample_rate: int) -> None:
    sounddevice = _sounddevice()
    samples = np.linspace(0, duration_seconds, int(sample_rate * duration_seconds), endpoint=False)
    wave_data = 0.2 * np.sin(2 * np.pi * 880 * samples)
    stereo_wave = np.column_stack([wave_data, wave_data]).astype(np.float32)
    try:
        sounddevice.play(stereo_wave, samplerate=sample_rate, device=device, blocking=True)
    finally:
        try:
            sounddevice.stop()
        except Exception:
            pass


def _play_alsa_beep(device: str | int | None, *, duration_seconds: float, sample_rate: int) -> None:
    if not isinstance(device, str) or not device:
        raise RuntimeError("Invalid ALSA output device")

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav_path = Path(tmp.name)
    try:
        _write_beep_wav(wav_path, duration_seconds=duration_seconds, sample_rate=sample_rate)
        result = subprocess.run(
            ["aplay", "-q", "-D", device, str(wav_path)],
            capture_output=True,
            check=False,
            text=True,
            timeout=max(2.0, duration_seconds + 2.0),
        )
    finally:
        wav_path.unlink(missing_ok=True)

    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(detail or f"aplay exited with {result.returncode}")


def _play_pulse_beep(device: str | int | None, *, duration_seconds: float, sample_rate: int) -> None:
    if not isinstance(device, str) or not device:
        raise RuntimeError("Invalid Pulse output device")

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav_path = Path(tmp.name)
    try:
        _write_beep_wav(wav_path, duration_seconds=duration_seconds, sample_rate=sample_rate)
        result = subprocess.run(
            ["paplay", "--device", device, str(wav_path)],
            capture_output=True,
            check=False,
            text=True,
            timeout=max(2.0, duration_seconds + 2.0),
        )
    finally:
        wav_path.unlink(missing_ok=True)

    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(detail or f"paplay exited with {result.returncode}")


def _write_beep_wav(path: Path, *, duration_seconds: float, sample_rate: int) -> None:
    frame_count = int(sample_rate * duration_seconds)
    amplitude = 0.25
    frequency = 880.0
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(2)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        frames = bytearray()
        for index in range(frame_count):
            sample = int(amplitude * 32767 * math.sin(2 * math.pi * frequency * index / sample_rate))
            packed = struct.pack("<h", sample)
            frames.extend(packed)
            frames.extend(packed)
        wav_file.writeframes(bytes(frames))


def _portaudio_host_apis(errors: list[str]) -> list[str]:
    try:
        sounddevice = _sounddevice()
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


def _parse_aplay_devices(errors: list[str]) -> list[dict[str, str]]:
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
        detail = result.stderr.strip() or result.stdout.strip()
        if detail:
            errors.append(f"aplay -l returned {result.returncode}: {detail}")
        return []

    devices: list[dict[str, str]] = []
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        match = _ALSA_DEVICE_PATTERN.match(line)
        if not match:
            continue
        devices.append(match.groupdict())
    return devices


def _parse_pactl_sinks(errors: list[str]) -> list[dict[str, str]]:
    try:
        result = subprocess.run(
            ["pactl", "list", "short", "sinks"],
            capture_output=True,
            check=False,
            text=True,
            timeout=1.5,
        )
    except FileNotFoundError:
        errors.append("pactl is not installed")
        return []
    except (OSError, subprocess.SubprocessError) as exc:
        errors.append(f"pactl failed: {exc}")
        return []

    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        if detail:
            errors.append(f"pactl list short sinks returned {result.returncode}: {detail}")
        return []

    sinks: list[dict[str, str]] = []
    for raw_line in result.stdout.splitlines():
        parts = raw_line.split("\t")
        if len(parts) < 2:
            continue
        sink_name = parts[1].strip()
        description = sink_name
        if len(parts) >= 5 and parts[4].strip():
            description = parts[4].strip()
        sinks.append({"name": sink_name, "description": description})
    return sinks


def _aplay_devices(errors: list[str]) -> list[str]:
    devices = _parse_aplay_devices(errors)
    return _aplay_devices_from_parsed(devices)


def _aplay_devices_from_parsed(devices: list[dict[str, str]]) -> list[str]:
    return [f"card {device['card_index']}: {device['card_name']} / {device['device_name']}" for device in devices]


def _recommended_fix(
    *,
    selected_id: str,
    resolved_target: AudioTarget | None,
    output_count: int,
    dev_snd_present: bool,
    pulse_server: str | None,
    pulse_runtime_present: bool,
) -> str | None:
    if output_count == 0 and pulse_server:
        return "Pulse or PipeWire is configured, but the container cannot query any sinks. Mount the Pulse socket into the container and verify `pactl list short sinks` works inside it."
    if output_count == 0 and not dev_snd_present and not pulse_server and not pulse_runtime_present:
        return "Container cannot see Linux audio devices. Mount /dev/snd into the container and restart it."
    if output_count == 0 and pulse_server and not pulse_runtime_present:
        return "PulseAudio is configured but its runtime socket is missing in the container. Prefer ALSA on the NUC or mount the Pulse or PipeWire socket explicitly."
    if output_count == 0:
        return "No output devices are visible. Check the host speaker setup, then reopen Settings and test again."
    if resolved_target is None:
        if selected_id == "auto":
            return "Automatic output selection could not resolve a usable speaker."
        return "The saved output device is no longer visible. Select one of the available outputs and save settings."
    if resolved_target.backend != "alsa" and os.name != "nt" and Path("/dev/snd").exists():
        return "A PortAudio fallback is active. For the NUC, prefer one of the ALSA outputs listed above."
    return None
