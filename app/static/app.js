async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    cache: "no-store",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json();
}

function formatDate(value) {
  if (!value) return "Never";
  return new Date(value).toLocaleString();
}

function boxLabel(event) {
  return `Box: ${Math.round(event.box.x1)}, ${Math.round(event.box.y1)} to ${Math.round(event.box.x2)}, ${Math.round(event.box.y2)}`;
}

function snapshotSrc(event) {
  const version = encodeURIComponent(`${event.id}-${event.created_at}`);
  return `${event.snapshot_url}?v=${version}`;
}

function videoSrc(event) {
  if (!event.video_url) return "";
  const version = encodeURIComponent(`${event.id}-${event.created_at}`);
  return `${event.video_url}?v=${version}`;
}

function requireVue() {
  if (!window.Vue) {
    throw new Error("Vue failed to load");
  }
  return window.Vue;
}

function dashboard() {
  const { createApp } = requireVue();
  createApp({
    data() {
      return {
        status: null,
        events: [],
        statusError: "",
        timer: null,
        stream: null,
      };
    },
    computed: {
      runningLabel() {
        if (!this.status) return "Loading";
        return this.status.detector_enabled && this.status.worker_running ? "Running" : "Paused";
      },
      cameraLabel() {
        if (!this.status) return "Loading";
        return this.status.camera_connected ? "Connected" : "Disconnected";
      },
      audioLabel() {
        if (!this.status) return "Loading";
        return this.status.audio_ready ? "Ready" : "Not ready";
      },
    },
    async mounted() {
      await this.refresh();
      this.connectStream();
      this.timer = setInterval(this.refresh, 3000);
    },
    unmounted() {
      if (this.timer) clearInterval(this.timer);
      if (this.stream) this.stream.close();
    },
    methods: {
      formatDate,
      boxLabel,
      snapshotSrc,
      videoSrc,
      async refresh() {
        try {
          const [status, events] = await Promise.all([
            requestJson("/api/status"),
            requestJson("/api/events?limit=5"),
          ]);
          this.status = status;
          this.events = events;
          this.statusError = status.last_error || "";
        } catch (error) {
          this.statusError = error.message;
        }
      },
      connectStream() {
        if (!window.EventSource) return;
        this.stream = new EventSource("/api/stream?limit=5");
        this.stream.addEventListener("update", (event) => {
          const payload = JSON.parse(event.data);
          this.status = payload.status;
          this.events = payload.events;
          this.statusError = payload.status.last_error || "";
        });
        this.stream.onerror = () => {
          this.statusError = this.statusError || "Live updates interrupted. Falling back to polling.";
        };
      },
      async startDetector() {
        try {
          this.status = await requestJson("/api/detector/start", { method: "POST" });
          await this.refresh();
        } catch (error) {
          this.statusError = error.message;
        }
      },
      async stopDetector() {
        try {
          this.status = await requestJson("/api/detector/stop", { method: "POST" });
          await this.refresh();
        } catch (error) {
          this.statusError = error.message;
        }
      },
    },
  }).mount("#dashboard-app");
}

function eventsPage() {
  const { createApp } = requireVue();
  createApp({
    data() {
      return {
        events: [],
        error: "",
        deletingVideos: {},
        timer: null,
        stream: null,
      };
    },
    async mounted() {
      await this.refresh();
      this.connectStream();
      this.timer = setInterval(this.refresh, 5000);
    },
    unmounted() {
      if (this.timer) clearInterval(this.timer);
      if (this.stream) this.stream.close();
    },
    methods: {
      formatDate,
      boxLabel,
      snapshotSrc,
      videoSrc,
      isDeletingVideo(event) {
        return Boolean(this.deletingVideos[event.id]);
      },
      async refresh() {
        try {
          this.events = await requestJson("/api/events?limit=100");
          this.error = "";
        } catch (error) {
          this.error = error.message;
        }
      },
      connectStream() {
        if (!window.EventSource) return;
        this.stream = new EventSource("/api/stream?limit=100");
        this.stream.addEventListener("update", (event) => {
          const payload = JSON.parse(event.data);
          this.events = payload.events;
          this.error = "";
        });
        this.stream.onerror = () => {
          this.error = this.error || "Live updates interrupted. Falling back to polling.";
        };
      },
      async deleteEventVideo(event) {
        if (!event.video_url || this.isDeletingVideo(event)) return;

        this.deletingVideos = { ...this.deletingVideos, [event.id]: true };
        try {
          const updated = await requestJson(`/api/events/${event.id}/video`, { method: "DELETE" });
          this.events = this.events.map((item) => (item.id === updated.id ? updated : item));
          this.error = "";
        } catch (error) {
          this.error = error.message;
        } finally {
          const next = { ...this.deletingVideos };
          delete next[event.id];
          this.deletingVideos = next;
        }
      },
    },
  }).mount("#events-app");
}

