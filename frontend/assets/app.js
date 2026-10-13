// ---------------------------------------------------------------------------
// AI Traffic Monitoring Dashboard - frontend logic
// Talks to the FastAPI backend at /api/*. No build step, no framework --
// plain fetch() calls and a bit of DOM wiring, kept in one file on purpose
// so the whole project stays simple to read for a student project.
// ---------------------------------------------------------------------------

const API = "/api";
const CLASS_KEYS = ["car", "bus", "truck", "motorcycle", "bicycle"];
const CLASS_COLORS = { car: "#22d3ee", bus: "#a78bfa", truck: "#f59e0b", motorcycle: "#ef4444", bicycle: "#22c55e" };
const DENSITY_COLOR = { LOW: "#22c55e", MEDIUM: "#f59e0b", HIGH: "#ef4444" };

let currentVideoId = null;
let pollTimer = null;
let charts = {};

// ---------------------------------------------------------------------------
// Navigation
// ---------------------------------------------------------------------------
document.querySelectorAll(".nav-item").forEach(btn => {
  btn.addEventListener("click", () => showPage(btn.dataset.page));
});
document.getElementById("dashUploadBtn").addEventListener("click", () => showPage("monitor"));
document.getElementById("backToHistory").addEventListener("click", () => showPage("history"));

function showPage(name) {
  document.querySelectorAll(".page").forEach(p => p.classList.remove("active"));
  document.querySelectorAll(".nav-item").forEach(b => b.classList.remove("active"));
  const page = document.getElementById(`page-${name}`);
  if (page) page.classList.add("active");
  const nav = document.querySelector(`.nav-item[data-page="${name}"]`);
  if (nav) nav.classList.add("active");
  if (name === "history") loadHistory();
  if (name === "analytics") loadAnalytics();
  if (name === "settings") loadSettings();
  resizeCharts();
}

// ---------------------------------------------------------------------------
// Backend health check
// ---------------------------------------------------------------------------
async function checkBackend() {
  const el = document.getElementById("backendStatus");
  try {
    const res = await fetch(`${API}/health`);
    if (!res.ok) throw new Error();
    el.classList.add("online"); el.classList.remove("offline");
    el.querySelector(".txt").textContent = "Backend connected";
  } catch {
    el.classList.add("offline"); el.classList.remove("online");
    el.querySelector(".txt").textContent = "Backend unavailable";
  }
}
checkBackend();
setInterval(checkBackend, 8000);

// ---------------------------------------------------------------------------
// Upload
// ---------------------------------------------------------------------------
const dropzone = document.getElementById("dropzone");
const fileInput = document.getElementById("fileInput");
document.getElementById("browseBtn").addEventListener("click", (e) => { e.stopPropagation(); fileInput.click(); });
dropzone.addEventListener("click", () => fileInput.click());
dropzone.addEventListener("dragover", (e) => { e.preventDefault(); dropzone.classList.add("drag"); });
dropzone.addEventListener("dragleave", () => dropzone.classList.remove("drag"));
dropzone.addEventListener("drop", (e) => {
  e.preventDefault(); dropzone.classList.remove("drag");
  if (e.dataTransfer.files.length) handleUpload(e.dataTransfer.files[0]);
});
fileInput.addEventListener("change", () => { if (fileInput.files.length) handleUpload(fileInput.files[0]); });

