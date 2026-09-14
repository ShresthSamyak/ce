"""Standalone, escaped HTML report for a measured local assessment session."""

from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any


def h(value: Any) -> str:
    """Escape untrusted database text before placing it in HTML."""
    return escape(str(value), quote=True)


def _moment(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _time(value: str) -> str:
    return _moment(value).strftime("%H:%M:%S.%f")[:-3]


def _duration(ms: int) -> str:
    total = ms // 1000
    return f"{total // 60:02d}:{total % 60:02d}"


def _category(item: dict[str, Any]) -> str:
    if item["kind"] != "EVENT":
        return item["kind"].lower()
    event_type = item["event_type"]
    if event_type in {"focus", "blur"}:
        return "focus"
    if event_type == "visibilitychange":
        return "visibility"
    if event_type in {"fullscreenchange", "fullscreen_error"}:
        return "fullscreen"
    if event_type in {"copy", "paste", "cut"}:
        return "clipboard"
    if event_type in {"online", "offline", "fetch_failure"}:
        return "network"
    if event_type == "editor_change":
        return "editor"
    return "other"


def _description(item: dict[str, Any]) -> str:
    kind = item["kind"]
    if kind == "MARKER":
        return "Marker: " + item["label"]
    if kind == "HEARTBEAT":
        interval = item["delta_ms"]
        return f"Heartbeat #{item['sequence']}" + (
            f" · {interval:.0f} ms · {item['gap_level']}" if interval is not None else " · first"
        )
    if kind == "SUBMISSION":
        return (
            f"{item['action'].title()} #{item['submission_number']} · "
            f"{item['question_id']} · {item['language']} · {item['result']}"
        )
    if kind == "SESSION":
        return "Session " + item["event_type"]
    event_type = item["event_type"]
    if event_type == "visibilitychange":
        return "Document " + item["visibility_state"]
    if event_type == "fullscreenchange":
        return "Fullscreen " + ("entered" if item["fullscreen"] else "exited")
    if event_type in {"copy", "paste", "cut"}:
        count = item["metadata"].get("character_count", 0)
        return f"{event_type.title()} · {count} character(s) measured"
    if event_type == "editor_change":
        meta = item["metadata"]
        return (
            f"Editor change · {meta.get('old_length', '?')} → {meta.get('new_length', '?')} "
            f"· {meta.get('change_size', 'unclassified')}"
        )
    return event_type.upper()


def _heartbeat_chart(points: list[dict[str, Any]]) -> str:
    measured = [point for point in points if point["delta_ms"] is not None]
    if not measured:
        return '<p class="empty">At least two heartbeats are needed to plot intervals.</p>'
    values = [float(point["delta_ms"]) for point in measured]
    width, height = 920, 260
    left, right, top, bottom = 70, 25, 20, 42
    plot_width, plot_height = width - left - right, height - top - bottom
    max_y = max(10000.0, max(values) * 1.1)
    first_time = _moment(measured[0]["timestamp_server"])
    times = [(_moment(point["timestamp_server"]) - first_time).total_seconds() for point in measured]
    span = max(1.0, times[-1])
    xs = [left + value / span * plot_width for value in times]
    ys = [top + plot_height - value / max_y * plot_height for value in values]
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Heartbeat interval in milliseconds by server receipt time">']
    for level, label in ((0, "0"), (4000, "4,000"), (8000, "8,000")):
        yy = top + plot_height - level / max_y * plot_height
        parts.append(
            f'<line x1="{left}" x2="{width-right}" y1="{yy:.1f}" y2="{yy:.1f}" '
            f'stroke="#b7c5d3" stroke-dasharray="4 4"/>'
            f'<text x="{left-8}" y="{yy+4:.1f}" text-anchor="end" font-size="12">{label}</text>'
        )
    if len(xs) > 1:
        path = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
        parts.append(f'<polyline points="{path}" fill="none" stroke="#687d92" stroke-width="2"/>')
    for point, value, xx, yy in zip(measured, values, xs, ys):
        level = point["gap_level"].replace(" ", "_").lower()
        parts.append(
            f'<circle class="hb-{h(level)}" cx="{xx:.1f}" cy="{yy:.1f}" r="5">'
            f'<title>{h(_time(point["timestamp_server"]))}: {value:.1f} ms ({h(point["gap_level"])})</title>'
            '</circle>'
        )
    parts.append(
        f'<text x="{left}" y="{height-8}" font-size="12">{h(_time(measured[0]["timestamp_server"]))}</text>'
        f'<text x="{width-right}" y="{height-8}" text-anchor="end" font-size="12">{h(_time(measured[-1]["timestamp_server"]))}</text>'
        '</svg>'
    )
    return "".join(parts)


def _state_bands(data: dict[str, Any], start: datetime, end: datetime) -> str:
    """Draw observed state snapshots as time bands; unknown remains explicit."""
    observations: list[tuple[datetime, str, str, str]] = []
    for item in data["timeline"]:
        if item["kind"] == "EVENT":
            observations.append((
                _moment(item["timestamp_server"]), item["visibility_state"],
                "focused" if item["document_has_focus"] else "unfocused",
                "active" if item["fullscreen"] else "inactive",
            ))
        elif item["kind"] == "HEARTBEAT":
            observations.append((
                _moment(item["timestamp_server"]), item["visibility_state"],
                "focused" if item["has_focus"] else "unfocused",
                "active" if item["fullscreen"] else "inactive",
            ))
    observations.sort(key=lambda row: row[0])
    span = max(1.0, (end - start).total_seconds())
    width, height = 920, 148
    left, right = 112, 20
    plot_width = width - left - right
    def x(when: datetime) -> float:
        return left + max(0, min(1, (when - start).total_seconds() / span)) * plot_width
    bands = [
        ("Visibility", 15, 1, "unknown"),
        ("Focus", 55, 2, "unknown"),
        ("Fullscreen", 95, 3, "unknown"),
    ]
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Visibility, focus and fullscreen state snapshots over time">']
    for label, y, index, initial in bands:
        current_time, current_state = start, initial
        parts.append(f'<text x="4" y="{y+18}" font-size="13">{label}</text>')
        for when, *states in observations:
            when = min(max(when, start), end)
            if when > current_time:
                parts.append(_band_rect(x(current_time), x(when), y, current_state))
            current_time, current_state = when, states[index - 1]
        if end > current_time:
            parts.append(_band_rect(x(current_time), x(end), y, current_state))
        elif not observations:
            parts.append(_band_rect(x(start), x(end), y, "unknown"))
    parts.append(
        f'<text x="{left}" y="{height-5}" font-size="12">{h(_time(start.isoformat()))}</text>'
        f'<text x="{width-right}" y="{height-5}" text-anchor="end" font-size="12">{h(_time(end.isoformat()))}</text>'
        '</svg>'
    )
    return "".join(parts)


def _band_rect(x1: float, x2: float, y: int, state: str) -> str:
    width = max(0.5, x2 - x1)
    safe_state = state if state in {
        "visible", "hidden", "focused", "unfocused", "active", "inactive", "unknown"
    } else "unknown"
    return (
        f'<rect class="state-{safe_state}" x="{x1:.1f}" y="{y}" width="{width:.1f}" height="27">'
        f'<title>{h(state.upper())}</title></rect>'
    )


def _table(headers: list[str], rows: list[list[Any]], empty: str) -> str:
    head = "".join(f"<th>{h(label)}</th>" for label in headers)
    body = "".join("<tr>" + "".join(f"<td>{h(cell)}</td>" for cell in row) + "</tr>" for row in rows)
    if not body:
        body = f'<tr><td colspan="{len(headers)}">{h(empty)}</td></tr>'
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def render_report(data: dict[str, Any]) -> str:
    """Render a portable report with no remote fonts, scripts or chart assets."""
    session, summary = data["session"], data["summary"]
    start = _moment(session["started_at"])
    end = _moment(session["ended_at"]) if session["ended_at"] else datetime.now(start.tzinfo)
    span_ms = max(1, (end - start).total_seconds() * 1000)

    dots: list[str] = []
    timeline_rows: list[str] = []
    for item in data["timeline"]:
        category = _category(item)
        description = _description(item)
        when = item["timestamp_server"]
        offset = max(0, min(100, (_moment(when) - start).total_seconds() * 100000 / span_ms))
        dots.append(
            f'<span class="dot {h(category)}" style="left:{offset:.2f}%" '
            f'title="{h(_time(when))} {h(description)}"></span>'
        )
        precision = ""
        if item["kind"] == "EVENT" and item.get("performance_ms") is not None:
            precision = f" · perf {item['performance_ms']:.3f} ms · seq {item.get('sequence', '?')}"
        timeline_rows.append(
            f'<tr><td>{h(_time(when))}</td><td><span class="badge {h(category)}">{h(category.upper())}</span></td>'
            f'<td>{h(description)}{h(precision)}</td></tr>'
        )
    timeline_body = "".join(timeline_rows) or '<tr><td colspan="3">No observations.</td></tr>'
    event_rows = [[name, count] for name, count in data["event_counts"].items()]
    correlations = []
    for entry in data["correlations"]:
        observed = entry["observed"]
        signals = ", ".join(
            signal["event_type"] + (
                " (" + signal["visibility_state"] + ")" if signal["event_type"] == "visibilitychange" else ""
            )
            for signal in entry["signals"]
        ) or "No listed browser signal observed in ±3 s"
        gap = observed["heartbeat_gap_ms"]
        correlations.append([
            _time(entry["marker"]["timestamp_server"]),
            entry["marker"]["label"], signals,
            f"{gap:.1f} ms" if gap is not None else "No interval in window",
        ])
    matrix = []
    for row in data["detection_matrix"]:
        gap = row["heartbeat_gap_ms"]
        matrix.append([
            row["action"], row["window_blur"], row["document_hidden"],
            row["fullscreen_exit"], f"{gap:.1f} ms" if gap is not None else "not measured",
            row["network_change"], row["browser_observable"],
        ])
    submissions = [
        [
            item["submission_number"], _time(item["timestamp_server"]),
            item["question_id"], item["language"], item["action"],
            item["code_length"], item["result"],
        ] for item in data["submissions"]
    ]
    distribution = summary["editor_change_distribution"]
    avg = summary["average_heartbeat_interval_ms"]
    longest = summary["longest_heartbeat_gap_ms"]
    env_rows = [
        ["Start (UTC)", session["started_at"]],
        ["End (UTC)", session["ended_at"] or "Still active"],
        ["Platform reported by browser", session["platform"]],
        ["User agent", session["user_agent"]],
        ["Browser language", session.get("language") or "not recorded"],
        ["Timezone", session.get("timezone") or "not recorded"],
        ["Hardware concurrency", session.get("hardware_concurrency") if session.get("hardware_concurrency") is not None else "not recorded"],
        ["Device memory (GB)", session.get("device_memory") if session.get("device_memory") is not None else "not recorded"],
        ["Screen", f"{session['screen_width']} × {session['screen_height']}"],
        ["Viewport", f"{session.get('viewport_width', 'not recorded')} × {session.get('viewport_height', 'not recorded')}"],
        ["Assessment duration", f"{session['duration_minutes']} minutes" if session.get("duration_minutes") else "not recorded"],
    ]
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer"><title>PROCTORING-LAB report {h(session["id"])}</title>
<style>
body{{font:15px/1.5 system-ui,Segoe UI,sans-serif;background:#f3f6fa;color:#182839;margin:0}}
main{{max-width:1160px;margin:0 auto;padding:28px 20px 60px}}
header{{background:#173b63;color:#fff;padding:24px;border-radius:10px}}
h1{{margin:0;font-size:26px}}h2{{margin:0 0 12px;font-size:19px}}p{{margin:8px 0}}
section{{background:#fff;border:1px solid #d8e2eb;border-radius:10px;padding:20px;margin-top:16px;overflow:auto}}
.muted{{color:#4d6275}}header .muted{{color:#dbe7f3}}.cards{{display:flex;flex-wrap:wrap;gap:10px}}
.card{{background:#eaf2fb;border-radius:7px;padding:11px 15px;min-width:142px}}
.card strong{{display:block;font-size:23px}}
table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;padding:8px 10px;border-bottom:1px solid #e2eaf2;vertical-align:top}}
th{{font-weight:650}}.wide{{min-width:800px}}.track{{height:37px;margin:24px 8px 5px;position:relative;border-top:3px solid #7990a5}}
.dot{{position:absolute;top:-8px;width:12px;height:12px;border-radius:50%;border:2px solid white;box-shadow:0 0 0 1px #345;transform:translateX(-50%)}}
.badge{{font-size:11px;font-weight:700;letter-spacing:.03em;display:inline-block;border-radius:4px;padding:3px 6px;background:#e8eef1}}
.focus{{background:#4467a4;color:white}}.visibility{{background:#9d4868;color:white}}
.fullscreen{{background:#6954a0;color:white}}.clipboard{{background:#a26a23;color:white}}
.heartbeat{{background:#147475;color:white}}.marker{{background:#aa4635;color:white}}
.network{{background:#aa6825;color:white}}.editor{{background:#596974;color:white}}
.submission{{background:#3e738e;color:white}}.session{{background:#3e5666;color:white}}
.other{{background:#64727e;color:white}}svg{{width:100%;height:auto;max-height:300px}}
svg text{{fill:#435669}}.hb-normal{{fill:#147475}}.hb-warning{{fill:#a77718}}.hb-large_gap{{fill:#b2413b}}
.state-visible,.state-focused,.state-active{{fill:#287d74}}
.state-hidden,.state-unfocused,.state-inactive{{fill:#b3524c}}
.state-unknown{{fill:#bfcad3}}.empty{{font-style:italic;color:#667887}}
.note{{border-left:4px solid #6d879e;padding-left:12px}}
@media print{{body{{background:white}}section{{break-inside:avoid}}}}
</style></head><body><main>
<header><h1>PROCTORING-LAB · Session report</h1><p class="muted">Local browser-signal experiment · {h(session["id"])}</p></header>
<section><h2>Executive summary</h2>
<p>Recorded {summary["event_count"]} browser events, {summary["heartbeat_count"]} heartbeats and {summary["marker_count"]} manual markers over {_duration(summary["total_duration_ms"])}. Marker correlations cover only ±3 seconds around each marker.</p>
<div class="cards"><div class="card"><strong>{summary["focus_loss_count"]}</strong>Focus losses</div>
<div class="card"><strong>{summary["visibility_hidden_count"]}</strong>Hidden transitions</div>
<div class="card"><strong>{summary["fullscreen_exit_count"]}</strong>Fullscreen exits</div>
<div class="card"><strong>{summary["paste_count"]}</strong>Paste events</div>
<div class="card"><strong>{summary["submission_count"]}</strong>Submissions</div></div></section>
<section><h2>Environment</h2>{_table(["Field", "Value"], env_rows, "No environment data recorded.")}</section>
<section><h2>Event counts</h2>{_table(["Event", "Count"], event_rows, "No browser events recorded.")}</section>
<section><h2>Focus, visibility and fullscreen statistics</h2>
<p>Focus losses: {summary["focus_loss_count"]} · Hidden transitions: {summary["visibility_hidden_count"]} · Fullscreen exits: {summary["fullscreen_exit_count"]} · Fullscreen request errors: {summary["fullscreen_error_count"]}.</p>
<p class="muted">Bands are reconstructed from received state snapshots. Gray means no snapshot was available yet. Receive time may differ from the action time.</p>
{_state_bands(data, start, end)}</section>
<section><h2>Visual event timeline</h2><p class="muted">Dots and rows use server receipt time; event rows also show browser performance time and sequence when available.</p>
<div class="track">{''.join(dots)}</div><p>Start {h(_time(session["started_at"]))} · End {h(_time(session["ended_at"])) if session["ended_at"] else "active"}</p>
<div class="wide"><table><thead><tr><th>UTC time</th><th>Category</th><th>Observation</th></tr></thead><tbody>{timeline_body}</tbody></table></div></section>
<section><h2>Heartbeat intervals</h2>
<p>Average: {f"{avg:.1f} ms" if avg is not None else "not available"} · Longest: {f"{longest:.1f} ms" if longest is not None else "not available"}.</p>
<p class="muted">Normal &lt;4,000 ms; warning 4,000–8,000 ms; large gap &gt;8,000 ms. Delays can have several causes and do not establish intent.</p>
{_heartbeat_chart(data["heartbeat_points"])}</section>
<section><h2>Network, clipboard and editor changes</h2>
<p>Network online/offline events: {summary["network_change_count"]} (offline: {summary["network_offline_count"]}); fetch failures: {summary["fetch_failure_count"]}; paste events: {summary["paste_count"]}.</p>
<p>Editor changes: {summary["editor_change_count"]}; small: {distribution["SMALL_CHANGE"]}; medium: {distribution["MEDIUM_CHANGE"]}; large: {distribution["LARGE_CHANGE"]}. Change size is descriptive and does not imply misconduct.</p></section>
<section><h2>Submission history</h2>
<p class="muted">Results are local mock judge statuses; no submitted code is stored in this report.</p>
{_table(["#", "UTC time", "Question", "Language", "Action", "Code length", "Mock result"], submissions, "No runs or submissions recorded.")}</section>
<section><h2>Marker correlation</h2><p class="muted">Signals received within ±3 seconds of each manually added marker. The interval column includes normal heartbeats too.</p>
{_table(["UTC time", "Marker", "Signals", "Largest nearby interval"], correlations, "No markers recorded.")}</section>
<section><h2>Measured detection matrix</h2><p class="muted">One row per marker in this session. “Not observed” applies only to that marker's ±3-second window.</p>
<div class="wide">{_table(["Action", "Window blur", "Document hidden", "Fullscreen exit", "Heartbeat interval", "Network change", "Browser observed"], matrix, "No measured marker actions yet.")}</div></section>
<section><h2>Limitations</h2><p class="note">{h(data["limitations"])}</p>
<p>Browser JavaScript cannot directly observe arbitrary host OS activity. Browser, guest OS, VM, timer and power behavior can vary. A marker records when it was added, which may be later than the action described. A signal near a marker indicates temporal proximity, not causation.</p></section>
</main></body></html>'''
