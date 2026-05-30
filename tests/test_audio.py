from app.audio import get_audio_diagnostics, list_audio_output_devices, play_test_beep, resolve_audio_target


class FakeSoundDevice:
    def __init__(self):
        self.play_calls = []
        self.stopped = False

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


class FailingSoundDevice(FakeSoundDevice):
    def play(self, data, *, samplerate, device, blocking):
        raise RuntimeError("no output")


def test_list_audio_output_devices_prefers_alsa(monkeypatch):
    monkeypatch.setattr("app.audio.sd", FakeSoundDevice())
    monkeypatch.setattr(
        "app.audio._parse_aplay_devices",
        lambda errors: [
            {
                "card_index": "0",
                "card_id": "Device",
                "card_name": "USB Audio Device",
                "device_index": "0",
                "device_id": "USB",
                "device_name": "USB Audio",
            }
        ],
    )

    devices = list_audio_output_devices("auto")

    assert devices[0].id == "auto"
    assert devices[0].selected is True
    assert devices[1].id == "alsa:plughw:CARD=Device,DEV=0"
    assert devices[1].name.startswith("ALSA:")


def test_list_audio_output_devices_keeps_unavailable_selection(monkeypatch):
    monkeypatch.setattr("app.audio.sd", FakeSoundDevice())
    monkeypatch.setattr("app.audio._parse_aplay_devices", lambda errors: [])

    devices = list_audio_output_devices("alsa:plughw:CARD=Missing,DEV=0")

    assert devices[-1].id == "alsa:plughw:CARD=Missing,DEV=0"
    assert devices[-1].available is False
    assert devices[-1].selected is True


def test_resolve_audio_target_supports_legacy_portaudio_id(monkeypatch):
    monkeypatch.setattr("app.audio.sd", FakeSoundDevice())
    monkeypatch.setattr("app.audio._parse_aplay_devices", lambda errors: [])

    target = resolve_audio_target("1")

    assert target.backend == "portaudio"
    assert target.target_id == "pa:1"
    assert target.play_device == 1


def test_play_test_beep_uses_selected_portaudio_device(monkeypatch):
    fake = FakeSoundDevice()
    monkeypatch.setattr("app.audio.sd", fake)
    monkeypatch.setattr("app.audio._parse_aplay_devices", lambda errors: [])

    result = play_test_beep("pa:1")

    assert result.ok is True
    assert fake.play_calls[0]["device"] == 1
    assert fake.play_calls[0]["blocking"] is True
    assert fake.stopped is True


def test_play_test_beep_prefers_alsa_in_auto_mode(monkeypatch):
    monkeypatch.setattr("app.audio.sd", FakeSoundDevice())
    monkeypatch.setattr(
        "app.audio._parse_aplay_devices",
        lambda errors: [
            {
                "card_index": "0",
                "card_id": "Device",
                "card_name": "USB Audio Device",
                "device_index": "0",
                "device_id": "USB",
                "device_name": "USB Audio",
            }
        ],
    )
    calls = []
    monkeypatch.setattr("app.audio._play_alsa_beep", lambda device, **kwargs: calls.append(device))

    result = play_test_beep("auto")

    assert result.ok is True
    assert calls == ["plughw:CARD=Device,DEV=0"]


def test_play_test_beep_reports_failure(monkeypatch):
    monkeypatch.setattr("app.audio.sd", FailingSoundDevice())
    monkeypatch.setattr("app.audio._parse_aplay_devices", lambda errors: [])

    result = play_test_beep("auto")

    assert result.ok is False
    assert "no output" in result.error


def test_get_audio_diagnostics_reports_linux_visibility(monkeypatch):
    monkeypatch.setattr("app.audio.sd", FakeSoundDevice())
    monkeypatch.setattr(
        "app.audio._parse_aplay_devices",
        lambda errors: [
            {
                "card_index": "0",
                "card_id": "Device",
                "card_name": "USB Audio Device",
                "device_index": "0",
                "device_id": "USB",
                "device_name": "USB Audio",
            }
        ],
    )
    monkeypatch.setattr("app.audio._dev_snd_entries", lambda: ["controlC0", "pcmC0D0p"])
    monkeypatch.setattr("app.audio._pulse_runtime_present", lambda: False)

    diagnostics = get_audio_diagnostics("auto")

    assert diagnostics.backend == "auto"
    assert diagnostics.resolved_backend == "alsa"
    assert diagnostics.default_output_id == "alsa:plughw:CARD=Device,DEV=0"
    assert diagnostics.default_output_name == "ALSA: USB Audio Device / USB Audio"
    assert diagnostics.available_output_count >= 1
    assert diagnostics.dev_snd_present is True
    assert diagnostics.selected_output_available is True
    assert diagnostics.host_apis == ["Core Audio"]
    assert diagnostics.aplay_devices == ["card 0: USB Audio Device / USB Audio"]


def test_get_audio_diagnostics_recommends_mounting_dev_snd(monkeypatch):
    monkeypatch.setattr("app.audio.sd", FakeSoundDevice())
    monkeypatch.setattr("app.audio._parse_aplay_devices", lambda errors: [])
    monkeypatch.setattr("app.audio._portaudio_targets", lambda errors: [])
    monkeypatch.setattr("app.audio._dev_snd_entries", lambda: [])
    monkeypatch.setattr("app.audio._pulse_runtime_present", lambda: False)

    diagnostics = get_audio_diagnostics("auto")

    assert diagnostics.dev_snd_present is False
    assert "Mount /dev/snd" in diagnostics.recommended_fix
