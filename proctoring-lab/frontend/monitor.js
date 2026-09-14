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
  eventSequence: 0,
  warningCount: 0,
  durationMinutes: 60,
  submissions: [],
  domContentLoaded: null,
  preStartEvents: [],
  stats: { focusLosses: 0, hidden: 0, paste: 0 },
};

const $ = (id) => document.getElementById(id);
const experimentTemplates = {
  a: { title: "A · Normal browser tab switch", steps: ["Start the session.", "Open another browser tab and wait a few seconds.", "Return to this tab.", "Add a marker labeled “Browser tab switch”."], marker: "Browser tab switch" },
  b: { title: "B · Alt-Tab to another application", steps: ["Start the session.", "Use Alt-Tab to switch to another application.", "Return to this browser.", "Add a marker labeled “Alt-Tab to application”."], marker: "Alt-Tab to application" },
  c: { title: "C · Minimize browser", steps: ["Start the session.", "Minimize the browser window and wait a few seconds.", "Restore it.", "Add a marker labeled “Browser minimized”."], marker: "Browser minimized" },
  d: { title: "D · Enter and exit fullscreen", steps: ["Start the session.", "Use TOGGLE PAGE FULLSCREEN above the problem to enter page fullscreen.", "Use the same button or Escape to exit. Browser F11 mode may behave differently.", "Add a marker labeled “Fullscreen enter and exit”."], marker: "Fullscreen enter and exit" },
  e: { title: "E · Copy and paste", steps: ["Start the session.", "Copy a short piece of practice text in this local page.", "Paste it into the editor.", "Add a marker labeled “Copy and paste”."], marker: "Copy and paste" },
  f: { title: "F · Launch benign overlay", steps: ["Start the session.", "Launch overlay/benign_overlay.py on the same desktop.", "Show, move, or focus its visible window. Return to the browser.", "Add a marker labeled “Benign overlay opened”."], marker: "Benign overlay opened" },
  g: { title: "G · VMware host test", steps: ["Inside the guest VM, start this simulation. START ASSESSMENT requests page fullscreen in the guest.", "Add a Before action marker, then from the host OS minimize the VMware application manually.", "Wait 10 seconds. Do not automate the host action.", "Restore VMware, then add VMware minimized and VMware restored markers in the guest browser.", "Review only the signals and heartbeat intervals actually recorded."], marker: "VMware minimized" },
  h: { title: "H · VMware guest Alt-Tab", steps: ["Inside the guest VM, start the session.", "Use Alt-Tab inside the guest to switch to a guest application.", "Return to the guest browser.", "Add a marker labeled “Guest Alt-Tab”."], marker: "Guest Alt-Tab" },
  i: { title: "I · Switch host application", steps: ["Inside the guest VM, start the session and leave the guest browser open.", "On the host OS, switch to another host application without automating the guest.", "Return to VMware.", "Add a marker labeled “Host application switch”."], marker: "Host application switch" },
};