async function handleUpload(file) {
  setError("");
  document.getElementById("metaStatus").textContent = "Uploading...";
  document.getElementById("fileMeta").hidden = false;
  document.getElementById("metaName").textContent = file.name;

  const form = new FormData();
  form.append("file", file);
  try {
    const res = await fetch(`${API}/upload-video`, { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Upload failed");

    currentVideoId = data.video_id;
    document.getElementById("metaName").textContent = data.filename;
    document.getElementById("metaDuration").textContent = `${data.duration_seconds.toFixed(1)}s`;
    document.getElementById("metaRes").textContent = `${data.width}x${data.height} @ ${data.fps.toFixed(1)}fps`;
    document.getElementById("metaStatus").textContent = "Ready to analyze";
    document.getElementById("startBtn").disabled = false;
  } catch (err) {
    setError(err.message);
    document.getElementById("metaStatus").textContent = "Upload failed";
  }
}

function setError(msg) {
  const el = document.getElementById("errorMsg");
  el.textContent = msg;
  el.hidden = !msg;
}

// ---------------------------------------------------------------------------
// Controls
// ---------------------------------------------------------------------------
document.getElementById("startBtn").addEventListener("click", startProcessing);
document.getElementById("pauseBtn").addEventListener("click", () => sendControl("pause"));
document.getElementById("resumeBtn").addEventListener("click", () => sendControl("resume"));
document.getElementById("stopBtn").addEventListener("click", () => sendControl("stop"));
document.getElementById("resetBtn").addEventListener("click", () => sendControl("reset"));

async function startProcessing() {
  if (!currentVideoId) return;
  setError("");
  try {
    const res = await fetch(`${API}/start-processing`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ video_id: currentVideoId }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Could not start processing");
    document.getElementById("liveFeed").src = `${API}/stream`;
    document.getElementById("liveFeed").classList.add("show");
    document.getElementById("videoPlaceholder").style.display = "none";
    setControlsState("processing");
    startPolling();
  } catch (err) {
    setError(err.message);
  }
}

async function sendControl(action) {
  try {
    const res = await fetch(`${API}/control`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || `Could not ${action}`);
    if (action === "reset") {
      document.getElementById("liveFeed").classList.remove("show");
      document.getElementById("videoPlaceholder").style.display = "block";
      document.getElementById("startBtn").disabled = !currentVideoId;
      setControlsState("idle");
      resetLiveDisplay();
    }
  } catch (err) {
    setError(err.message);
  }
}

function setControlsState(state) {
  const start = document.getElementById("startBtn");
  const pause = document.getElementById("pauseBtn");
  const resume = document.getElementById("resumeBtn");
  const stop = document.getElementById("stopBtn");
  if (state === "processing") {
    start.disabled = true; pause.disabled = false; resume.disabled = true; stop.disabled = false;
  } else if (state === "paused") {
    start.disabled = true; pause.disabled = true; resume.disabled = false; stop.disabled = false;
  } else {
    pause.disabled = true; resume.disabled = true; stop.disabled = true;
  }
}

function resetLiveDisplay() {
  document.getElementById("liveDot").classList.remove("active");
  document.getElementById("liveLabel").textContent = "IDLE";
  document.getElementById("monDetection").textContent = "DETECTION: INACTIVE";
  document.getElementById("progressFill").style.width = "0%";
  ["total", ...CLASS_KEYS].forEach(k => setText(`[data-live="${k}"]`, "0"));
  ["total", ...CLASS_KEYS].forEach(k => setText(`[data-count="${k}"]`, "0"));
}

function setText(sel, val) { const el = document.querySelector(sel); if (el) el.textContent = val; }

// ---------------------------------------------------------------------------
// Polling loop (status + results + timeseries) while a session is active
// ---------------------------------------------------------------------------
function startPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(pollOnce, 1000);
  pollOnce();
}

async function pollOnce() {
  try {
    const [statusRes, resultsRes, tsRes] = await Promise.all([
      fetch(`${API}/status`), fetch(`${API}/results`), fetch(`${API}/timeseries`),
    ]);
    const status = await statusRes.json();
    const results = await resultsRes.json();
    const ts = await tsRes.json();
    applyStatus(status);
    try { applyResults(results); } catch (e) { console.error("applyResults failed:", e); }
    try { applyTimeseries(ts); } catch (e) { console.error("applyTimeseries failed:", e); }

    if (["completed", "stopped", "error"].includes(status.status)) {
      clearInterval(pollTimer);
      pollTimer = null;
      setControlsState("idle");
      document.getElementById("liveDot").classList.remove("active");
      document.getElementById("monDetection").textContent = "DETECTION: INACTIVE";
      if (status.status === "error") setError(status.error_message || "Processing failed.");
      document.getElementById("startBtn").disabled = true; // must upload a new video or reset
    } else if (status.status === "paused") {
      setControlsState("paused");
    } else if (status.status === "processing") {
      setControlsState("processing");
    }
  } catch {
    // backend hiccup mid-poll; checkBackend() will surface the offline state
  }
}

function applyStatus(status) {
  document.getElementById("progressFill").style.width = `${status.progress_percent || 0}%`;
  const dot = document.getElementById("liveDot");
  const label = document.getElementById("liveLabel");
  if (status.status === "processing") {
    dot.classList.add("active"); label.textContent = "LIVE";
    document.getElementById("monDetection").textContent = "DETECTION: ACTIVE";
  } else if (status.status === "paused") {
    dot.classList.remove("active"); label.textContent = "PAUSED";
    document.getElementById("monDetection").textContent = "DETECTION: PAUSED";
  } else {
    dot.classList.remove("active"); label.textContent = status.status.toUpperCase();
  }
  document.getElementById("monCam").textContent = `CAM: ${status.video_name || "-"}`;
  document.getElementById("monFps").textContent = `FPS: ${status.processing_fps.toFixed(1)}`;
}

function applyResults(results) {
  const counts = results.counts || {};
  ["total", ...CLASS_KEYS].forEach(k => {
    setText(`[data-count="${k}"]`, counts[k] ?? 0);
    setText(`[data-live="${k}"]`, counts[k] ?? 0);
  });
  document.getElementById("fpsTag").textContent = `FPS: ${(results.processing_fps || 0).toFixed(1)}`;

  const density = results.density || { level: "LOW", vehicles_in_window: 0, window_seconds: 30 };
  const ring = document.getElementById("densityRing");
  ring.style.borderColor = DENSITY_COLOR[density.level];
  ring.style.boxShadow = `0 0 30px ${DENSITY_COLOR[density.level]}40`;
  document.getElementById("densityLevel").textContent = density.level;
  document.getElementById("densityLevel").style.color = DENSITY_COLOR[density.level];
  document.getElementById("densityWindowTag").textContent = `last ${density.window_seconds}s`;
  document.getElementById("densitySub").textContent =
    `${density.vehicles_in_window} vehicle(s) crossed in the last window`;

  updateDistributionChart("distributionChart", counts);
  updateBarChart("liveBarChart", counts);
}

function applyTimeseries(points) {
  updateTimeChart("timeChart", points);
  updateTimeChart("liveTimeChart", points);
}

// ---------------------------------------------------------------------------
// Charts (Chart.js, bundled locally in assets/chart.umd.js)
// ---------------------------------------------------------------------------
const CHART_READY = typeof Chart !== "undefined";
if (CHART_READY) {
  Chart.defaults.color = "#8b96a8";
  Chart.defaults.font.family = "Inter, sans-serif";
} else {
  console.error("Chart.js did not load - check that frontend/assets/chart.umd.js exists.");
}

const cap = (c) => c[0].toUpperCase() + c.slice(1);
const GRID = "rgba(148,163,184,0.08)";

// Draws "No data yet" in the middle of a chart that has nothing to show.
const noDataPlugin = {
  id: "noData",
  afterDraw(chart) {
    const ds = chart.data.datasets[0];
    const isLine = chart.config.type === "line";
    const hasData = isLine ? ds.data.length > 0 : ds.data.some(v => v > 0);
    if (hasData) return;
    const { ctx, chartArea } = chart;
    if (!chartArea) return;
    ctx.save();
    ctx.fillStyle = "#8b96a8";
    ctx.textAlign = "center";
    ctx.font = "13px Inter, sans-serif";
    ctx.fillText("No data yet", (chartArea.left + chartArea.right) / 2, (chartArea.top + chartArea.bottom) / 2);
    ctx.restore();
  },
};

function canvasCtx(canvasId) {
  if (!CHART_READY) return null;
  const el = document.getElementById(canvasId);
  return el ? el.getContext("2d") : null;
}

function ensureDoughnut(canvasId) {
  if (charts[canvasId]) return charts[canvasId];
  const ctx = canvasCtx(canvasId);
  if (!ctx) return null;
  charts[canvasId] = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels: CLASS_KEYS.map(cap),
      datasets: [{ data: CLASS_KEYS.map(() => 0), backgroundColor: CLASS_KEYS.map(c => CLASS_COLORS[c]), borderWidth: 0 }],
    },
    options: {
      plugins: { legend: { position: "bottom", labels: { boxWidth: 10, padding: 14 } } },
      cutout: "68%",
    },
    plugins: [noDataPlugin],
  });
  return charts[canvasId];
}

