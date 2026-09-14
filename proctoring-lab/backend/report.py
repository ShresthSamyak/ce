"""Standalone, escaped HTML report for a single measured session."""

from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any


def h(value: Any) -> str:
    return escape(str(value), quote=True)


def _time(value: str) -> str:
    return datetime.fromisoformat(value).strftime("%H:%M:%S.%f")[:-3]


def _duration(ms: int) -> str:
    total = ms // 1000
    return f"{total // 60:02d}:{total % 60:02d}"


def _category(item: dict) -> str:
    if item["kind"] != "EVENT":
        return item["kind"].lower()
    event_type = item["event_type"]
    if event_type in {"focus", "blur"}:
        return "focus"
    if event_type == "visibilitychange":
        return "visibility"
    if event_type == "fullscreenchange":
        return "fullscreen"
    if event_type in {"copy", "paste", "cut"}:
        return "clipboard"
    return "other"


def _description(item: dict) -> str:
    if item["kind"] == "MARKER":
        return "Marker: " + item["label"]
    if item["kind"] == "HEARTBEAT":
        interval = item["delta_ms"]
        return f"Heartbeat #{item['sequence']}" + (f" · {interval:.0f} ms · {item['gap_level']}" if interval is not None else " · first")
    if item["kind"] == "SESSION":
        return "Session " + item["event_type"]
    if item["event_type"] == "visibilitychange":
        return "Visibility: " + item["visibility_state"]
    if item["event_type"] == "fullscreenchange":
        return "Fullscreen: " + ("entered" if item["fullscreen"] else "exited")
    if item["event_type"] in {"copy", "paste", "cut"}:
        return f"{item['event_type'].title()} · {item['metadata'].get('character_count', 0)} characters"
    return item["event_type"]


def _heartbeat_chart(points: list[dict]) -> str:
    measured = [point for point in points if point["delta_ms"] is not None]
    if not measured:
        return '<p class="empty">At least two heartbeats are needed to plot intervals.</p>'
    values = [float(point["delta_ms"]) for point in measured]
    max_y = max(10000.0, max(values) * 1.12)
    width, height = 800, 230
    left, right, top, bottom = 58, 20, 18, 36
    plot_width = width - left - right
    plot_height = height - top - bottom
    first_time = datetime.fromisoformat(measured[0]["timestamp_server"])
    times = [(datetime.fromisoformat(point["timestamp_server"]) - first_time).total_seconds() for point in measured]
    time_span = max(1.0, times[-1])
    x = lambda i: left + (times[i] / time_span) * plot_width
    y = lambda value: top + plot_height - value / max_y * plot_height
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Heartbeat interval in milliseconds over time">']
    for level, label in ((4000, "4 s"), (8000, "8 s")):
        yy = y(level)
        parts.append(f'<line x1="{left}" x2="{width-right}" y1="{yy:.1f}" y2="{yy:.1f}" stroke="#adb9c7" stroke-dasharray="5 4"/>')
        parts.append(f'<text x="4" y="{yy+4:.1f}" fill="#425466" font-size="12">{label}</text>')
    parts.append(f'<line x1="{left}" x2="{width-right}" y1="{y(0):.1f}" y2="{y(0):.1f}" stroke="#425466"/>')
    for i, point in enumerate(measured):
        value = float(point["delta_ms"])
        color = "#ab392d" if value > 8000 else "#9a640c" if value >= 4000 else "#176d6a"
        xx, yy = x(i), y(value)
        parts.append(f'<circle cx="{xx:.1f}" cy="{yy:.1f}" r="4" fill="{color}"><title>{h(_time(point["timestamp_server"]))}: {value:.1f} ms ({h(point["gap_level"])})</title></circle>')
    parts.append(f'<text x="{left}" y="{height-7}" fill="#425466" font-size="12">{h(_time(measured[0]["timestamp_server"]))}</text>')
    parts.append(f'<text x="{width-right}" y="{height-7}" text-anchor="end" fill="#425466" font-size="12">{h(_time(measured[-1]["timestamp_server"]))}</text>')
    parts.append('</svg>')
    return "".join(parts)


