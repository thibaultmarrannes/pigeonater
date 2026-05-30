from glob import glob
from pathlib import Path
import shutil
import subprocess
from time import sleep
from typing import Callable

from app.schemas import HardwareCommandResult, HardwareDevice, HardwareStatus

DISABLED_DEVICE = "none"
BAUD_RATE = 115200


def list_hardware_devices(
    selected_device: str,
    *,
    by_id_dir: Path = Path("/dev/serial/by-id"),
) -> list[HardwareDevice]:
    paths = _discover_serial_paths(by_id_dir)
    devices = [
        HardwareDevice(
            path=DISABLED_DEVICE,
            name="Disabled",
            selected=selected_device == DISABLED_DEVICE,
            available=True,
        )
    ]
    devices.extend(
        HardwareDevice(
            path=path,
            name=_device_label(path),
            selected=path == selected_device,
            available=True,
        )
        for path in paths
    )
    if selected_device != DISABLED_DEVICE and selected_device not in paths:
        devices.append(
            HardwareDevice(
                path=selected_device,
                name=f"{selected_device} (not available)",
                selected=True,
                available=False,
            )
        )
    return devices


def cached_hardware_status(selected_device: str) -> HardwareStatus:
    if selected_device == DISABLED_DEVICE:
        return HardwareStatus(selected_device=selected_device, available=True, connected=False)
    return HardwareStatus(
        selected_device=selected_device,
        available=Path(selected_device).exists(),
        connected=False,
    )


def ping_hardware(selected_device: str, *, timeout_seconds: float) -> HardwareStatus:
    if selected_device == DISABLED_DEVICE:
        return HardwareStatus(selected_device=selected_device, available=True, connected=False)

    result = send_hardware_command(selected_device, "PING", timeout_seconds=timeout_seconds)
    return HardwareStatus(
        selected_device=selected_device,
        available=Path(selected_device).exists(),
        connected=result.ok,
        last_response=result.response,
        last_error=result.error,
    )


def send_relay_pulse(
    selected_device: str,
    pulse_ms: int,
    *,
    timeout_seconds: float,
    serial_factory: Callable | None = None,
) -> HardwareCommandResult:
    return send_hardware_command(
        selected_device,
        f"RELAY_PULSE {pulse_ms}",
        timeout_seconds=timeout_seconds,
        serial_factory=serial_factory,
    )


def send_servo_sweep(
    selected_device: str,
    from_angle: int,
    to_angle: int,
    step_delay_ms: int,
    *,
    timeout_seconds: float,
    serial_factory: Callable | None = None,
) -> HardwareCommandResult:
    return send_hardware_command(
        selected_device,
        f"SERVO_SWEEP {from_angle} {to_angle} {step_delay_ms}",
        timeout_seconds=timeout_seconds,
        serial_factory=serial_factory,
    )


def send_led_blink(
    selected_device: str,
    *,
    timeout_seconds: float,
    serial_factory: Callable | None = None,
) -> HardwareCommandResult:
    return send_hardware_command(
        selected_device,
        "LED_BLINK 3 150",
        timeout_seconds=timeout_seconds,
        serial_factory=serial_factory,
    )


