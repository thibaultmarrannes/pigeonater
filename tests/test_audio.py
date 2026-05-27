from app.audio import list_audio_output_devices, play_test_beep


class FakeSoundDevice:
    def __init__(self):
        self.play_calls = []
        self.stopped = False
        self.default = type("Default", (), {"device": [0, 1]})()

    def query_devices(self):
        return [
            {"name": "Input only", "max_output_channels": 0},
            {"name": "Built-in speakers", "max_output_channels": 2},
        ]

    def play(self, data, *, samplerate, device, blocking):
        self.play_calls.append({"shape": data.shape, "samplerate": samplerate, "device": device, "blocking": blocking})

    def stop(self):
        self.stopped = True


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