const questions = {
  q1: { number: 1, title: "Array maximum", description: "Given an array of N integers, output its maximum value.", input: "The first line contains N. The second line contains N space-separated integers.", output: "Print one integer: the maximum value in the array.", constraints: ["1 ≤ N ≤ 100,000", "−1,000,000 ≤ each integer ≤ 1,000,000"], sampleInput: "4\n3 7 -2 5", sampleOutput: "7", explanation: "7 is the largest value in the array." },
  q2: { number: 2, title: "Balanced parentheses", description: "Determine whether a string of opening and closing parentheses is balanced.", input: "A single line containing only the characters ( and ).", output: "Print YES if every opening parenthesis is matched in order; otherwise print NO.", constraints: ["1 ≤ string length ≤ 100,000"], sampleInput: "(()())", sampleOutput: "YES", explanation: "Every opening parenthesis has a matching closing parenthesis." },
  q3: { number: 3, title: "Binary search", description: "Given a sorted array and a target value, find the target's zero-based index. If the target is absent, output −1.", input: "The first line contains N and target. The second line contains N strictly increasing integers.", output: "Print the target's zero-based index, or −1 if it is absent.", constraints: ["1 ≤ N ≤ 100,000", "−1,000,000 ≤ each integer and target ≤ 1,000,000"], sampleInput: "5 7\n1 3 5 7 9", sampleOutput: "3", explanation: "The target 7 is at zero-based index 3." },
};
const starterCode = {
  Python: "# Write your solution here.\n# This local lab does not execute or grade code.\n",
  C: "// Write your solution here.\n// This local lab does not execute or grade code.\n",
  "C++": "// Write your solution here.\n// This local lab does not execute or grade code.\n",
  Java: "// Write your solution here.\n// This local lab does not execute or grade code.\n",
};
const editorDrafts = {};
const customInputDrafts = {};
const inputModes = {};
let currentQuestion = "q1";
let currentLanguage = "Python";
let lastEditorLength = 0;

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
  $("header-session").textContent = state.status === "idle" ? "Not started" : `${state.id.slice(0, 8)}…`;
  $("header-fullscreen").textContent = document.fullscreenElement ? "Yes" : "No";
  $("session-start").textContent = state.startedAt ? formatDateTime(state.startedAt) : "Not started";
  $("browser-name").textContent = browserName();
  $("platform-name").textContent = currentPlatform();
  $("viewport-size").textContent = `${window.innerWidth} × ${window.innerHeight}`;
  $("screen-size").textContent = `${screen.width} × ${screen.height}`;
}

function updateElapsed() {
  const seconds = state.startedAt ? Math.max(0, Math.floor((Date.now() - new Date(state.startedAt).getTime()) / 1000)) : 0;
  $("elapsed-time").textContent = `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
  const remaining = Math.max(0, state.durationMinutes * 60 - seconds);
  $("time-left").textContent = `${String(Math.floor(remaining / 60)).padStart(2, "0")}:${String(remaining % 60).padStart(2, "0")}`;
  $("time-left").classList.toggle("time-warning", remaining <= 300 && state.startedAt !== null);
}

function formatDateTime(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value || "—") : date.toLocaleString();
}

function formatClock(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}:${String(date.getSeconds()).padStart(2, "0")}.${String(date.getMilliseconds()).padStart(3, "0")}`;
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
  $("export-json").disabled = status !== "ended";
  $("export-csv").disabled = status !== "ended";
  $("run-code").disabled = status !== "active";
  $("submit-code").disabled = status !== "active";
  $("duration-select").disabled = status !== "idle";
  $("status-proctoring").textContent = { idle: "Not started", starting: "Starting local test", active: "Recording local signals", ending: "Ending local test", "end-error": "End save error", ended: "Ended" }[status];
  updateEnvironment();
}

