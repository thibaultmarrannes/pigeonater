import subprocess

from app.cameras import list_camera_devices


def test_list_camera_devices_skips_non_capture_devices(tmp_path, monkeypatch):
    video_root = tmp_path / "video4linux"
    (video_root / "video0").mkdir(parents=True)
    (video_root / "video1").mkdir()

    monkeypatch.setattr("app.cameras.shutil.which", lambda _: "/usr/bin/v4l2-ctl")

    def fake_run(command, **kwargs):
        device = command[2]
        if device == "/dev/video0":
            return subprocess.CompletedProcess(command, 0, stdout="Device Caps : Video Capture\n", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="Device Caps : Metadata Capture\n", stderr="")

    monkeypatch.setattr("app.cameras.subprocess.run", fake_run)

    cameras = list_camera_devices("/dev/video0", sys_class_path=video_root)

    assert [camera.path for camera in cameras] == ["/dev/video0"]
    assert cameras[0].available is True


def test_list_camera_devices_keeps_selected_unavailable_device(tmp_path, monkeypatch):
    video_root = tmp_path / "video4linux"
    video_root.mkdir()

    monkeypatch.setattr("app.cameras.shutil.which", lambda _: "/usr/bin/v4l2-ctl")

    cameras = list_camera_devices("/dev/video9", sys_class_path=video_root)

    assert len(cameras) == 1
    assert cameras[0].path == "/dev/video9"
    assert cameras[0].selected is True
    assert cameras[0].available is False