function updateDistributionChart(canvasId, counts) {
  const chart = ensureDoughnut(canvasId);
  if (!chart) return;
  chart.data.datasets[0].data = CLASS_KEYS.map(c => counts[c] || 0);
  chart.update();
}

function ensureBarChart(canvasId) {
  if (charts[canvasId]) return charts[canvasId];
  const ctx = canvasCtx(canvasId);
  if (!ctx) return null;
  charts[canvasId] = new Chart(ctx, {
    type: "bar",
    data: {
      labels: CLASS_KEYS.map(cap),
      datasets: [{ data: CLASS_KEYS.map(() => 0), backgroundColor: CLASS_KEYS.map(c => CLASS_COLORS[c]), borderRadius: 6, maxBarThickness: 34 }],
    },
    options: {
      indexAxis: "y",
      plugins: { legend: { display: false } },
      scales: {
        x: { beginAtZero: true, ticks: { precision: 0 }, grid: { color: GRID } },
        y: { grid: { display: false } },
      },
    },
    plugins: [noDataPlugin],
  });
  return charts[canvasId];
}

function updateBarChart(canvasId, counts) {
  const chart = ensureBarChart(canvasId);
  if (!chart) return;
  chart.data.datasets[0].data = CLASS_KEYS.map(c => counts[c] || 0);
  chart.update();
}