def render_report(data: dict) -> str:
    """Render data as an independent file with no external network assets."""
    session, summary = data["session"], data["summary"]
    start = datetime.fromisoformat(session["started_at"])
    end = datetime.fromisoformat(session["ended_at"]) if session["ended_at"] else None
    duration_ms = summary["total_duration_ms"]
    end_time = end or datetime.now(start.tzinfo)
    span_ms = max(1, (end_time - start).total_seconds() * 1000)
    dots = []
    rows = []
    for item in data["timeline"]:
        category = _category(item)
        description = _description(item)
        timestamp = item["timestamp_server"]
        offset = max(0, min(100, (datetime.fromisoformat(timestamp) - start).total_seconds() * 100000 / span_ms))
        dots.append(f'<span class="dot {h(category)}" style="left:{offset:.2f}%" title="{h(_time(timestamp))} {h(description)}"></span>')
        rows.append(f'<tr><td>{h(_time(timestamp))}</td><td><span class="badge {h(category)}">{h(category.upper())}</span></td><td>{h(description)}</td></tr>')
    event_rows = "".join(f'<tr><th>{h(name)}</th><td>{count}</td></tr>' for name, count in data["event_counts"].items()) or '<tr><td colspan="2">No browser events recorded.</td></tr>'
    correlation_rows = []
    for correlation in data["correlations"]:
        marker = correlation["marker"]
        signals = ", ".join(signal["event_type"] + (" (" + signal["visibility_state"] + ")" if signal["event_type"] == "visibilitychange" else "") for signal in correlation["signals"])
        correlation_rows.append(f'<tr><td>{h(_time(marker["timestamp_server"]))}</td><td>{h(marker["label"])}</td><td>{h(signals or "No listed browser signal observed in ±3 s")}</td></tr>')
    matrix_rows = []
    for row in data["detection_matrix"]:
        matrix_rows.append("<tr>" + "".join(f"<td>{h(row[key])}</td>" for key in ("action", "visibilitychange", "blur", "fullscreenchange", "heartbeat_anomaly", "clipboard_signal", "browser_observable")) + "</tr>")
    avg = summary["average_heartbeat_interval_ms"]
    longest = summary["longest_heartbeat_gap_ms"]
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>PROCTORING-LAB report {h(session["id"])}</title>
<style>
body{{font:15px/1.5 system-ui,Segoe UI,sans-serif;background:#f3f6f8;color:#182634;margin:0}}
main{{max-width:1100px;margin:0 auto;padding:32px 20px 60px}}
header{{background:#17354a;color:white;padding:24px;border-radius:12px}}h1{{margin:0;font-size:26px}}h2{{margin:0 0 14px;font-size:19px}}p{{margin:8px 0}}
section{{background:white;border:1px solid #dbe3e8;border-radius:12px;padding:22px;margin-top:18px;overflow:auto}}
.muted{{color:#4d6170}}header .muted{{color:#d5e1e9}}.cards{{display:flex;flex-wrap:wrap;gap:12px}}.card{{background:#eef5f7;border-radius:8px;padding:12px 16px;min-width:140px}}.card strong{{display:block;font-size:22px}}
table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;padding:8px 10px;border-bottom:1px solid #e3e9ee;vertical-align:top}}th{{font-weight:650}}.matrix{{font-size:13px;white-space:nowrap}}
.track{{height:42px;margin:24px 8px 10px;position:relative;border-top:3px solid #73899b}}.dot{{position:absolute;top:-8px;width:12px;height:12px;border-radius:50%;border:2px solid white;box-shadow:0 0 0 1px #345;transform:translateX(-50%)}}
.badge{{font-size:11px;font-weight:700;letter-spacing:.04em;display:inline-block;border-radius:4px;padding:3px 6px;background:#e8eef1}}
.focus{{background:#4d6da8;color:white}}.visibility{{background:#a14a67;color:white}}.fullscreen{{background:#6856a0;color:white}}.clipboard{{background:#a46d24;color:white}}.heartbeat{{background:#176d6a;color:white}}.marker{{background:#a94334;color:white}}.session{{background:#3f5664;color:white}}.other{{background:#64727e;color:white}}
svg{{width:100%;height:auto;max-height:300px}}.empty{{font-style:italic;color:#667887}}.note{{border-left:4px solid #637e92;padding-left:12px}}
</style></head><body><main>
<header><h1>PROCTORING-LAB · Session report</h1><p class="muted">Local browser-signal experiment · {h(session["id"])}</p></header>
<section><h2>Executive summary</h2><p>Measured {summary["event_count"]} browser events and {summary["heartbeat_count"]} heartbeats over {_duration(duration_ms)}. {summary["marker_count"]} manual marker(s) were recorded. Marker observations refer only to the ±3-second window around each marker.</p>
<div class="cards"><div class="card"><strong>{summary["focus_loss_count"]}</strong>Focus losses</div><div class="card"><strong>{summary["visibility_hidden_count"]}</strong>Hidden transitions</div><div class="card"><strong>{summary["paste_count"]}</strong>Paste events</div><div class="card"><strong>{summary["marker_count"]}</strong>Markers</div></div></section>
<section><h2>Environment</h2><table><tbody><tr><th>Session start (UTC)</th><td>{h(session["started_at"])}</td></tr><tr><th>Session end (UTC)</th><td>{h(session["ended_at"] or "Still active")}</td></tr><tr><th>Platform reported by browser</th><td>{h(session["platform"])}</td></tr><tr><th>User agent</th><td>{h(session["user_agent"])}</td></tr><tr><th>Screen</th><td>{session["screen_width"]} × {session["screen_height"]}</td></tr></tbody></table></section>
<section><h2>Event counts</h2><table><tbody>{event_rows}</tbody></table></section>
<section><h2>Visual timeline</h2><p class="muted">Dots show server receipt time. Overlapping observations may share a position.</p><div class="track">{''.join(dots)}</div><p>Start {h(_time(session["started_at"]))} · End {h(_time(session["ended_at"])) if session["ended_at"] else "active"}</p><table><thead><tr><th>UTC time</th><th>Category</th><th>Observation</th></tr></thead><tbody>{''.join(rows)}</tbody></table></section>
<section><h2>Heartbeat intervals</h2><p>Average: {f'{avg:.1f} ms' if avg is not None else 'not available'} · Longest: {f'{longest:.1f} ms' if longest is not None else 'not available'}.</p><p class="muted">Normal &lt;4 s; warning 4–8 s; large gap &gt;8 s. Gaps may have many causes and do not establish intent.</p>{_heartbeat_chart(data["heartbeat_points"])}</section>
<section><h2>Marker correlation</h2><p class="muted">Signals received within ±3 seconds of each manual marker. Add markers close to actions for useful correlation.</p><table><thead><tr><th>UTC time</th><th>Marker</th><th>Observed signals</th></tr></thead><tbody>{''.join(correlation_rows) or '<tr><td colspan="3">No markers recorded.</td></tr>'}</tbody></table></section>
<section><h2>Detection matrix</h2><p class="muted">Rows are created only from markers in this session. “Not observed” describes this measurement window only.</p><table class="matrix"><thead><tr><th>Action</th><th>Visibility</th><th>Blur</th><th>Fullscreen</th><th>Heartbeat anomaly</th><th>Clipboard</th><th>Browser observable?</th></tr></thead><tbody>{''.join(matrix_rows) or '<tr><td colspan="7">No measured marker actions yet.</td></tr>'}</tbody></table></section>
<section><h2>Limitations</h2><p class="note">{h(data["limitations"])}</p><p>Browser JavaScript does not measure arbitrary host operating system activity. Focus, visibility, and timer behavior may differ between operating systems, browser versions, VM configurations, and power states. Marker timestamps reflect when the marker was added, which may be after the described action.</p></section>
</main></body></html>'''