async function api(path, body) {
  let response;
  try {
    response = await fetch(path, {
      method: body === undefined ? "GET" : "POST",
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
    });
  } catch (error) {
    if (state.status === "active" && path !== "/api/events") recordEvent("fetch_failure", { operation: apiOperation(path) });
    throw error;
  }
  if (!response.ok) {
    if (state.status === "active" && path !== "/api/events") recordEvent("fetch_failure", { operation: apiOperation(path) });
    let detail = `${response.status} ${response.statusText}`;
    try { detail = (await response.json()).detail || detail; } catch { /* A non-JSON error is still shown. */ }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return response.json();
}

function apiOperation(path) {
  if (path.includes("heartbeat")) return "heartbeat";
  if (path.includes("submission")) return "submission";
  if (path.includes("marker")) return "marker";
  if (path.includes("session/end")) return "session_end";
  return "session_request";
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
  if (type === "fullscreenchange" || type === "fullscreen_error") return "fullscreen";
  if (["online", "offline", "fetch_failure"].includes(type)) return "network";
  if (type === "editor_change") return "editor";
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
  if (type === "editor_change") return `${metadata.change_size || "SMALL_CHANGE"} · length ${metadata.old_length ?? 0} → ${metadata.new_length ?? 0}`;
  if (type === "domcontentloaded") return "document content loaded before test start";
  if (type === "fullscreen_error") return "page fullscreen request failed";
  if (type === "online") return "browser reported online";
  if (type === "offline") return "browser reported offline";
  if (type === "fetch_failure") return `${metadata.operation || "request"} request failed`;
  if (type === "marker") return payload.label || "test marker";
  if (type === "heartbeat") return payload.delta_ms == null ? "initial heartbeat" : `${Math.round(payload.delta_ms)} ms interval${payload.gap_level ? ` · ${payload.gap_level}` : ""}`;
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
  const followLatest = list.scrollTop + list.clientHeight >= list.scrollHeight - 30;
  list.querySelector(".empty-state")?.remove();
  const item = document.createElement("li");
  item.className = `event-${eventCategory(type)}`;
  item.dataset.category = eventCategory(type);
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
  list.append(item);
  applyEventFilter();
  while (list.children.length > 150) list.firstElementChild.remove();
  if (followLatest) list.scrollTop = list.scrollHeight;
  state.eventCount += 1;
  $("event-total").textContent = `${state.eventCount} entries`;
  updateTelemetryStats(type, payload);
}

function addWarning(message, timestamp) {
  state.warningCount += 1;
  $("warning-count").textContent = state.warningCount;
  const list = $("warning-list");
  if (state.warningCount === 1) list.replaceChildren();
  const item = document.createElement("li");
  item.textContent = `${formatClock(timestamp || new Date().toISOString())} · ${message}`;
  list.prepend(item);
  while (list.children.length > 30) list.lastElementChild.remove();
  $("live-warning-text").textContent = `Browser observation: ${message}. This alone does not establish external activity.`;
  $("live-warning-banner").hidden = false;
}

function updateTelemetryStats(type, payload) {
  const focus = payload.document_has_focus ?? payload.has_focus;
  if (typeof focus === "boolean") $("stat-focus").textContent = focus ? "Yes" : "No";
  if (typeof payload.fullscreen === "boolean") $("stat-fullscreen").textContent = payload.fullscreen ? "Yes" : "No";
  if (typeof payload.fullscreen === "boolean") $("header-fullscreen").textContent = payload.fullscreen ? "Yes" : "No";
  if (payload.visibility_state) $("stat-visible").textContent = payload.visibility_state === "visible" ? "Yes" : "No";
  const time = payload.timestamp_client || payload.client_timestamp || payload.server_timestamp;
  if (type === "blur") {
    $("stat-focus-losses").textContent = ++state.stats.focusLosses;
    addWarning("Window lost focus", time);
  }
  if (type === "visibilitychange" && payload.visibility_state === "hidden") {
    $("stat-hidden").textContent = ++state.stats.hidden;
    addWarning("Document became hidden", time);
  }
  if (type === "fullscreenchange" && !payload.fullscreen) addWarning("Page exited fullscreen", time);
  if (type === "fullscreen_error") addWarning("Page fullscreen request failed", time);
  if (type === "paste") $("stat-paste").textContent = ++state.stats.paste;
  if (type === "online" || type === "offline") {
    $("stat-network").textContent = type === "online" ? "Online" : "Offline";
    $("status-network").textContent = type === "online" ? "Online" : "Offline";
    addWarning(`Browser reported ${type}`, time);
  }
  if (type === "fetch_failure") addWarning(`${payload.metadata?.operation || "Local API"} request failed`, time);
  if (type === "fetch_failure") { $("stat-network").textContent = "Request failed"; $("status-network").textContent = "Request failed"; }
  if (type === "heartbeat") {
    $("stat-heartbeat").textContent = payload.delta_ms == null ? "First" : `${Math.round(payload.delta_ms)} ms`;
    if (["WARNING", "LARGE GAP"].includes(payload.gap_level)) addWarning(`${payload.gap_level}: ${Math.round(payload.delta_ms)} ms heartbeat gap`, time);
  }
}

function applyEventFilter() {
  const filter = $("event-filter").value;
  for (const item of $("event-list").children) item.hidden = filter !== "all" && item.dataset.category !== filter;
}

function sendUnloadEvent(payload) {
  const data = new Blob([JSON.stringify(payload)], { type: "application/json" });
  if (navigator.sendBeacon?.("/api/events", data)) return;
  fetch("/api/events", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload), keepalive: true }).catch(() => {});
}

