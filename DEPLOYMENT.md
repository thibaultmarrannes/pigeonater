# Production Deployment

This project is designed to publish a Docker image from GitHub Actions and let the NUC pull new versions automatically.

## Image Publishing

The workflow in `.github/workflows/container.yml` does this on pushes to `DEV`, `production`, `main`, or `master`:

1. Install Python dependencies.
2. Run `pytest`.
3. Build the Docker image.
4. Push tags to GitHub Container Registry:
   - `ghcr.io/<owner>/<repo>:DEV`, `:production`, `:main`, or `:master`
   - `ghcr.io/<owner>/<repo>:sha-<commit>`
   - `ghcr.io/<owner>/<repo>:latest` only from the `production` branch
   - `ghcr.io/<owner>/<repo>:vX.Y.Z` for git tags like `v1.0.0`

Pull requests run tests only and do not publish images.

## First-Time NUC Setup

Install Docker and confirm the webcam is visible:

```bash
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-plugin v4l-utils
sudo usermod -aG docker "$USER"
v4l2-ctl --list-devices
```

Log out and back in after adding your user to the Docker group.

If the GitHub package is private, log in to GHCR on the NUC:

```bash
echo "<github-token-with-read-packages>" | docker login ghcr.io -u <github-user> --password-stdin
```

Public packages do not need a login.

## Production Compose

Create a `.env` file next to `docker-compose.prod.yml`:

```bash
PIDGEONATER_IMAGE=ghcr.io/thibaultmarrannes/pigeonater:latest
MODEL_NAME=yolo11n.pt
ACTION_WEBHOOK_URL=
```

Start the service:

```bash
docker compose -f docker-compose.prod.yml up -d
```

Open `http://<nuc-ip>:8080`, go to Settings, and select the visible `/dev/video*` camera.

## Lighthouse or Auto-Updater Flow

Point Lighthouse at the stable production image:

```text
ghcr.io/<owner>/<repo>:latest
```

When GitHub Actions publishes a new image for that tag, Lighthouse can pull it and restart the container. The container exposes a healthcheck that calls:

```text
GET /healthz
```

## Branch Flow

- Commit active development to `DEV`.
- Use `ghcr.io/thibaultmarrannes/pigeonater:DEV` for test devices that should follow development builds.
- Merge or fast-forward `production` when a version should roll out to remote production devices.
- Production devices should track `ghcr.io/thibaultmarrannes/pigeonater:latest`.

## Rollback

Each build also publishes a commit-specific tag:

```text
ghcr.io/<owner>/<repo>:sha-<commit>
```

To roll back, set `PIDGEONATER_IMAGE` to a known-good SHA tag and restart:

```bash
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
```
