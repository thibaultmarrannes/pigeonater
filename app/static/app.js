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

function renderEvent(event) {
  return `
    <article class="event-item">
      <a href="${event.snapshot_url}" target="_blank" rel="noreferrer">
        <img src="${event.snapshot_url}" alt="Detection snapshot ${event.id}">
      </a>
      <div>
        <strong>${event.label} candidate</strong>
        <span>${formatDate(event.created_at)}</span>
        <span>${Math.round(event.confidence * 100)}% confidence</span>
        <small>Box: ${Math.round(event.box.x1)}, ${Math.round(event.box.y1)} to ${Math.round(event.box.x2)}, ${Math.round(event.box.y2)}</small>
      </div>
    </article>
  `;
}

async function refreshStatus() {
  const status = await requestJson("/api/status");
  document.querySelector("#status-running").textContent = status.detector_enabled && status.worker_running ? "Running" : "Paused";
  document.querySelector("#status-camera").textContent = status.camera_connected ? "Connected" : "Disconnected";
  document.querySelector("#status-frame").textContent = formatDate(status.last_frame_at);
  document.querySelector("#status-event").textContent = formatDate(status.last_event_at);
  document.querySelector("#status-error").textContent = status.last_error || "";
  const settings = document.querySelector("#settings-summary");
  settings.innerHTML = `
    <dt>Camera</dt><dd>${status.camera_device}</dd>
    <dt>Model</dt><dd>${status.model_name}</dd>
    <dt>Threshold</dt><dd>${status.settings.confidence_threshold}</dd>
    <dt>Cooldown</dt><dd>${status.settings.cooldown_seconds}s</dd>
    <dt>Retention</dt><dd>${status.settings.retention_days} days</dd>
  `;
  return status;
}

async function refreshEvents(selector, limit = 20) {
  const events = await requestJson(`/api/events?limit=${limit}`);
  const list = document.querySelector(selector);
  list.innerHTML = events.length ? events.map(renderEvent).join("") : `<p class="empty">No detections recorded yet.</p>`;
}

function dashboard() {
  document.querySelector("#start-detector").addEventListener("click", async () => {
    await requestJson("/api/detector/start", { method: "POST" });
    await refreshStatus();
  });
  document.querySelector("#stop-detector").addEventListener("click", async () => {
    await requestJson("/api/detector/stop", { method: "POST" });
    await refreshStatus();
  });
  const tick = async () => {
    try {
      await refreshStatus();
      await refreshEvents("#latest-events", 5);
    } catch (error) {
      document.querySelector("#status-error").textContent = error.message;
    }
  };
  tick();
  setInterval(tick, 5000);
}

function eventsPage() {
  refreshEvents("#events-page-list", 100);
  setInterval(() => refreshEvents("#events-page-list", 100), 10000);
}

async function settingsPage() {
  const form = document.querySelector("#settings-form");
  const message = document.querySelector("#settings-message");
  const [status, cameras] = await Promise.all([requestJson("/api/status"), requestJson("/api/cameras")]);
  form.camera_device.innerHTML = cameras.map((camera) => {
    const suffix = camera.available ? "" : " (not available)";
    return `<option value="${camera.path}">${camera.path}${suffix}</option>`;
  }).join("");
  form.enabled.checked = status.settings.enabled;
  form.camera_device.value = status.settings.camera_device;
  form.confidence_threshold.value = status.settings.confidence_threshold;
  form.cooldown_seconds.value = status.settings.cooldown_seconds;
  form.retention_days.value = status.settings.retention_days;
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    message.textContent = "Saving...";
    const payload = {
      enabled: form.enabled.checked,
      camera_device: form.camera_device.value,
      confidence_threshold: Number(form.confidence_threshold.value),
      cooldown_seconds: Number(form.cooldown_seconds.value),
      retention_days: Number(form.retention_days.value),
    };
    try {
      await requestJson("/api/settings", { method: "PATCH", body: JSON.stringify(payload) });
      message.textContent = "Settings saved.";
    } catch (error) {
      message.textContent = error.message;
    }
  });
}

window.Pigeonater = { dashboard, eventsPage, settingsPage };