function recordEvent(eventType, metadata = {}, unload = false, observedAt = null, observedSnapshot = null) {
  if (state.status === "starting" && ["fullscreenchange", "fullscreen_error"].includes(eventType)) {
    state.preStartEvents.push({ eventType, metadata, observedAt: observedAt || { timestamp_client: new Date(Date.now()).toISOString(), performance_ms: performance.now() }, observedSnapshot: observedSnapshot || snapshot() });
    return;
  }
  if (state.status !== "active") return;
  const payload = {
    event_id: crypto.randomUUID(),
    session_id: state.id,
    event_type: eventType,
    sequence: ++state.eventSequence,
    performance_ms: observedAt?.performance_ms ?? performance.now(),
    timestamp_client: observedAt?.timestamp_client ?? new Date(Date.now()).toISOString(),
    ...(observedSnapshot || snapshot()),
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
  document.addEventListener("DOMContentLoaded", () => {
    state.domContentLoaded = { timestamp_client: new Date(Date.now()).toISOString(), performance_ms: performance.now() };
  }, { once: true });
  if (document.readyState !== "loading") {
    const navigation = performance.getEntriesByType("navigation")[0];
    const ms = navigation?.domContentLoadedEventEnd || performance.now();
    state.domContentLoaded = { timestamp_client: new Date(performance.timeOrigin + ms).toISOString(), performance_ms: ms };
  }
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
  window.addEventListener("online", () => recordEvent("online"));
  window.addEventListener("offline", () => recordEvent("offline"));
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
      performance_ms: performance.now(),
      visibility_state: document.visibilityState,
      has_focus: document.hasFocus(),
      fullscreen: Boolean(document.fullscreenElement),
    });
    state.pendingHeartbeatRequest = request;
    const result = await request;
    if (state.status === "active") {
      appendLive("heartbeat", result);
    }
  } catch (error) {
    if (state.status === "active") setMessage(`Heartbeat could not be saved: ${error.message}`, true);
  } finally {
    state.pendingHeartbeatRequest = null;
    state.heartbeatInFlight = false;
  }
}

function requestAssessmentFullscreen() {
  try {
    if (typeof document.documentElement.requestFullscreen !== "function") throw new Error("Fullscreen API unavailable");
    // Called synchronously from the START ASSESSMENT click, before any await.
    Promise.resolve(document.documentElement.requestFullscreen()).catch((error) => {
      recordEvent("fullscreen_error");
      setMessage(`Page fullscreen request failed: ${error.message}`, true);
    });
  } catch (error) {
    recordEvent("fullscreen_error");
    setMessage(`Page fullscreen request failed: ${error.message}`, true);
  }
}

