import subprocess

from app.hardware import (
    DISABLED_DEVICE,
    cached_hardware_status,
    flash_arduino_firmware,
    list_hardware_devices,
    send_led_blink,
    send_hardware_command,
    send_relay_pulse,
    send_servo_sweep,
)


class FakeSerial:
    commands = []

    def __init__(self, device, baudrate, timeout, write_timeout, response=b"OK DONE\n"):
        self.device = device
        self.baudrate = baudrate
        self.timeout = timeout
        self.write_timeout = write_timeout
        self.response = response

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def reset_input_buffer(self):
        pass

    def write(self, payload):
        self.commands.append(payload.decode("ascii"))

    def flush(self):
        pass

    def readline(self):
        return self.response


def test_list_hardware_devices_prefers_serial_by_id(tmp_path, monkeypatch):
    by_id = tmp_path / "serial" / "by-id"
    by_id.mkdir(parents=True)
    first = by_id / "usb-Arduino_Uno-if00"
    second = by_id / "usb-Other-if00"
    first.touch()
    second.touch()
    monkeypatch.setattr("app.hardware.glob", lambda pattern: ["/dev/ttyACM0"])

    devices = list_hardware_devices(str(first), by_id_dir=by_id)

    assert [device.path for device in devices] == [DISABLED_DEVICE, str(first), str(second)]
    assert devices[1].selected is True


def test_cached_hardware_status_is_fast_without_arduino():
    status = cached_hardware_status("/dev/serial/by-id/missing")

    assert status.selected_device == "/dev/serial/by-id/missing"
    assert status.available is False
    assert status.connected is False


def test_relay_command_serializes_exactly():
    FakeSerial.commands = []

    result = send_relay_pulse(
        "/dev/ttyACM0",
        750,
        timeout_seconds=0.01,
        serial_factory=FakeSerial,
    )

    assert result.ok is True
    assert FakeSerial.commands == ["RELAY_PULSE 750\n"]


def test_servo_command_serializes_exactly():
    FakeSerial.commands = []

    result = send_servo_sweep(
        "/dev/ttyACM0",
        20,
        160,
        5,
        timeout_seconds=0.01,
        serial_factory=FakeSerial,
    )

    assert result.ok is True
    assert FakeSerial.commands == ["SERVO_SWEEP 20 160 5\n"]


def test_led_blink_command_serializes_exactly():
    FakeSerial.commands = []

    result = send_led_blink(
        "/dev/ttyACM0",
        timeout_seconds=0.01,
        serial_factory=FakeSerial,
    )

    assert result.ok is True
    assert FakeSerial.commands == ["LED_BLINK 3 150\n"]


def test_flash_firmware_runs_compile_and_upload(tmp_path):
    device = tmp_path / "ttyACM0"
    firmware = tmp_path / "firmware"
    device.touch()
    firmware.mkdir()
    calls = []

    def fake_runner(command, capture_output, text, timeout, check):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    result = flash_arduino_firmware(
        str(device),
        firmware_path=firmware,
        fqbn="arduino:avr:uno",
        timeout_seconds=0.01,
        runner=fake_runner,
    )

    assert result.ok is True
    assert calls == [
        ["arduino-cli", "compile", "--fqbn", "arduino:avr:uno", str(firmware)],
        ["arduino-cli", "upload", "-p", str(device), "--fqbn", "arduino:avr:uno", str(firmware)],
    ]


def test_flash_firmware_reports_failed_upload(tmp_path):
    device = tmp_path / "ttyACM0"
    firmware = tmp_path / "firmware"
    device.touch()
    firmware.mkdir()

    def fake_runner(command, capture_output, text, timeout, check):
        if "upload" in command:
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="upload failed")
        return subprocess.CompletedProcess(command, 0, stdout="compiled", stderr="")

    result = flash_arduino_firmware(
        str(device),
        firmware_path=firmware,
        fqbn="arduino:avr:uno",
        timeout_seconds=0.01,
        runner=fake_runner,
    )

    assert result.ok is False
    assert result.error == "upload failed"


def test_serial_error_returns_command_failure():
    class FailingSerial:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("serial failed")

    result = send_hardware_command(
        "/dev/ttyACM0",
        "PING",
        timeout_seconds=0.01,
        serial_factory=FailingSerial,
    )

    assert result.ok is False
    assert result.error == "serial failed"


def test_disabled_device_returns_command_failure():
    result = send_hardware_command(
        DISABLED_DEVICE,
        "PING",
        timeout_seconds=0.01,
        serial_factory=FakeSerial,
    )

    assert result.ok is False
    assert result.error == "Arduino hardware is disabled"
