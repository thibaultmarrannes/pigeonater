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
sudo apt-get install -y docker.io docker-compose-plugin git v4l-utils
sudo usermod -aG docker "$USER"
v4l2-ctl --list-devices
```

Log out and back in after adding your user to the Docker group.

If the GitHub package is private, log in to GHCR on the NUC:

```bash
echo "<github-token-with-read-packages>" | docker login ghcr.io -u <github-user> --password-stdin
```

Public packages do not need a login.

## Get the Compose Files

Recommended: clone the repository on the NUC and use the production branch.

```bash
mkdir -p ~/apps
cd ~/apps
git clone -b production https://github.com/thibaultmarrannes/pigeonater.git
cd pigeonater
```

This gives the NUC the production Compose file, `.env.example`, and docs. The app itself still runs from the published GHCR image, not from a local build.

If you do not want a full clone, create a minimal deployment folder instead:

```bash
mkdir -p ~/apps/pigeonater
cd ~/apps/pigeonater
curl -fsSLO https://raw.githubusercontent.com/thibaultmarrannes/pigeonater/production/docker-compose.prod.yml
curl -fsSLO https://raw.githubusercontent.com/thibaultmarrannes/pigeonater/production/.env.example
```

## Production Compose

Create a `.env` file next to `docker-compose.prod.yml`:

```bash
cp .env.example .env
```

Start the service:

```bash
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml logs -f
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

To roll back, set `PIGEONATER_IMAGE` to a known-good SHA tag and restart:

```bash
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
```

## Updating the NUC Files

If you cloned the repo, update the deployment files with:

```bash
cd ~/apps/pigeonater
git fetch origin
git checkout production
git pull --ff-only
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
```

If Lighthouse manages image updates, it can handle the pull/restart step automatically. You only need to update the repo files when `docker-compose.prod.yml` or deployment docs change.