function livePage() {
  const { createApp } = requireVue();
  createApp({
    data() {
      return {
        status: null,
        statusError: "",
        timer: null,
        streamUrl: `/api/live.mjpg?t=${Date.now()}`,
      };
    },
    computed: {
      runningLabel() {
        if (!this.status) return "Loading";
        return this.status.detector_enabled && this.status.worker_running ? "Running" : "Paused";
      },
      cameraLabel() {
        if (!this.status) return "Loading";
        return this.status.camera_connected ? "Connected" : "Disconnected";
      },
    },
    async mounted() {
      await this.refresh();
      this.timer = setInterval(this.refresh, 2000);
    },
    unmounted() {
      if (this.timer) clearInterval(this.timer);
    },
    methods: {
      formatDate,
      async refresh() {
        try {
          this.status = await requestJson("/api/status");
          this.statusError = this.status.last_error || "";
        } catch (error) {
          this.statusError = error.message;
        }
      },
      async startDetector() {
        try {
          this.status = await requestJson("/api/detector/start", { method: "POST" });
          this.streamUrl = `/api/live.mjpg?t=${Date.now()}`;
          await this.refresh();
        } catch (error) {
          this.statusError = error.message;
        }
      },
      async stopDetector() {
        try {
          this.status = await requestJson("/api/detector/stop", { method: "POST" });
          await this.refresh();
        } catch (error) {
          this.statusError = error.message;
        }
      },
    },
  }).mount("#live-app");
}

