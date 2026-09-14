"use strict";

// Only page-local signals are collected. Neither editor text nor key values are sent.
const state = {
  id: crypto.randomUUID(),
  status: "idle",
  startedAt: null,
  heartbeatTimer: null,
  elapsedTimer: null,
  heartbeatInFlight: false,
  heartbeatSequence: 0,
  eventCount: 0,
  pendingEvents: new Set(),
  pendingHeartbeatRequest: null,
};

const $ = (id) => document.getElementById(id);
const experimentTemplates = {
  a: { title: "A · Normal browser tab switch", steps: ["Start the session.", "Open another browser tab and wait a few seconds.", "Return to this tab.", "Add a marker labeled “Browser tab switch”."], marker: "Browser tab switch" },
  b: { title: "B · Alt-Tab to another application", steps: ["Start the session.", "Use Alt-Tab to switch to another application.", "Return to this browser.", "Add a marker labeled “Alt-Tab to application”."], marker: "Alt-Tab to application" },
  c: { title: "C · Minimize browser", steps: ["Start the session.", "Minimize the browser window and wait a few seconds.", "Restore it.", "Add a marker labeled “Browser minimized”."], marker: "Browser minimized" },
  d: { title: "D · Enter and exit fullscreen", steps: ["Start the session.", "Use TOGGLE PAGE FULLSCREEN above the problem to enter page fullscreen.", "Use the same button or Escape to exit. Browser F11 mode may behave differently.", "Add a marker labeled “Fullscreen enter and exit”."], marker: "Fullscreen enter and exit" },
  e: { title: "E · Copy and paste", steps: ["Start the session.", "Copy a short piece of practice text in this local page.", "Paste it into the editor.", "Add a marker labeled “Copy and paste”."], marker: "Copy and paste" },
  f: { title: "F · Launch benign overlay", steps: ["Start the session.", "Launch overlay/benign_overlay.py on the same desktop.", "Show, move, or focus its visible window. Return to the browser.", "Add a marker labeled “Benign overlay opened”."], marker: "Benign overlay opened" },
  g: { title: "G · VMware host test", steps: ["Inside the guest VM, start this simulation and keep the browser open.", "From the host OS, minimize the VMware application. Do not automate this action.", "Wait 10 seconds.", "Restore VMware.", "Inside the guest browser, add a marker labeled “VMware minimized”."], marker: "VMware minimized" },
  h: { title: "H · VMware guest Alt-Tab", steps: ["Inside the guest VM, start the session.", "Use Alt-Tab inside the guest to switch to a guest application.", "Return to the guest browser.", "Add a marker labeled “Guest Alt-Tab”."], marker: "Guest Alt-Tab" },
  i: { title: "I · Switch host application", steps: ["Inside the guest VM, start the session and leave the guest browser open.", "On the host OS, switch to another host application without automating the guest.", "Return to VMware.", "Add a marker labeled “Host application switch”."], marker: "Host application switch" },
};

const starterCode = {
  "Python 3": "# Write your solution here.\n# This local lab does not execute or grade code.\n",
  JavaScript: "// Write your solution here.\n// This local lab does not execute or grade code.\n",
  "C++": "// Write your solution here.\n// This local lab does not execute or grade code.\n",
  Java: "// Write your solution here.\n// This local lab does not execute or grade code.\n",
};
const editorDrafts = {};
let currentLanguage = "Python 3";
let mockSubmissionCount = 0;

function browserName() {
  const ua = navigator.userAgent;
  if (ua.includes("Edg/")) return "Microsoft Edge";
  if (ua.includes("Firefox/")) return "Firefox";
  if (ua.includes("Chrome/")) return "Chrome";
  if (ua.includes("Safari/")) return "Safari";
  return "Other browser";
}

function currentPlatform() {
  return navigator.userAgentData?.platform || navigator.platform || "Unknown";
}