function ensureLineChart(canvasId) {
  if (charts[canvasId]) return charts[canvasId];
  const ctx = canvasCtx(canvasId);
  if (!ctx) return null;
  charts[canvasId] = new Chart(ctx, {
    type: "line",
    data: { labels: [], datasets: [{ label: "Total vehicles", data: [], borderColor: "#22d3ee", backgroundColor: "rgba(34,211,238,0.12)", fill: true, tension: 0.35, pointRadius: 2 }] },
    options: {
      scales: {
        x: { grid: { color: GRID } },
        y: { grid: { color: GRID }, beginAtZero: true, ticks: { precision: 0 } },
      },
      plugins: { legend: { display: false } },
    },
    plugins: [noDataPlugin],
  });
  return charts[canvasId];
}

function updateTimeChart(canvasId, points) {
  const chart = ensureLineChart(canvasId);
  if (!chart) return;
  chart.data.labels = points.map(p => p.timestamp);
  chart.data.datasets[0].data = points.map(p => p.total);
  chart.update();
}

// Charts created/updated while their page was hidden have zero size;
// call this after a page becomes visible.
function resizeCharts() {
  setTimeout(() => Object.values(charts).forEach(c => c && c.resize()), 60);
}

// ---------------------------------------------------------------------------
// History
// ---------------------------------------------------------------------------
async function loadHistory() {
  const res = await fetch(`${API}/history`);
  const rows = await res.json();
  const body = document.getElementById("historyBody");
  const empty = document.getElementById("historyEmpty");
  body.innerHTML = "";
  empty.hidden = rows.length > 0;
  rows.forEach(r => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${new Date(r.created_at).toLocaleString()}</td>
      <td>${r.video_name}</td>
      <td>${r.total}</td><td>${r.car}</td><td>${r.bus}</td><td>${r.truck}</td>
      <td>${r.motorcycle}</td><td>${r.bicycle}</td>
      <td><span class="density-pill ${r.density}">${r.density}</span></td>
      <td>${r.fps.toFixed(1)}</td>
      <td><button class="link-btn" data-id="${r.id}">View</button></td>
    `;
    body.appendChild(tr);
  });
  body.querySelectorAll(".link-btn").forEach(btn => {
    btn.addEventListener("click", () => openHistoryDetail(btn.dataset.id));
  });
}

let currentDetailId = null;

async function openHistoryDetail(id) {
  const res = await fetch(`${API}/history/${id}`);
  const data = await res.json();
  currentDetailId = id;
  const s = data.session;
  document.getElementById("detailTitle").textContent = `Session #${s.id} - ${s.video_name}`;
  document.getElementById("detailSummary").innerHTML = `
    <li><span>Total</span><strong>${s.total}</strong></li>
    <li><span>Car</span><strong>${s.car}</strong></li>
    <li><span>Bus</span><strong>${s.bus}</strong></li>
    <li><span>Truck</span><strong>${s.truck}</strong></li>
    <li><span>Motorcycle</span><strong>${s.motorcycle}</strong></li>
    <li><span>Bicycle</span><strong>${s.bicycle}</strong></li>
    <li><span>Density</span><strong>${s.density}</strong></li>
    <li><span>FPS</span><strong>${s.fps.toFixed(1)}</strong></li>
    <li><span>Duration</span><strong>${s.duration_seconds.toFixed(1)}s</strong></li>
    <li><span>Suspected duplicate crossings</span><strong>${s.suspected_duplicates}</strong></li>
  `;
  const video = document.getElementById("detailVideo");
  video.src = s.output_video ? `${API}/outputs/${s.output_video}` : "";
  document.getElementById("detailMissed").value = s.missed_detections ?? "";
  document.getElementById("detailDup").value = s.duplicate_detections ?? "";
  document.getElementById("detailNotes").value = s.notes ?? "";

  const chart = ensureLineChart("detailChart");
  chart.data.labels = data.timeseries.map(p => p.timestamp);
  chart.data.datasets[0].data = data.timeseries.map(p => p.total);
  chart.update();

  document.querySelectorAll(".page").forEach(p => p.classList.remove("active"));
  document.getElementById("page-history-detail").classList.add("active");
  resizeCharts();
}

document.getElementById("saveDetailBtn").addEventListener("click", async () => {
  if (!currentDetailId) return;
  const body = {
    missed_detections: numOrNull(document.getElementById("detailMissed").value),
    duplicate_detections: numOrNull(document.getElementById("detailDup").value),
    notes: document.getElementById("detailNotes").value || null,
  };
  await fetch(`${API}/history/${currentDetailId}`, {
    method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
});

function numOrNull(v) { return v === "" ? null : Number(v); }

// ---------------------------------------------------------------------------
// Analytics
// ---------------------------------------------------------------------------
async function loadAnalytics() {
  const res = await fetch(`${API}/history`);
  const rows = await res.json();
  if (!rows.length) return;
  const latest = rows[0];

  document.getElementById("anTotal").textContent = latest.total;
  document.getElementById("anFps").textContent = latest.fps.toFixed(1);
  const perMinute = latest.duration_seconds > 0 ? (latest.total / (latest.duration_seconds / 60)) : 0;
  document.getElementById("anRate").textContent = perMinute.toFixed(1);

  const detailRes = await fetch(`${API}/history/${latest.id}`);
  const detail = await detailRes.json();
  let peak = "-";
  if (detail.timeseries.length) {
    let best = detail.timeseries[0];
    let prevTotal = 0;
    let bestDelta = -1;
    detail.timeseries.forEach(p => {
      const delta = p.total - prevTotal;
      if (delta > bestDelta) { bestDelta = delta; best = p; }
      prevTotal = p.total;
    });
    peak = best.timestamp;
  }
  document.getElementById("anPeak").textContent = peak;

  const distChart = ensureDoughnut("anDistributionChart");
  distChart.data.datasets[0].data = CLASS_KEYS.map(c => latest[c] || 0);
  distChart.update();

  const timeChart = ensureLineChart("anTimeChart");
  timeChart.data.labels = detail.timeseries.map(p => p.timestamp);
  timeChart.data.datasets[0].data = detail.timeseries.map(p => p.total);
  timeChart.update();

  const densityCanvas = document.getElementById("anDensityChart");
  if (!charts["anDensityChart"]) {
    charts["anDensityChart"] = new Chart(densityCanvas.getContext("2d"), {
      type: "bar",
      data: { labels: [], datasets: [{ label: "Total vehicles", data: [], backgroundColor: [] }] },
      options: { plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, ticks: { precision: 0 } } } },
    });
  }
  const recent = rows.slice(0, 8).reverse();
  const dChart = charts["anDensityChart"];
  dChart.data.labels = recent.map(r => `#${r.id}`);
  dChart.data.datasets[0].data = recent.map(r => r.total);
  dChart.data.datasets[0].backgroundColor = recent.map(r => DENSITY_COLOR[r.density]);
  dChart.update();
}

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------
async function loadSettings() {
  const [settingsRes, modelsRes] = await Promise.all([fetch(`${API}/settings`), fetch(`${API}/models`)]);
  const settings = await settingsRes.json();
  const models = await modelsRes.json();

  document.getElementById("lineSlider").value = settings.counting_line_position;
  document.getElementById("lineValLabel").textContent = Number(settings.counting_line_position).toFixed(2);
  document.getElementById("confInput").value = settings.confidence_threshold;
  document.getElementById("windowInput").value = settings.density_window_seconds;
  document.getElementById("lowMaxInput").value = settings.density_low_max;
  document.getElementById("medMaxInput").value = settings.density_medium_max;

  const modelSelect = document.getElementById("modelSelect");
  modelSelect.innerHTML = "";
  const modelList = models.models.length ? models.models : [settings.model_name];
  modelList.forEach(m => {
    const opt = document.createElement("option");
    opt.value = m; opt.textContent = m;
    if (m === settings.model_name) opt.selected = true;
    modelSelect.appendChild(opt);
  });

  const chipRow = document.getElementById("classChips");
  chipRow.innerHTML = "";
  models.vehicle_classes.forEach(c => {
    const chip = document.createElement("div");
    chip.className = "chip" + (settings.enabled_classes.includes(c) ? " on" : "");
    chip.textContent = c[0].toUpperCase() + c.slice(1);
    chip.dataset.value = c;
    chip.addEventListener("click", () => chip.classList.toggle("on"));
    chipRow.appendChild(chip);
  });
}

document.getElementById("lineSlider").addEventListener("input", (e) => {
  document.getElementById("lineValLabel").textContent = Number(e.target.value).toFixed(2);
});

document.getElementById("saveSettingsBtn").addEventListener("click", async () => {
  const enabled_classes = Array.from(document.querySelectorAll("#classChips .chip.on")).map(c => c.dataset.value);
  const body = {
    counting_line_position: Number(document.getElementById("lineSlider").value),
    confidence_threshold: Number(document.getElementById("confInput").value),
    density_window_seconds: Number(document.getElementById("windowInput").value),
    density_low_max: Number(document.getElementById("lowMaxInput").value),
    density_medium_max: Number(document.getElementById("medMaxInput").value),
    model_name: document.getElementById("modelSelect").value,
    enabled_classes,
  };
  await fetch(`${API}/settings`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const confirm = document.getElementById("saveConfirm");
  confirm.hidden = false;
  setTimeout(() => (confirm.hidden = true), 2000);
});

// ---------------------------------------------------------------------------
// Init: pick up an already-running session on page load/refresh
// ---------------------------------------------------------------------------
(async function init() {
  try {
    const res = await fetch(`${API}/status`);
    const status = await res.json();
    if (["processing", "paused"].includes(status.status)) {
      document.getElementById("liveFeed").src = `${API}/stream`;
      document.getElementById("liveFeed").classList.add("show");
      document.getElementById("videoPlaceholder").style.display = "none";
      setControlsState(status.status === "paused" ? "paused" : "processing");
      startPolling();
    } else {
      applyResults(await (await fetch(`${API}/results`)).json());
    }
  } catch {
    // backend not up yet; the health check banner covers this
  }
})();
