# Pidgeonater

Pidgeonater is a small LAN appliance for watching a USB webcam, detecting bird events as pigeon candidates, saving evidence snapshots, and reviewing activity from a web dashboard.

V1 intentionally treats pretrained `bird` detections as pigeon candidates. The saved snapshots and metadata are the basis for later threshold tuning or custom pigeon-specific training.

## Features

- FastAPI dashboard on port `8080`
- Logitech-style USB webcam input selectable from the Settings page
- Ultralytics YOLO pretrained detector
- SQLite event/settings database
- Snapshot evidence with bounding boxes
- 7 day default evidence retention
- Start/pause controls and detector settings from the UI
- Optional future action hook through `ACTION_WEBHOOK_URL`

## Local Development

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
uvicorn app.main:app --reload --port 8080
```

Open `http://localhost:8080`.

On a development machine without `/dev/video0`, the dashboard will still load and show a camera error when the detector is enabled.

## Docker Compose

```bash
cp .env.example .env
docker compose up --build
```

Open `http://<nuc-ip>:8080` from another device on the home network.

The Compose file maps the camera device and persists data:

```yaml
device_cgroup_rules:
  - "c 81:* rmw"
volumes:
  - ./data:/data
  - /dev:/dev
```

## Production Images

GitHub Actions can test the app, build the Docker image, and push it to GitHub Container Registry. Remote NUCs can then run `docker-compose.prod.yml` and track the published `latest` image tag from the `production` branch.

For a NUC, start with [DEPLOYMENT.md](DEPLOYMENT.md). It includes the exact commands to install Docker, clone the production branch or download only the Compose files, start the service, and connect Lighthouse.

## Ubuntu NUC Setup

1. Install Ubuntu Server or Desktop on the NUC.
2. Install Docker Engine and the Docker Compose plugin.
3. Plug in the Logitech webcam.
4. Confirm Linux sees the camera:

```bash
sudo apt-get update
sudo apt-get install -y v4l-utils
v4l2-ctl --list-devices
```

The Settings page lists visible `/dev/video*` devices. Pick the camera there, then save settings. If no camera appears, confirm the host sees it with `v4l2-ctl --list-devices` and restart the container after plugging it in.

5. For production use, follow [DEPLOYMENT.md](DEPLOYMENT.md). For local source builds, start the app with:

```bash
docker compose up -d --build
docker compose logs -f
```

## Configuration

Environment variables:

- `MODEL_NAME`: Ultralytics model name or local model path, default `yolo11n.pt`
- `ACTION_WEBHOOK_URL`: optional future integration endpoint

Dashboard settings:

- Camera device
- Detection enabled
- Confidence threshold
- Cooldown seconds between saved events
- Retention days for snapshots and event records

## API

- `GET /api/status`
- `GET /api/events`
- `GET /api/events/{id}`
- `PATCH /api/settings`
- `POST /api/detector/start`
- `POST /api/detector/stop`

## Notes

- The first detector startup downloads the configured YOLO weights if they are not already present in the container.
- The app is designed for LAN-only access in V1. It does not include authentication or HTTPS.
- `ACTION_WEBHOOK_URL` is present as an integration point, but no physical deterrent is configured by default.
