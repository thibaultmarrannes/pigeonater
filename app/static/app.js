async function requestJson(url, options = {}) {
  const response = await fetch(url, {
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
      this.timer = setInterval(this.refresh, 3000);
    },
    unmounted() {
      if (this.timer) clearInterval(this.timer);
    },
    methods: {
      formatDate,
      boxLabel,
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
        timer: null,
      };
    },
    async mounted() {
      await this.refresh();
      this.timer = setInterval(this.refresh, 5000);
    },
    unmounted() {
      if (this.timer) clearInterval(this.timer);
    },
    methods: {
      formatDate,
      boxLabel,
      async refresh() {
        try {
          this.events = await requestJson("/api/events?limit=100");
          this.error = "";
        } catch (error) {
          this.error = error.message;
        }
      },
    },
  }).mount("#events-app");
}

function settingsPage() {
  const { createApp } = requireVue();
  createApp({
    data() {
      return {
        cameras: [],
        form: {
          enabled: false,
          camera_device: "/dev/video0",
          confidence_threshold: 0.35,
          cooldown_seconds: 60,
          retention_days: 7,
        },
        message: "",
        previewUrl: "",
        previewEmpty: "No preview loaded.",
        previewError: "",
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
      async load() {
        const [status, cameras] = await Promise.all([requestJson("/api/status"), requestJson("/api/cameras")]);
        this.cameras = cameras;
        this.form = { ...status.settings };
      },
      async saveSettings() {
        this.message = "Saving...";
        try {
          this.form = await requestJson("/api/settings", {
            method: "PATCH",
            body: JSON.stringify(this.form),
          });
          this.message = "Settings saved.";
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
      revokePreviewUrl() {
        if (this.previewUrl) {
          URL.revokeObjectURL(this.previewUrl);
          this.previewUrl = "";
        }
      },
    },
  }).mount("#settings-app");
}

window.Pigeonater = { dashboard, eventsPage, settingsPage };