async function startTest() {
  if (state.status !== "idle") return;
  setStatus("starting");
  setMessage("Starting local session…");
  requestAssessmentFullscreen();
  try {
    const result = await api("/api/session/start", {
      id: state.id,
      started_at: new Date().toISOString(),
      user_agent: navigator.userAgent,
      platform: currentPlatform(),
      screen_width: screen.width,
      screen_height: screen.height,
      language: navigator.language || "unknown",
      hardware_concurrency: navigator.hardwareConcurrency || null,
      device_memory: navigator.deviceMemory || null,
      viewport_width: window.innerWidth,
      viewport_height: window.innerHeight,
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "unknown",
      duration_minutes: state.durationMinutes,
    });
    state.id = result.id;
    state.startedAt = result.started_at;
    state.durationMinutes = result.duration_minutes || state.durationMinutes;
    updateEnvironment();
    updateElapsed();
    setStatus("active");
    setMessage("Recording page events and sending a heartbeat every two seconds.");
    if (state.domContentLoaded) recordEvent("domcontentloaded", {}, false, state.domContentLoaded);
    for (const buffered of state.preStartEvents.splice(0)) recordEvent(buffered.eventType, buffered.metadata, false, buffered.observedAt, buffered.observedSnapshot);
    await sendHeartbeat();
    if (state.status === "active") {
      state.heartbeatTimer = window.setInterval(sendHeartbeat, 2000);
      state.elapsedTimer = window.setInterval(updateElapsed, 1000);
    }
  } catch (error) {
    state.preStartEvents.length = 0;
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
    setMessage(`Session end could not be saved: ${error.message}. Click END ASSESSMENT to retry.`, true);
    return;
  }
  setStatus("ended");
  try {
    const submissionHistory = await api(`/api/session/${encodeURIComponent(state.id)}/submissions`);
    state.submissions = submissionHistory.items || state.submissions;
    renderSubmissionHistory();
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
  $("marker-preset").value = $("marker-label").value;
  $("marker-dialog").showModal();
  $("marker-label").focus();
}

async function saveMarker(event) {
  event.preventDefault();
  if (state.status !== "active") return;
  const label = $("marker-label").value.trim().replace(/[\x00-\x1f\x7f]/g, " ").slice(0, 100);
  if (!label) { $("marker-label").focus(); return; }
  await addMarkerLabel(label);
}

async function addMarkerLabel(label) {
  if (state.status !== "active") return;
  const timestampClient = new Date().toISOString();
  try {
    await api("/api/marker", { session_id: state.id, label, timestamp_client: timestampClient });
    appendLive("marker", { label, timestamp_client: timestampClient });
    if ($("marker-dialog").open) $("marker-dialog").close();
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
    ["Fullscreen errors", valueFrom(summary, "fullscreen_error_count") ?? 0],
    ["Network changes", valueFrom(summary, "network_change_count") ?? 0],
    ["Fetch failures", valueFrom(summary, "fetch_failure_count") ?? 0],
    ["Editor changes", valueFrom(summary, "editor_change_count") ?? 0],
    ["Mock submissions", valueFrom(summary, "submission_count") ?? 0],
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
  for (const [name, color] of [["Focus", "#208470"], ["Visibility", "#d48224"], ["Fullscreen", "#795cbd"], ["Network", "#a4462e"], ["Editor", "#285f9c"], ["Clipboard", "#bf5688"], ["Heartbeat", "#6f97ba"], ["Marker", "#d06c24"]]) {
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
      const parts = Object.entries(signals).map(([key, value]) => {
        if (key === "browser_state_snapshot" && value && typeof value === "object") return `browser snapshot: ${JSON.stringify(value)}`;
        return `${key.replaceAll("_", " ")}: ${signalText(value)}`;
      });
      note.textContent = parts.length ? parts.join(" · ") : "No browser signals observed within ±3 seconds.";
    }
    box.append(title, note); container.append(box);
  }
}

function renderMatrix(rows) {
  const container = $("matrix-table");
  container.replaceChildren();
  if (!rows.length) { container.textContent = "Add labeled markers during a test to populate this table from measured data."; return; }
  const columns = [["action", "Action"], ["visibilitychange", "Visibility change"], ["blur", "Blur"], ["fullscreenchange", "Fullscreen change"], ["heartbeat_anomaly", "Heartbeat anomaly"], ["heartbeat_gap_ms", "Max gap (ms)"], ["network_change", "Network change"], ["clipboard_signal", "Clipboard signal"], ["browser_observable", "Browser observable?"]];
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

function draftKey(question = currentQuestion, language = currentLanguage) {
  return `${question}:${language}`;
}

function saveCurrentDraft() {
  editorDrafts[draftKey()] = $("code-editor").value;
  if (inputModes[currentQuestion] === "custom") customInputDrafts[currentQuestion] = $("custom-input").value;
}

function renderInputMode() {
  const sample = (inputModes[currentQuestion] || "sample") === "sample";
  $("use-sample").classList.toggle("is-selected", sample);
  $("use-custom").classList.toggle("is-selected", !sample);
  $("use-sample").setAttribute("aria-pressed", String(sample));
  $("use-custom").setAttribute("aria-pressed", String(!sample));
  $("custom-input").readOnly = sample;
  $("custom-input").value = sample ? questions[currentQuestion].sampleInput : (customInputDrafts[currentQuestion] || "");
  $("expected-output").textContent = sample ? questions[currentQuestion].sampleOutput : "Not computed for custom input.";
}

function renderQuestion() {
  const question = questions[currentQuestion];
  $("problem-kicker").textContent = `QUESTION ${question.number} / 3 · PRACTICE`;
  $("problem-title").textContent = question.title;
  $("problem-description").textContent = question.description;
  $("input-format").textContent = question.input;
  $("output-format").textContent = question.output;
  $("constraints-list").replaceChildren(...question.constraints.map((constraint) => {
    const li = document.createElement("li"); li.textContent = constraint; return li;
  }));
  $("sample-input").textContent = question.sampleInput;
  $("sample-output").textContent = question.sampleOutput;
  $("problem-explanation").textContent = question.explanation;
  $("workspace-question").textContent = `WORKSPACE / QUESTION ${question.number}`;
  $("code-editor").value = editorDrafts[draftKey()] ?? starterCode[currentLanguage];
  lastEditorLength = $("code-editor").value.length;
  renderInputMode();
  for (const tab of document.querySelectorAll("[data-question]")) {
    const selected = tab.dataset.question === currentQuestion;
    tab.classList.toggle("is-current", selected);
    if (selected) tab.setAttribute("aria-current", "page"); else tab.removeAttribute("aria-current");
  }
  $("result-state").textContent = "Not run";
  $("result-state").classList.remove("is-simulated");
  $("editor-result").textContent = "Mock Run/Submit records are independent of code correctness. Source remains in this browser tab.";
  $("program-output").textContent = "Unavailable — code execution is disabled.";
  renderSubmissionHistory();
  updateCursorPosition();
}

function switchQuestion(questionId) {
  if (!questions[questionId] || questionId === currentQuestion) return;
  saveCurrentDraft();
  currentQuestion = questionId;
  renderQuestion();
}

function switchLanguage() {
  const nextLanguage = $("language").value;
  saveCurrentDraft();
  currentLanguage = nextLanguage;
  $("code-editor").value = editorDrafts[draftKey()] ?? starterCode[nextLanguage];
  lastEditorLength = $("code-editor").value.length;
  $("editor-extension").textContent = { Python: "py", C: "c", "C++": "cpp", Java: "java" }[nextLanguage];
  updateCursorPosition();
}

function setInputMode(mode) {
  if (inputModes[currentQuestion] === "custom") customInputDrafts[currentQuestion] = $("custom-input").value;
  inputModes[currentQuestion] = mode;
  renderInputMode();
  if (mode === "custom") $("custom-input").focus();
}

function renderSubmissionHistory() {
  const list = $("submission-history");
  list.replaceChildren();
  const items = state.submissions.filter((item) => item.question_id === currentQuestion).slice(-12).reverse();
  if (!items.length) { const empty = document.createElement("li"); empty.textContent = "No mock submissions for this question."; list.append(empty); }
  for (const item of items) {
    const li = document.createElement("li");
    const time = item.timestamp_server || item.server_timestamp || item.timestamp_client;
    li.textContent = `#${item.submission_number} · ${formatClock(time)} · ${item.action.toUpperCase()} · ${item.language} · Mock ${item.result} (scripted)`;
    list.append(li);
  }
  const submits = state.submissions.filter((item) => item.action === "submit");
  $("submission-count").textContent = `Mock submissions this session: ${submits.length}`;
  $("status-submission-count").textContent = String(submits.length);
  for (const id of Object.keys(questions)) {
    const count = submits.filter((item) => item.question_id === id).length;
    $(`nav-state-${id}`).textContent = count ? `${count} mock submission${count === 1 ? "" : "s"}` : "Not submitted";
  }
}

async function simulateAssessmentAction(action) {
  if (state.status !== "active") return;
  saveCurrentDraft();
  $("run-code").disabled = true;
  $("submit-code").disabled = true;
  $("result-state").textContent = "Recording…";
  try {
    const record = await api("/api/submission", {
      session_id: state.id, question_id: currentQuestion, language: currentLanguage,
      action, code_length: $("code-editor").value.length,
      timestamp_client: new Date(Date.now()).toISOString(),
    });
    state.submissions.push(record);
    renderSubmissionHistory();
    $("result-state").textContent = `Mock ${record.result}`;
    if (action === "run") $("last-run-status").textContent = `Mock ${record.result}`;
    $("editor-result").textContent = `${record.evaluation_note || "Mock result only; source code was not evaluated."} The result is scripted and independent of your code or custom input.`;
  } catch (error) {
    $("result-state").textContent = "Record failed";
    $("editor-result").textContent = `Mock ${action} could not be recorded: ${error.message}`;
  } finally {
    $("run-code").disabled = state.status !== "active";
    $("submit-code").disabled = state.status !== "active";
  }
  $("result-state").classList.add("is-simulated");
  $("program-output").textContent = "Unavailable — code execution is disabled. The mock result above is scripted.";
  $("result-heading").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function initEditor() {
  const editor = $("code-editor");
  editorDrafts[draftKey()] = editor.value;
  lastEditorLength = editor.value.length;
  for (const type of ["input", "keyup", "click", "select"]) editor.addEventListener(type, updateCursorPosition);
  editor.addEventListener("input", () => {
    const newLength = editor.value.length;
    const delta = newLength - lastEditorLength;
    const magnitude = Math.abs(delta);
    recordEvent("editor_change", {
      old_length: lastEditorLength,
      new_length: newLength,
      delta_length: delta,
      change_size: magnitude < 30 ? "SMALL_CHANGE" : magnitude <= 150 ? "MEDIUM_CHANGE" : "LARGE_CHANGE",
    });
    lastEditorLength = newLength;
    editorDrafts[draftKey()] = editor.value;
  });
  editor.addEventListener("keydown", (event) => {
    if (event.key !== "Tab" || event.ctrlKey || event.altKey || event.metaKey) return;
    event.preventDefault();
    const start = editor.selectionStart, end = editor.selectionEnd;
    editor.setRangeText("    ", start, end, "end");
    editor.dispatchEvent(new Event("input", { bubbles: true }));
    updateCursorPosition();
  });
  $("language").addEventListener("change", switchLanguage);
  for (const tab of document.querySelectorAll("[data-question]")) tab.addEventListener("click", () => switchQuestion(tab.dataset.question));
  $("font-size").addEventListener("change", () => { editor.style.fontSize = `${$("font-size").value}px`; });
  $("reset-code").addEventListener("click", () => {
    if (!window.confirm("Replace the current draft with the starter comment?")) return;
    editor.value = starterCode[currentLanguage];
    editorDrafts[draftKey()] = editor.value;
    lastEditorLength = editor.value.length;
    editor.focus();
    updateCursorPosition();
  });
  $("use-sample").addEventListener("click", () => setInputMode("sample"));
  $("use-custom").addEventListener("click", () => setInputMode("custom"));
  $("custom-input").addEventListener("input", () => { if (inputModes[currentQuestion] === "custom") customInputDrafts[currentQuestion] = $("custom-input").value; });
  $("copy-sample").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText($("sample-input").textContent.trim());
      $("editor-result").textContent = "Sample copied. Programmatic clipboard writes may not produce a browser copy event; use Ctrl+C to test that signal.";
    } catch (error) {
      $("editor-result").textContent = `Sample could not be copied: ${error.message}`;
    }
  });
  $("run-code").addEventListener("click", () => simulateAssessmentAction("run"));
  $("submit-code").addEventListener("click", () => simulateAssessmentAction("submit"));
  renderQuestion();
  updateCursorPosition();
}