function settingsPage() {
  const { createApp } = requireVue();
  createApp({
    data() {
      return {
        cameras: [],
        audioDevices: [],
        audioSounds: [],
        hardwareDevices: [],
        audioDiagnostics: null,
        hardwareStatus: null,
        activeTab: "video",
        form: {
          enabled: false,
          camera_device: "/dev/video0",
          output_device: "auto",
          sound_on_detection: false,
          selected_sound: "beep",
          hardware_serial_device: "none",
          hardware_relay_pulse_ms: 500,
          hardware_servo_from_angle: 30,
          hardware_servo_to_angle: 150,
          hardware_servo_step_delay_ms: 10,
          detection_fps: 3.0,
          inference_max_width: 640,
          confidence_threshold: 0.35,
          cooldown_seconds: 60,
          retention_days: 7,
        },
        message: "",
        previewUrl: "",
        previewEmpty: "No preview loaded.",
        previewError: "",
        audioMessage: "",
        audioError: "",
        audioUploading: false,
        hardwareMessage: "",
        hardwareError: "",
        hardwareFlashLog: "",
        diagnosticsError: "",
      };
    },
    async mounted() {
      await this.load();
      await this.refreshPreview();
    },
    unmounted() {
      this.revokePreviewUrl();
    },
    methods: {
      cameraLabel(camera) {
        return `${camera.path}${camera.available ? "" : " (not available)"}`;
      },
      audioDeviceLabel(device) {
        return `${device.name}${device.available ? "" : " (not available)"}`;
      },
      audioSoundLabel(sound) {
        return sound.name;
      },
      hardwareDeviceLabel(device) {
        return `${device.name}${device.available ? "" : " (not available)"}`;
      },
      async load() {
        const [status, cameras, audioDevices, audioSounds, hardwareDevices, hardwareStatus] = await Promise.all([
          requestJson("/api/status"),
          requestJson("/api/cameras"),
          requestJson("/api/audio/devices"),
          requestJson("/api/audio/sounds"),
          requestJson("/api/hardware/devices"),
          requestJson("/api/hardware/status"),
        ]);
        this.cameras = cameras;
        this.audioDevices = audioDevices;
        this.audioSounds = audioSounds;
        this.hardwareDevices = hardwareDevices;
        this.hardwareStatus = hardwareStatus;
        this.form = { ...status.settings };
        await this.refreshAudioDiagnostics();
      },
      async saveSettings() {
        this.message = "Saving...";
        try {
          this.form = await requestJson("/api/settings", {
            method: "PATCH",
            body: JSON.stringify(this.form),
          });
          this.message = "Settings saved.";
          this.audioMessage = "";
          this.audioError = "";
          this.hardwareMessage = "";
          this.hardwareError = "";
          this.hardwareFlashLog = "";
          await this.load();
          await this.refreshPreview();
        } catch (error) {
          this.message = error.message;
        }
      },
      markPreviewStale() {
        this.revokePreviewUrl();
        this.previewEmpty = "Save settings to preview the selected camera.";
        this.previewError = "";
      },
      async refreshPreview() {
        this.previewError = "";
        this.previewEmpty = "Loading preview...";
        this.revokePreviewUrl();
        try {
          const response = await fetch(`/api/camera/preview?t=${Date.now()}`, { cache: "no-store" });
          if (!response.ok) {
            const body = await response.json().catch(() => ({ detail: response.statusText }));
            throw new Error(body.detail || response.statusText);
          }
          const blob = await response.blob();
          this.previewUrl = URL.createObjectURL(blob);
          this.previewEmpty = "";
        } catch (error) {
          this.previewError = error.message;
          this.previewEmpty = "Preview unavailable.";
        }
      },
      async playTestBeep() {
        this.audioMessage = "Playing test beep...";
        this.audioError = "";
        try {
          await requestJson("/api/audio/test-beep", { method: "POST" });
          this.audioMessage = "Test beep played.";
          await this.refreshAudioDiagnostics();
        } catch (error) {
          this.audioMessage = "";
          this.audioError = error.message;
          await this.refreshAudioDiagnostics();
        }
      },
      async playSelectedSound() {
        this.audioMessage = "Playing selected sound...";
        this.audioError = "";
        try {
          await requestJson("/api/audio/test-selected-sound", { method: "POST" });
          this.audioMessage = "Selected sound played.";
          await this.refreshAudioDiagnostics();
        } catch (error) {
          this.audioMessage = "";
          this.audioError = error.message;
          await this.refreshAudioDiagnostics();
        }
      },
      async uploadSound(event) {
        const file = event.target.files && event.target.files[0];
        if (!file) return;
        this.audioUploading = true;
        this.audioMessage = "Uploading sound...";
        this.audioError = "";
        try {
          const formData = new FormData();
          formData.append("file", file);
          const response = await fetch("/api/audio/sounds", {
            method: "POST",
            body: formData,
          });
          const body = await response.json().catch(() => null);
          if (!response.ok) {
            throw new Error(body?.detail || response.statusText);
          }
          this.form.selected_sound = body.id;
          this.audioSounds = await requestJson("/api/audio/sounds");
          this.audioMessage = "Sound uploaded. Save settings to use it for detections.";
        } catch (error) {
          this.audioMessage = "";
          this.audioError = error.message;
        } finally {
          this.audioUploading = false;
          event.target.value = "";
        }
      },
      async refreshHardwareStatus() {
        this.hardwareError = "";
        try {
          this.hardwareStatus = await requestJson("/api/hardware/status");
        } catch (error) {
          this.hardwareStatus = null;
          this.hardwareError = error.message;
        }
      },
      async testRelay() {
        this.hardwareMessage = "Testing relay...";
        this.hardwareError = "";
        try {
          this.hardwareStatus = await requestJson("/api/hardware/test-relay", { method: "POST" });
          this.hardwareMessage = "Relay test sent.";
        } catch (error) {
          this.hardwareMessage = "";
          this.hardwareError = error.message;
          await this.refreshHardwareStatus();
        }
      },
      async testLed() {
        this.hardwareMessage = "Blinking LED...";
        this.hardwareError = "";
        try {
          this.hardwareStatus = await requestJson("/api/hardware/test-led", { method: "POST" });
          this.hardwareMessage = "LED blink test sent.";
        } catch (error) {
          this.hardwareMessage = "";
          this.hardwareError = error.message;
          await this.refreshHardwareStatus();
        }
      },
      async testServo() {
        this.hardwareMessage = "Testing servo...";
        this.hardwareError = "";
        try {
          this.hardwareStatus = await requestJson("/api/hardware/test-servo", { method: "POST" });
          this.hardwareMessage = "Servo test sent.";
        } catch (error) {
          this.hardwareMessage = "";
          this.hardwareError = error.message;
          await this.refreshHardwareStatus();
        }
      },
      async flashArduino() {
        this.hardwareMessage = "Flashing Arduino firmware...";
        this.hardwareError = "";
        this.hardwareFlashLog = "Starting firmware flash...";
        try {
          const response = await fetch("/api/hardware/flash", {
            cache: "no-store",
            headers: { "Content-Type": "application/json" },
            method: "POST",
          });
          const body = await response.json().catch(() => null);
          if (!response.ok) {
            const detail = body?.detail;
            this.hardwareFlashLog = detail?.log || JSON.stringify(body, null, 2) || "";
            throw new Error(detail?.error || detail || response.statusText);
          }
          this.hardwareStatus = body;
          this.hardwareMessage = "Arduino firmware flashed.";
          this.hardwareFlashLog = body.last_log || body.last_response || "Firmware flashed.";
        } catch (error) {
          this.hardwareMessage = "";
          this.hardwareError = error.message;
          await this.refreshHardwareStatus();
        }
      },
      async refreshAudioDiagnostics() {
        this.diagnosticsError = "";
        try {
          this.audioDiagnostics = await requestJson("/api/audio/diagnostics");
        } catch (error) {
          this.audioDiagnostics = null;
          this.diagnosticsError = error.message;
        }
      },
      revokePreviewUrl() {
        if (this.previewUrl) {
          URL.revokeObjectURL(this.previewUrl);
          this.previewUrl = "";
        }
      },
    },
  }).mount("#settings-app");
}

window.Pigeonater = { dashboard, eventsPage, livePage, settingsPage };
