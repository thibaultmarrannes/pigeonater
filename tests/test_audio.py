from app.audio import get_audio_diagnostics, list_audio_output_devices, play_test_beep


class FakeSoundDevice:
    def __init__(self):
        self.play_calls = []
        self.stopped = False
        self.default = type("Default", (), {"device": [0, 1]})()

    def query_devices(self, device=None, kind=None):
        devices = [
            {"name": "Input only", "max_output_channels": 0},
            {"name": "Built-in speakers", "max_output_channels": 2},
        ]
        if device is None:
            return devices
        return devices[int(device)]

    def play(self, data, *, samplerate, device, blocking):
        self.play_calls.append({"shape": data.shape, "samplerate": samplerate, "device": device, "blocking": blocking})

    def stop(self):
        self.stopped = True

    def query_hostapis(self):
        return [{"name": "Core Audio"}]


class FakeDefaultPair:
    def __init__(self, input_device, output_device):
        self.input = input_device
        self.output = output_device


class FailingSoundDevice(FakeSoundDevice):
    def play(self, data, *, samplerate, device, blocking):
        raise RuntimeError("no output")


def test_list_audio_output_devices_filters_output_devices(monkeypatch):
    monkeypatch.setattr("app.audio.sd", FakeSoundDevice())

    devices = list_audio_output_devices("1")

    assert [device.id for device in devices] == ["default", "1"]
    assert devices[1].name == "Built-in speakers"
    assert devices[1].selected is True


def test_list_audio_output_devices_keeps_unavailable_selection(monkeypatch):
    monkeypatch.setattr("app.audio.sd", FakeSoundDevice())

    devices = list_audio_output_devices("9")

    assert devices[-1].id == "9"
    assert devices[-1].available is False
    assert devices[-1].selected is True


def test_play_test_beep_uses_selected_device(monkeypatch):
    fake = FakeSoundDevice()
    monkeypatch.setattr("app.audio.sd", fake)

    result = play_test_beep("1")

    assert result.ok is True
    assert fake.play_calls[0]["device"] == 1
    assert fake.play_calls[0]["blocking"] is True
    assert fake.stopped is True


def test_play_test_beep_resolves_default_output_device(monkeypatch):
    fake = FakeSoundDevice()
    monkeypatch.setattr("app.audio.sd", fake)

    result = play_test_beep("default")

    assert result.ok is True
    assert fake.play_calls[0]["device"] == 1


def test_play_test_beep_falls_back_when_default_is_invalid(monkeypatch):
    fake = FakeSoundDevice()
    fake.default.device = [-1, -1]
    monkeypatch.setattr("app.audio.sd", fake)

    result = play_test_beep("default")

    assert result.ok is True
    assert fake.play_calls[0]["device"] == 1


def test_play_test_beep_uses_default_pair_output(monkeypatch):
    fake = FakeSoundDevice()
    fake.default.device = FakeDefaultPair(0, 1)
    monkeypatch.setattr("app.audio.sd", fake)

    result = play_test_beep("default")

    assert result.ok is True
    assert fake.play_calls[0]["device"] == 1


def test_play_test_beep_reports_failure(monkeypatch):
    monkeypatch.setattr("app.audio.sd", FailingSoundDevice())

    result = play_test_beep("default")

    assert result.ok is False
    assert "no output" in result.error


def test_get_audio_diagnostics_reports_linux_visibility(monkeypatch):
    monkeypatch.setattr("app.audio.sd", FakeSoundDevice())
    monkeypatch.setattr("app.audio._dev_snd_entries", lambda: ["controlC0", "pcmC0D0p"])
    monkeypatch.setattr("app.audio._pulse_runtime_present", lambda: False)
    monkeypatch.setattr("app.audio._aplay_devices", lambda errors: ["card 0: Device [USB Audio Device], device 0: USB Audio [USB Audio]"])

    diagnostics = get_audio_diagnostics("default")

    assert diagnostics.backend == "portaudio"
    assert diagnostics.default_output_id == "1"
    assert diagnostics.default_output_name == "Built-in speakers"
    assert diagnostics.available_output_count == 1
    assert diagnostics.dev_snd_present is True
    assert diagnostics.selected_output_available is True
    assert diagnostics.host_apis == ["Core Audio"]
    assert diagnostics.aplay_devices


def test_get_audio_diagnostics_recommends_mounting_dev_snd(monkeypatch):
    monkeypatch.setattr("app.audio.sd", FakeSoundDevice())
    monkeypatch.setattr("app.audio._dev_snd_entries", lambda: [])
    monkeypatch.setattr("app.audio._pulse_runtime_present", lambda: False)
    monkeypatch.setattr("app.audio._aplay_devices", lambda errors: [])

    diagnostics = get_audio_diagnostics("default")

    assert diagnostics.dev_snd_present is False
    assert "Mount /dev/snd" in diagnostics.recommended_fix
