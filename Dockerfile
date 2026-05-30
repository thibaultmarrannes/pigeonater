FROM python:3.11-slim

ARG ARDUINO_CLI_VERSION="1.5.0"
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
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 curl v4l-utils libportaudio2 alsa-utils pulseaudio-utils ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | BINDIR=/usr/local/bin sh -s "$ARDUINO_CLI_VERSION" \
    && arduino-cli core update-index \
    && arduino-cli core install arduino:avr \
    && arduino-cli lib install Servo

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY firmware ./firmware

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8080/healthz || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