function updateEnvironment() {
  $("session-id").textContent = state.id;
  $("session-start").textContent = state.startedAt ? formatDateTime(state.startedAt) : "Not started";
  $("browser-name").textContent = browserName();
  $("platform-name").textContent = currentPlatform();
  $("viewport-size").textContent = `${window.innerWidth} × ${window.innerHeight}`;
  $("screen-size").textContent = `${screen.width} × ${screen.height}`;
}

function updateElapsed() {
  const seconds = state.startedAt ? Math.max(0, Math.floor((Date.now() - new Date(state.startedAt).getTime()) / 1000)) : 0;
  $("elapsed-time").textContent = `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

function formatDateTime(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value || "—") : date.toLocaleString();
}

function formatClock(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleTimeString([], { hour12: false });
}

function setMessage(message, error = false) {
  const target = $("app-message");
  target.textContent = message;
  target.classList.toggle("error", error);
}

function setStatus(status) {
  state.status = status;
  const badge = $("session-status");
  badge.textContent = { idle: "Ready", starting: "Starting…", active: "Recording", ending: "Ending…", "end-error": "Save error", ended: "Ended" }[status];
  badge.className = `status-badge ${status === "active" ? "status-active" : status === "ended" ? "status-ended" : "status-idle"}`;
  $("start-test").disabled = status !== "idle";
  $("end-test").disabled = !["active", "end-error"].includes(status);
  $("add-marker").disabled = status !== "active";
  $("view-report").disabled = status !== "ended";
}

async function api(path, body) {
  const response = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try { detail = (await response.json()).detail || detail; } catch { /* A non-JSON error is still shown. */ }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return response.json();
}

function snapshot() {
  return {
    visibility_state: document.visibilityState,
    document_has_focus: document.hasFocus(),
    fullscreen: Boolean(document.fullscreenElement),
    screen_width: screen.width,
    screen_height: screen.height,
    viewport_width: window.innerWidth,
    viewport_height: window.innerHeight,
    user_agent: navigator.userAgent,
  };
}

function eventCategory(type) {
  if (type === "focus" || type === "blur") return "focus";
  if (type === "visibilitychange") return "visibility";
  if (type === "fullscreenchange") return "fullscreen";
  if (["copy", "paste", "cut"].includes(type)) return "clipboard";
  if (type === "marker") return "marker";
  if (type === "heartbeat") return "heartbeat";
  return "interaction";
}

function eventDescription(type, payload = {}) {
  const metadata = payload.metadata || {};
  if (type === "visibilitychange") return `document ${payload.visibility_state || document.visibilityState}`;
  if (type === "focus") return "window focused";
  if (type === "blur") return "window lost focus";
  if (type === "fullscreenchange") return payload.fullscreen ? "entered page fullscreen" : "exited page fullscreen";
  if (["copy", "paste", "cut"].includes(type)) return `${metadata.character_count ?? 0} characters`;
  if (type === "keydown") return `${metadata.keyCategory || "other"} key category`;
  if (type === "marker") return payload.label || "test marker";
  if (type === "heartbeat") return `${Math.round(payload.delta_ms ?? 0)} ms interval${payload.gap_level ? ` · ${payload.gap_level}` : ""}`;
  if (type === "contextmenu") return "context menu requested";
  if (type === "pointerleave") return "pointer left page";
  if (type === "pointerenter") return "pointer entered page";
  if (type === "beforeunload") return "page about to unload";
  if (type === "pagehide") return "page hidden or unloaded";
  if (type === "pageshow") return "page shown";
  if (type === "start") return "session started";
  if (type === "end") return "session ended";
  return type.replaceAll("_", " ");
}

function appendLive(type, payload = {}) {
  const list = $("event-list");
  list.querySelector(".empty-state")?.remove();
  const item = document.createElement("li");
  item.className = `event-${eventCategory(type)}`;
  if (type === "heartbeat") {
    if (payload.gap_level === "WARNING") item.classList.add("event-warning");
    if (payload.gap_level === "LARGE GAP") item.classList.add("event-large");
  }
  const time = document.createElement("time");
  time.dateTime = payload.timestamp_client || payload.client_timestamp || new Date().toISOString();
  time.textContent = formatClock(time.dateTime);
  const label = document.createElement("span");
  label.className = "event-label";
  label.textContent = type === "visibilitychange" ? "VISIBILITY" : type.toUpperCase();
  const description = document.createElement("span");
  description.className = "event-description";
  description.textContent = eventDescription(type, payload);
  item.append(time, label, description);
  list.prepend(item);
  while (list.children.length > 150) list.lastElementChild.remove();
  state.eventCount += 1;
  $("event-total").textContent = `${state.eventCount} events`;
}

function sendUnloadEvent(payload) {
  const data = new Blob([JSON.stringify(payload)], { type: "application/json" });
  if (navigator.sendBeacon?.("/api/events", data)) return;
  fetch("/api/events", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload), keepalive: true }).catch(() => {});
}

function recordEvent(eventType, metadata = {}, unload = false) {
  if (state.status !== "active") return;
  const payload = {
    event_id: crypto.randomUUID(),
    session_id: state.id,
    event_type: eventType,
    timestamp_client: new Date().toISOString(),
    ...snapshot(),
    metadata,
  };
  appendLive(eventType, payload);
  if (unload) { sendUnloadEvent(payload); return; }
  const request = api("/api/events", payload).catch((error) => setMessage(`Event could not be saved: ${error.message}`, true));
  state.pendingEvents.add(request);
  request.finally(() => state.pendingEvents.delete(request));
}

function keyCategory(key) {
  if (["Shift", "Control", "Alt", "Meta", "AltGraph", "CapsLock"].includes(key)) return "modifier";
  if (["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Home", "End", "PageUp", "PageDown", "Tab"].includes(key)) return "navigation";
  if (["Backspace", "Delete", "Enter", "Insert", "Escape"].includes(key)) return "editing";
  if (/^F(?:[1-9]|1[0-9]|2[0-4])$/.test(key)) return "function";
  if (key.length === 1) return "character";
  return "other";
}

function selectedCharacterCount() {
  const editor = $("code-editor");
  if (document.activeElement === editor) return Math.max(0, editor.selectionEnd - editor.selectionStart);
  return window.getSelection()?.toString().length ?? 0;
}

function clipboardCharacterCount(event) {
  if (event.type === "paste") {
    // Read the transient paste event only to count characters; never retain or transmit its text.
    return event.clipboardData?.getData("text/plain")?.length ?? 0;
  }
  return selectedCharacterCount();
}

function installEventListeners() {
  document.addEventListener("visibilitychange", () => recordEvent("visibilitychange"));
  window.addEventListener("blur", () => recordEvent("blur"));
  window.addEventListener("focus", () => recordEvent("focus"));
  document.addEventListener("fullscreenchange", () => recordEvent("fullscreenchange"));
  window.addEventListener("beforeunload", () => recordEvent("beforeunload", {}, true));
  window.addEventListener("pagehide", () => recordEvent("pagehide", {}, true));
  window.addEventListener("pageshow", () => recordEvent("pageshow"));
  for (const type of ["copy", "paste", "cut"]) {
    document.addEventListener(type, (event) => recordEvent(type, { character_count: clipboardCharacterCount(event) }));
  }
  document.addEventListener("contextmenu", () => recordEvent("contextmenu"));
  document.addEventListener("keydown", (event) => recordEvent("keydown", {
    keyCategory: keyCategory(event.key),
    ctrl: event.ctrlKey,
    alt: event.altKey,
    shift: event.shiftKey,
    meta: event.metaKey,
    repeat: event.repeat,
  }));
  document.addEventListener("pointerleave", () => recordEvent("pointerleave"));
  document.addEventListener("pointerenter", () => recordEvent("pointerenter"));
  window.addEventListener("resize", updateEnvironment);
}

async function sendHeartbeat() {
  if (state.status !== "active" || state.heartbeatInFlight) return;
  state.heartbeatInFlight = true;
  try {
    const request = api("/api/heartbeat", {
      session_id: state.id,
      sequence: ++state.heartbeatSequence,
      client_timestamp: new Date().toISOString(),
      visibility_state: document.visibilityState,
      has_focus: document.hasFocus(),
      fullscreen: Boolean(document.fullscreenElement),
    });
    state.pendingHeartbeatRequest = request;
    const result = await request;
    if (state.status === "active" && ["WARNING", "LARGE GAP"].includes(result.gap_level)) {
      appendLive("heartbeat", result);
    }
  } catch (error) {
    if (state.status === "active") setMessage(`Heartbeat could not be saved: ${error.message}`, true);
  } finally {
    state.pendingHeartbeatRequest = null;
    state.heartbeatInFlight = false;
  }
}

async function startTest() {
  if (state.status !== "idle") return;
  setStatus("starting");
  setMessage("Starting local session…");
  try {
    const result = await api("/api/session/start", {
      id: state.id,
      started_at: new Date().toISOString(),
      user_agent: navigator.userAgent,
      platform: currentPlatform(),
      screen_width: screen.width,
      screen_height: screen.height,
    });
    state.id = result.id;
    state.startedAt = result.started_at;
    updateEnvironment();
    updateElapsed();
    setStatus("active");
    setMessage("Recording page events and sending a heartbeat every two seconds.");
    await sendHeartbeat();
    if (state.status === "active") {
      state.heartbeatTimer = window.setInterval(sendHeartbeat, 2000);
      state.elapsedTimer = window.setInterval(updateElapsed, 1000);
    }
  } catch (error) {
    setStatus("idle");
    setMessage(`Could not start session: ${error.message}`, true);
  }
}

async function endTest() {
  if (!["active", "end-error"].includes(state.status)) return;
  setStatus("ending");
  window.clearInterval(state.heartbeatTimer);
  window.clearInterval(state.elapsedTimer);
  updateElapsed();
  setMessage("Saving and analyzing the session…");
  await Promise.allSettled([...state.pendingEvents, state.pendingHeartbeatRequest].filter(Boolean));
  try {
    await api("/api/session/end", { session_id: state.id });
  } catch (error) {
    setStatus("end-error");
    setMessage(`Session end could not be saved: ${error.message}. Click END TEST to retry.`, true);
    return;
  }
  setStatus("ended");
  try {
    const analysis = await api(`/api/session/${encodeURIComponent(state.id)}/analysis`);
    renderAnalysis(analysis);
    $("analysis-section").hidden = false;
    await fetch(`/api/session/${encodeURIComponent(state.id)}/report`, { cache: "no-store" }).then((response) => {
      if (!response.ok) throw new Error(`Report generation returned ${response.status}`);
    });
    setMessage("Session ended. The report is saved locally and can be opened above.");
    $("analysis-section").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    // Capture remains frozen after END. The report link still permits a retry.
    setMessage(`Session capture stopped, but a result could not be loaded: ${error.message}`, true);
  }
}

function showMarkerDialog() {
  if (state.status !== "active") return;
  $("marker-label").value = experimentTemplates[$("experiment-select").value].marker;
  $("marker-dialog").showModal();
  $("marker-label").focus();
}

async function saveMarker(event) {
  event.preventDefault();
  if (state.status !== "active") return;
  const label = $("marker-label").value.trim().replace(/[\x00-\x1f\x7f]/g, " ").slice(0, 100);
  if (!label) { $("marker-label").focus(); return; }
  const timestampClient = new Date().toISOString();
  try {
    await api("/api/marker", { session_id: state.id, label, timestamp_client: timestampClient });
    appendLive("marker", { label, timestamp_client: timestampClient });
    $("marker-dialog").close();
    setMessage(`Marker saved: ${label}`);
  } catch (error) {
    setMessage(`Marker could not be saved: ${error.message}`, true);
  }
}

function renderExperiment() {
  const template = experimentTemplates[$("experiment-select").value];
  const heading = document.createElement("h3");
  heading.textContent = template.title;
  const steps = document.createElement("ol");
  for (const step of template.steps) {
    const item = document.createElement("li");
    item.textContent = step;
    steps.append(item);
  }
  $("experiment-instructions").replaceChildren(heading, steps);
}

function valueFrom(object, ...keys) {
  for (const key of keys) if (object && object[key] !== undefined && object[key] !== null) return object[key];
  return null;
}

function renderSummary(analysis) {
  const summary = analysis.summary || analysis;
  const longestGap = valueFrom(summary, "longest_heartbeat_gap_ms", "longest_gap_ms");
  const averageInterval = valueFrom(summary, "average_heartbeat_interval_ms", "average_heartbeat_ms");
  const cards = [
    ["Duration", `${Number(valueFrom(summary, "duration_seconds", "total_duration_seconds") ?? Number(valueFrom(summary, "total_duration_ms") || 0) / 1000).toFixed(1)} s`],
    ["Focus losses", valueFrom(summary, "focus_loss_count") ?? 0],
    ["Visibility hidden", valueFrom(summary, "visibility_hidden_count") ?? 0],
    ["Fullscreen exits", valueFrom(summary, "fullscreen_exit_count") ?? 0],
    ["Paste events", valueFrom(summary, "paste_count") ?? 0],
    ["Longest heartbeat gap", longestGap === null ? "Not measured" : `${Math.round(Number(longestGap))} ms`],
    ["Average heartbeat", averageInterval === null ? "Not measured" : `${Math.round(Number(averageInterval))} ms`],
    ["Markers", valueFrom(summary, "marker_count") ?? 0],
  ];
  const container = $("summary-cards");
  container.replaceChildren();
  for (const [label, value] of cards) {
    const card = document.createElement("div");
    card.className = "summary-card";
    const name = document.createElement("span");
    name.textContent = label;
    const number = document.createElement("strong");
    number.textContent = String(value);
    card.append(name, number);
    container.append(card);
  }
}

function timelineTime(item) {
  return valueFrom(item, "timestamp_server", "server_timestamp", "timestamp", "client_timestamp", "timestamp_client") || state.startedAt;
}

function timelineType(item) {
  const kind = String(item.kind || "").toLowerCase();
  if (kind === "marker") return "marker";
  if (kind === "heartbeat") return "heartbeat";
  return item.event_type || kind || "event";
}

function renderTimeline(items) {
  const list = $("timeline-list");
  const visual = $("timeline-visual");
  list.replaceChildren(); visual.replaceChildren();
  if (!items.length) { list.textContent = "No measured timeline entries."; return; }
  const sorted = [...items].sort((a, b) => new Date(timelineTime(a)) - new Date(timelineTime(b)));
  const start = new Date(state.startedAt || timelineTime(sorted[0])).getTime();
  const end = Math.max(start + 1000, ...sorted.map((item) => new Date(timelineTime(item)).getTime()));
  const track = document.createElement("div");
  track.className = "timeline-track";
  for (const item of sorted) {
    const type = timelineType(item);
    const at = new Date(timelineTime(item)).getTime();
    const elapsed = Math.max(0, (at - start) / 1000);
    const entry = document.createElement("li");
    const time = document.createElement("time");
    time.textContent = `${elapsed.toFixed(1)} s`;
    const description = document.createElement("span");
    description.textContent = type === "marker" ? `Marker: ${item.label || item.metadata?.label || "test marker"}` : eventDescription(type, item);
    entry.append(time, description);
    list.append(entry);
    const dot = document.createElement("span");
    dot.className = `timeline-dot event-${eventCategory(type)}`;
    dot.style.left = `${Math.min(99, Math.max(1, 100 * (at - start) / (end - start)))}%`;
    dot.title = `${elapsed.toFixed(1)} s · ${description.textContent}`;
    track.append(dot);
  }
  const legend = document.createElement("div");
  legend.className = "timeline-legend";
  for (const [name, color] of [["Focus", "#208470"], ["Visibility", "#d48224"], ["Fullscreen", "#795cbd"], ["Clipboard", "#bf5688"], ["Heartbeat", "#6f97ba"], ["Marker", "#d06c24"]]) {
    const chip = document.createElement("span");
    chip.style.setProperty("--dot", color);
    chip.textContent = name;
    legend.append(chip);
  }
  visual.append(track, legend);
}

function svgNode(tag, attributes = {}, text = null) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, String(value));
  if (text !== null) node.textContent = String(text);
  return node;
}

function renderHeartbeatGraph(points) {
  const wrap = $("heartbeat-graph");
  wrap.replaceChildren();
  const intervals = points.filter((point) => point.delta_ms !== null && point.delta_ms !== undefined && Number.isFinite(Number(point.delta_ms)));
  if (!intervals.length) {
    const empty = document.createElement("p");
    empty.className = "graph-empty";
    empty.textContent = "No heartbeat intervals were measured.";
    wrap.append(empty);
    return;
  }
  const width = Math.min(1600, Math.max(650, 75 * intervals.length + 85));
  const height = 240, left = 55, right = 25, top = 20, bottom = 38;
  const plotW = width - left - right, plotH = height - top - bottom;
  const maxY = Math.max(9000, Math.ceil(Math.max(...intervals.map((p) => Number(p.delta_ms))) / 2000) * 2000);
  const timestamps = intervals.map((point) => new Date(timelineTime(point)).getTime());
  const firstTime = Math.min(...timestamps), lastTime = Math.max(...timestamps);
  const x = (i) => left + (firstTime === lastTime ? plotW / 2 : plotW * (timestamps[i] - firstTime) / (lastTime - firstTime));
  const y = (ms) => top + plotH * (1 - ms / maxY);
  const svg = svgNode("svg", { width, height, viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": "Heartbeat interval over time; warning threshold 4000 milliseconds and large gap threshold 8000 milliseconds" });
  svg.append(svgNode("text", { x: left, y: 12, fill: "#53677b", "font-size": 11 }, "Interval (ms)"));
  for (const threshold of [0, 4000, 8000]) {
    svg.append(svgNode("line", { x1: left, x2: width - right, y1: y(threshold), y2: y(threshold), stroke: threshold ? "#d9a87a" : "#8da2b7", "stroke-dasharray": threshold ? "5 4" : "none" }));
    svg.append(svgNode("text", { x: 4, y: y(threshold) + 4, fill: "#53677b", "font-size": 11 }, String(threshold)));
  }
  const path = intervals.map((point, i) => `${i ? "L" : "M"}${x(i)},${y(Number(point.delta_ms))}`).join(" ");
  svg.append(svgNode("path", { d: path, fill: "none", stroke: "#2862a0", "stroke-width": 2 }));
  for (let i = 0; i < intervals.length; i++) {
    const ms = Number(intervals[i].delta_ms);
    const color = ms > 8000 ? "#bd3942" : ms >= 4000 ? "#ce862c" : "#2862a0";
    const dot = svgNode("circle", { cx: x(i), cy: y(ms), r: 4, fill: color });
    dot.append(svgNode("title", {}, `Heartbeat ${intervals[i].sequence ?? i + 1}: ${Math.round(ms)} ms at ${formatClock(timelineTime(intervals[i]))}`));
    svg.append(dot);
  }
  svg.append(svgNode("text", { x: left, y: height - 7, fill: "#53677b", "font-size": 11 }, formatClock(timelineTime(intervals[0]))));
  svg.append(svgNode("text", { x: width - right, y: height - 7, fill: "#53677b", "font-size": 11, "text-anchor": "end" }, formatClock(timelineTime(intervals[intervals.length - 1]))));
  svg.append(svgNode("text", { x: width / 2 - 23, y: height - 7, fill: "#53677b", "font-size": 11 }, "Time →"));
  wrap.append(svg);
}

function signalText(value) {
  if (value === true) return "Observed";
  if (value === false || value === null || value === undefined) return "No signal observed";
  if (typeof value === "number") return value > 0 ? `${value} observed` : "No signal observed";
  return String(value);
}

function renderCorrelations(correlations) {
  const container = $("correlation-list");
  container.replaceChildren();
  if (!correlations.length) { container.textContent = "No markers were recorded."; return; }
  for (const correlation of correlations) {
    const box = document.createElement("div"); box.className = "correlation";
    const title = document.createElement("strong"); title.textContent = correlation.label || correlation.marker?.label || "Test marker";
    const note = document.createElement("p");
    const signals = correlation.observed || correlation.signals || {};
    if (Array.isArray(signals)) {
      note.textContent = signals.length ? signals.map((signal) => {
        if (typeof signal === "string") return signal;
        if (signal.event_type === "visibilitychange") return `visibilitychange: ${signal.visibility_state}`;
        if (signal.event_type === "heartbeat_gap") return `heartbeat gap: ${Math.round(signal.delta_ms)} ms (${signal.gap_level})`;
        if (["copy", "paste", "cut"].includes(signal.event_type)) return `${signal.event_type}: ${signal.metadata?.character_count ?? 0} characters`;
        return signal.event_type || signal.kind || "event";
      }).join(" · ") : (correlation.observation || "No browser signals observed within ±3 seconds.");
    } else {
      const parts = Object.entries(signals).map(([key, value]) => `${key.replaceAll("_", " ")}: ${signalText(value)}`);
      note.textContent = parts.length ? parts.join(" · ") : "No browser signals observed within ±3 seconds.";
    }
    box.append(title, note); container.append(box);
  }
}

function renderMatrix(rows) {
  const container = $("matrix-table");
  container.replaceChildren();
  if (!rows.length) { container.textContent = "Add labeled markers during a test to populate this table from measured data."; return; }
  const columns = [["action", "Action"], ["visibilitychange", "Visibility change"], ["blur", "Blur"], ["fullscreenchange", "Fullscreen change"], ["heartbeat_anomaly", "Heartbeat anomaly"], ["clipboard_signal", "Clipboard signal"], ["browser_observable", "Browser observable?"]];
  const table = document.createElement("table");
  const head = document.createElement("thead"), headingRow = document.createElement("tr");
  for (const [, label] of columns) { const cell = document.createElement("th"); cell.textContent = label; headingRow.append(cell); }
  head.append(headingRow); table.append(head);
  const body = document.createElement("tbody");
  for (const row of rows) {
    const tr = document.createElement("tr");
    for (const [key] of columns) {
      const cell = document.createElement("td");
      const value = valueFrom(row, key, key === "action" ? "label" : key === "browser_observable" ? "observable" : key);
      cell.textContent = key === "action" ? String(value ?? "—") : signalText(value);
      tr.append(cell);
    }
    body.append(tr);
  }
  table.append(body); container.append(table);
}

function renderAnalysis(analysis) {
  renderSummary(analysis);
  renderTimeline(analysis.timeline || []);
  renderHeartbeatGraph(analysis.heartbeat_points || analysis.heartbeats || []);
  renderCorrelations(analysis.correlations || analysis.marker_correlations || []);
  renderMatrix(analysis.detection_matrix || []);
}

function updateCursorPosition() {
  const editor = $("code-editor");
  const beforeCursor = editor.value.slice(0, editor.selectionStart);
  const lines = beforeCursor.split("\n");
  $("cursor-position").textContent = `Ln ${lines.length}, Col ${lines[lines.length - 1].length + 1}`;
}

function switchLanguage() {
  const nextLanguage = $("language").value;
  editorDrafts[currentLanguage] = $("code-editor").value;
  currentLanguage = nextLanguage;
  $("code-editor").value = editorDrafts[nextLanguage] ?? starterCode[nextLanguage];
  $("editor-extension").textContent = { "Python 3": "py", JavaScript: "js", "C++": "cpp", Java: "java" }[nextLanguage];
  updateCursorPosition();
}

function setInputMode(mode) {
  const sample = mode === "sample";
  $("use-sample").classList.toggle("is-selected", sample);
  $("use-custom").classList.toggle("is-selected", !sample);
  $("use-sample").setAttribute("aria-pressed", String(sample));
  $("use-custom").setAttribute("aria-pressed", String(!sample));
  $("custom-input").readOnly = sample;
  if (sample) $("custom-input").value = $("sample-input").textContent.trim();
  else { $("custom-input").value = ""; $("custom-input").focus(); }
  $("expected-output").textContent = sample ? "13" : "Not computed for custom input.";
}

function simulateAssessmentAction(action) {
  const isSubmission = action === "Submit";
  if (isSubmission) {
    mockSubmissionCount += 1;
    $("submission-count").textContent = `Mock submissions this visit: ${mockSubmissionCount}`;
    $("problem-state").textContent = `Mock submitted ${mockSubmissionCount} time${mockSubmissionCount === 1 ? "" : "s"}`;
  }
  $("result-state").textContent = isSubmission ? "Mock submitted" : "Simulation only";
  $("result-state").classList.add("is-simulated");
  $("editor-result").textContent = isSubmission
    ? "Mock submission recorded in this browser tab. No source code was sent, executed, graded, or saved."
    : "Run requested. This safe simulation does not execute code, so it cannot produce a program output or verdict.";
  $("program-output").textContent = "Not available — code execution is disabled.";
  $("result-heading").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function initEditor() {
  const editor = $("code-editor");
  editorDrafts[currentLanguage] = editor.value;
  for (const type of ["input", "keyup", "click", "select"]) editor.addEventListener(type, updateCursorPosition);
  editor.addEventListener("keydown", (event) => {
    if (event.key !== "Tab" || event.ctrlKey || event.altKey || event.metaKey) return;
    event.preventDefault();
    const start = editor.selectionStart, end = editor.selectionEnd;
    editor.setRangeText("    ", start, end, "end");
    updateCursorPosition();
  });
  $("language").addEventListener("change", switchLanguage);
  $("font-size").addEventListener("change", () => { editor.style.fontSize = `${$("font-size").value}px`; });
  $("reset-code").addEventListener("click", () => {
    if (!window.confirm("Replace the current draft with the starter comment?")) return;
    editor.value = starterCode[currentLanguage];
    editorDrafts[currentLanguage] = editor.value;
    editor.focus();
    updateCursorPosition();
  });
  $("use-sample").addEventListener("click", () => setInputMode("sample"));
  $("use-custom").addEventListener("click", () => setInputMode("custom"));
  $("copy-sample").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText($("sample-input").textContent.trim());
      $("editor-result").textContent = "Sample copied. Programmatic clipboard writes may not produce a browser copy event; use Ctrl+C to test that signal.";
    } catch (error) {
      $("editor-result").textContent = `Sample could not be copied: ${error.message}`;
    }
  });
  $("run-code").addEventListener("click", () => simulateAssessmentAction("Run"));
  $("submit-code").addEventListener("click", () => simulateAssessmentAction("Submit"));
  updateCursorPosition();
}

function init() {
  updateEnvironment();
  renderExperiment();
  installEventListeners();
  initEditor();
  $("start-test").addEventListener("click", startTest);
  $("end-test").addEventListener("click", endTest);
  $("add-marker").addEventListener("click", showMarkerDialog);
  $("cancel-marker").addEventListener("click", () => $("marker-dialog").close());
  $("marker-form").addEventListener("submit", saveMarker);
  $("experiment-select").addEventListener("change", renderExperiment);
  $("view-report").addEventListener("click", () => window.open(`/api/session/${encodeURIComponent(state.id)}/report`, "_blank", "noopener"));
  $("toggle-fullscreen").addEventListener("click", async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await document.documentElement.requestFullscreen();
    } catch (error) { setMessage(`Page fullscreen request failed: ${error.message}`, true); }
  });
}

init();
