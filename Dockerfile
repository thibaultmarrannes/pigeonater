FROM python:3.11-slim

ARG PIGEONATER_VERSION="dev"
ARG PIGEONATER_COMMIT="unknown"
ARG PIGEONATER_BUILD_DATE="unknown"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIGEONATER_VERSION="${PIGEONATER_VERSION}" \
    PIGEONATER_COMMIT="${PIGEONATER_COMMIT}" \
    PIGEONATER_BUILD_DATE="${PIGEONATER_BUILD_DATE}"

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 curl v4l-utils libportaudio2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8080/healthz || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