function setTelemetryOpen(open) {
  if (!open && $("telemetry-sidebar").contains(document.activeElement)) $("toggle-telemetry").focus();
  $("telemetry-sidebar").classList.toggle("is-open", open);
  $("telemetry-sidebar").inert = !open;
  $("telemetry-sidebar").setAttribute("aria-hidden", String(!open));
  $("toggle-telemetry").setAttribute("aria-expanded", String(open));
  $("telemetry-backdrop").hidden = !open;
}

function init() {
  updateEnvironment();
  $("stat-fullscreen").textContent = document.fullscreenElement ? "Yes" : "No";
  $("stat-visible").textContent = document.visibilityState === "visible" ? "Yes" : "No";
  $("stat-focus").textContent = document.hasFocus() ? "Yes" : "No";
  $("stat-network").textContent = navigator.onLine ? "Online" : "Offline";
  $("status-network").textContent = navigator.onLine ? "Online" : "Offline";
  renderExperiment();
  installEventListeners();
  initEditor();
  $("start-test").addEventListener("click", startTest);
  $("end-test").addEventListener("click", endTest);
  $("add-marker").addEventListener("click", showMarkerDialog);
  $("cancel-marker").addEventListener("click", () => $("marker-dialog").close());
  $("marker-form").addEventListener("submit", saveMarker);
  $("experiment-select").addEventListener("change", renderExperiment);
  $("duration-select").addEventListener("change", () => { if (state.status === "idle") { state.durationMinutes = Number($("duration-select").value); updateElapsed(); } });
  $("marker-preset").addEventListener("change", () => { if ($("marker-preset").value) $("marker-label").value = $("marker-preset").value; });
  $("dismiss-warning").addEventListener("click", () => { $("live-warning-banner").hidden = true; });
  $("vm-mode").addEventListener("change", () => {
    if ($("vm-mode").checked) $("experiment-select").value = "g";
    renderExperiment();
    setMessage($("vm-mode").checked ? "VM guest mode selected. Carry out host actions manually, then add before/after markers." : "Normal browser experiment mode selected.");
  });
  for (const button of document.querySelectorAll("[data-marker]")) button.addEventListener("click", () => addMarkerLabel(button.dataset.marker));
  $("event-filter").addEventListener("change", applyEventFilter);
  $("toggle-telemetry").addEventListener("click", () => setTelemetryOpen($("toggle-telemetry").getAttribute("aria-expanded") !== "true"));
  $("close-telemetry").addEventListener("click", () => setTelemetryOpen(false));
  $("telemetry-backdrop").addEventListener("click", () => setTelemetryOpen(false));
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") setTelemetryOpen(false); });
  $("view-report").addEventListener("click", () => window.open(`/api/session/${encodeURIComponent(state.id)}/report`, "_blank", "noopener"));
  $("export-json").addEventListener("click", () => { window.location.href = `/api/session/${encodeURIComponent(state.id)}/export/json`; });
  $("export-csv").addEventListener("click", () => { window.location.href = `/api/session/${encodeURIComponent(state.id)}/export/csv`; });
  $("toggle-fullscreen").addEventListener("click", async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await document.documentElement.requestFullscreen();
    } catch (error) { recordEvent("fullscreen_error"); setMessage(`Page fullscreen request failed: ${error.message}`, true); }
  });
}

init();