def flash_arduino_firmware(
    selected_device: str,
    *,
    firmware_path: Path,
    fqbn: str,
    timeout_seconds: float,
    cli_path: str = "arduino-cli",
    runner: Callable | None = None,
) -> HardwareCommandResult:
    if selected_device == DISABLED_DEVICE:
        return HardwareCommandResult(ok=False, error="Arduino hardware is disabled", log="Arduino hardware is disabled")
    if not Path(selected_device).exists():
        error = f"Arduino serial device is not available: {selected_device}"
        return HardwareCommandResult(ok=False, error=error, log=error)
    if not firmware_path.exists():
        error = f"Arduino firmware folder is missing: {firmware_path}"
        return HardwareCommandResult(ok=False, error=error, log=error)
    if runner is None and shutil.which(cli_path) is None:
        error = "arduino-cli is not installed in the container"
        return HardwareCommandResult(ok=False, error=error, log=error)

    runner = runner or subprocess.run
    compile_command = [cli_path, "compile", "--fqbn", fqbn, str(firmware_path)]
    upload_command = [cli_path, "upload", "-p", selected_device, "--fqbn", fqbn, str(firmware_path)]

    compile_result = _run_firmware_command(runner, "compile", compile_command, timeout_seconds)
    if not compile_result.ok:
        return compile_result

    upload_result = _run_firmware_command(runner, "upload", upload_command, timeout_seconds)
    combined_log = "\n\n".join(part for part in [compile_result.log, upload_result.log] if part)
    if not upload_result.ok:
        upload_result.log = combined_log or upload_result.log
        return upload_result

    return HardwareCommandResult(ok=True, response="OK FIRMWARE_FLASHED", log=combined_log or "OK FIRMWARE_FLASHED")


def send_hardware_command(
    selected_device: str,
    command: str,
    *,
    timeout_seconds: float,
    serial_factory: Callable | None = None,
) -> HardwareCommandResult:
    if selected_device == DISABLED_DEVICE:
        return HardwareCommandResult(ok=False, error="Arduino hardware is disabled")

    if serial_factory is None:
        try:
            from serial import Serial
        except ImportError as exc:
            return HardwareCommandResult(ok=False, error="pyserial is not installed")
        serial_factory = Serial

    try:
        with serial_factory(
            selected_device,
            baudrate=BAUD_RATE,
            timeout=timeout_seconds,
            write_timeout=timeout_seconds,
        ) as serial_port:
            if hasattr(serial_port, "reset_input_buffer"):
                serial_port.reset_input_buffer()
            sleep(min(1.5, max(timeout_seconds / 2.0, 0.0)))
            serial_port.write(f"{command}\n".encode("ascii"))
            if hasattr(serial_port, "flush"):
                serial_port.flush()
            response = serial_port.readline().decode("utf-8", errors="replace").strip()
    except Exception as exc:
        return HardwareCommandResult(ok=False, error=str(exc))

    if not response:
        return HardwareCommandResult(ok=False, error=f"No response from Arduino for {command}")
    if not response.startswith("OK"):
        return HardwareCommandResult(ok=False, response=response, error=response)
    return HardwareCommandResult(ok=True, response=response)


def _run_firmware_command(
    runner: Callable,
    label: str,
    command: list[str],
    timeout_seconds: float,
) -> HardwareCommandResult:
    command_text = " ".join(command)
    try:
        result = runner(command, capture_output=True, text=True, timeout=timeout_seconds, check=False)
    except Exception as exc:
        error = str(exc)
        return HardwareCommandResult(ok=False, error=error, log=f"$ {command_text}\n{error}")

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    output = "\n".join(part for part in [stdout, stderr] if part)
    log = f"$ {command_text}"
    if output:
        log = f"{log}\n{output}"
    log = f"[{label}] exit code {result.returncode}\n{log}"
    if result.returncode != 0:
        return HardwareCommandResult(
            ok=False,
            response=output or None,
            error=output or f"Command failed: {command[0]}",
            log=log,
        )
    return HardwareCommandResult(ok=True, response=output or "OK", log=log)


def _discover_serial_paths(by_id_dir: Path) -> list[str]:
    by_id_paths = []
    if by_id_dir.exists():
        by_id_paths = sorted(str(path) for path in by_id_dir.iterdir())
    if by_id_paths:
        return by_id_paths

    fallback_paths = [*glob("/dev/ttyACM*"), *glob("/dev/ttyUSB*")]
    return sorted(set(fallback_paths))


def _device_label(path: str) -> str:
    if path.startswith("/dev/serial/by-id/"):
        return Path(path).name
    return path
