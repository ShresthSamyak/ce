# PROCTORING-LAB

**A local-only, educational browser telemetry experiment.** The included page is a generic mock coding assessment about summing integers. It records what its own JavaScript page can observe while you change tabs, focus, fullscreen state, clipboard actions, or the surrounding desktop/VM environment. It does not connect to a coding platform or a real assessment.

The page displays **PROCTORING SIMULATION — LOCAL TEST ENVIRONMENT**. Run and Submit are simulation controls, not a remote judge. This project does not grade code.

> Do not use this project to interfere with or evade monitoring on an actual examination platform. Conduct experiments only against the included local simulation.

## Threat model and measurement boundary

The observer is JavaScript running in **our own page**. It can receive browser events and send them to the local FastAPI server. The experiment can compare those observations with actions you intentionally take and label. It cannot independently establish every action that occurred elsewhere on the computer.

```text
HOST OS
   ↓
VMware application
   ↓
GUEST OS
   ↓
Guest browser
   ↓
JavaScript assessment page
```

JavaScript inside a guest browser normally receives browser/guest-level signals. It does not automatically receive arbitrary host-OS state. Actual behavior can vary with the browser, guest and host operating systems, VM configuration, power management, and whether a window is minimized or merely unfocused. **Measure each configuration; do not treat one result as universal.**

The page records `visibilitychange`, window `blur`/`focus`, `fullscreenchange`, `beforeunload`, `pagehide`/`pageshow`, `copy`/`paste`/`cut`, `contextmenu`, `keydown`, and `pointerleave`/`pointerenter`. Keyboard records contain only categories and modifier flags, never typed characters. Clipboard records contain only the action and a character count where the browser exposes one, never clipboard content. A two-second heartbeat captures visibility, focus, and fullscreen snapshots and allows interval analysis. Browser throttling, suspension, server delay, and scheduling can all affect those intervals. A gap does **not** prove misconduct.

The lab does not use a webcam, microphone, screenshots, global keyboard hooks, clipboard readers, process inspection, Safe Exam Browser integration, third-party scripts, or telemetry spoofing. Its application API and page are bound to `127.0.0.1`; runtime requests stay on the same local server. Package installation during setup may require access to a package index.

## Requirements and installation

- Python 3.12, with `venv` and `pip`.
- Windows 11, or Ubuntu 24.04 with a desktop session. For the optional Tkinter overlay on Ubuntu, install the distribution's `python3.12-tk` package if Tkinter is unavailable.
- A modern Chrome, Edge, or Firefox browser.

Run the server **inside the operating system being measured**. `127.0.0.1` in a guest refers to that guest, not the Windows host. To compare a Windows host, a Windows guest, and an Ubuntu guest, install or copy the project into each one and run a separate local session in each.

Windows, from the `proctoring-lab` directory:

```bat
setup.bat
run.bat
```

`setup.bat` creates `.venv` using the Windows `py -3.12` launcher when available, or a Python 3.12 `python` command on PATH.

Ubuntu, from the `proctoring-lab` directory:

```sh
chmod +x setup.sh run.sh
./setup.sh
./run.sh
```

Open **http://127.0.0.1:8000/** on the same OS. Stop the server with Ctrl+C. No account or external service is required at runtime.

## Using the simulation

1. Open the assessment page and note its session ID and environment information.
2. Select an experiment template to display instructions. Click **START TEST**.
3. Add a marker immediately before an intentional action whenever possible, for example `About to switch browser tab`. Perform the action, return, and add a second marker such as `Returned from browser tab`.
4. Let the session run long enough for several heartbeats. Click **END TEST** to freeze collection and view the summary, timeline, correlation analysis, and report link.
5. Repeat in each environment and browser. Use a fresh session for a clean comparison.

Available templates cover tab switching, Alt-Tab to another application, browser minimize, entering and exiting fullscreen, copy/paste in the editor, the benign overlay, VMware host minimize, guest Alt-Tab, and switching host applications while the guest remains running. These are instructions only; the app never automates desktop or host actions.

The marker correlation window is **±3 seconds around the timestamp when you click the marker**. If you cannot click inside a minimized or unfocused guest, a marker placed after returning can only be correlated with the return. It cannot retroactively timestamp a host action. Use paired before/after markers and record the approximate host action time in your notes. Browser and server clocks also may differ, so interpret near-boundary correlations cautiously.

### VMware experiment G: host minimizes VMware

1. Inside the guest OS, start the local server and open the mock assessment page in the guest browser.
2. Start a session. Keep the guest browser visible. Add a marker such as `About to minimize VMware from host` immediately before interacting with the host.
3. From the **host OS**, minimize the VMware application. Do not automate or modify VMware or the browser.
4. Wait about 10 seconds using a host clock. Restore VMware.
5. In the guest page, add `VMware restored after host minimize` and end the test after a few more heartbeats.
6. Inspect the actual visibility/focus events and heartbeat intervals spanning the before/after markers. If no visibility event occurred, report exactly that: **“During this experiment, the browser did not observe a visibility change.”** Do not infer an evasion or a general rule.

For experiment I, switch to a host application while the guest continues running, then return and mark both ends. For experiment H, Alt-Tab **inside the guest**. Record which OS received the key combination; that distinction matters.

### Optional desktop overlay

Run this on the desktop under test, in a separate terminal:

```sh
python overlay/benign_overlay.py
```

On Windows with the project environment, use `.venv\Scripts\python.exe overlay\benign_overlay.py`; on Ubuntu use `.venv/bin/python overlay/benign_overlay.py`. The control window provides **Show**, **Hide**, **Always on top**, and position/size fields. The overlay itself is a normal decorated window that can be moved and resized. Clicking it may change browser focus; merely displaying it may not. Observe and record what actually happens. The utility has no global hooks, click-through mode, browser connection, screenshots, or clipboard access.

## Data and reports

The FastAPI API stores sessions, browser events, heartbeats, and manual markers in a local SQLite database under `data/`. Each browser event carries a UUID, session ID, client and server timestamps, visibility/focus/fullscreen snapshots, screen and viewport dimensions, user agent, and event-specific safe metadata. The report contains event counts, a chronological timeline, heartbeat statistics and graph, marker correlations, a measured detection matrix, and limitations. Rows without measured data must remain unknown or unreported; the project does not prefill conclusions about VMware behavior.

The server saves generated HTML reports as `reports/session_<uuid>.html`. You can request a report at `http://127.0.0.1:8000/api/session/<uuid>/report` or regenerate a local copy while the server is running:

```sh
python scripts/generate_report.py <session-uuid>
```

The helper accepts only a loopback HTTP API URL. Reports and the SQLite database are excluded from Git; they can still contain environment details and manual labels, so handle local files accordingly.

Key API routes:

| Method | Route | Purpose |
| --- | --- | --- |
| `POST` | `/api/session/start` | Create a session |
| `POST` | `/api/session/end` | End a session |
| `POST` | `/api/events` | Save a browser event |
| `POST` | `/api/heartbeat` | Save a snapshot and interval |
| `POST` | `/api/marker` | Save a manual label |
| `GET` | `/api/session/{id}` | Retrieve a session |
| `GET` | `/api/session/{id}/timeline` | Chronological records |
| `GET` | `/api/session/{id}/analysis` | Summary and marker correlation |
| `GET` | `/api/session/{id}/report` | HTML report |

## Interpreting the results

Visibility, focus, and fullscreen are different signals. A browser can lose focus while its document remains visible. A host action may alter guest timing without producing an explicit browser event, or may produce an event in a particular setup. The heartbeat labels are based on elapsed server receipt time: **NORMAL** below 4 seconds, **WARNING** from 4 through 8 seconds, and **LARGE GAP** above 8 seconds. Network loopback latency, scheduling, tab throttling, VM suspension, and machine load can contribute. A missing browser signal says only what this page did not record during that run.

The detection matrix should be populated from your measured sessions. Use the following note sheet alongside the generated reports:

| Host / guest | Browser and version | Action | Session UUID | Marker times | Visibility | Focus/blur | Fullscreen | Largest heartbeat gap | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | ---: | --- |
| Windows 11 host / none | Chrome / Edge / Firefox | Tab switch | | | | | | | |
| Windows 11 host / Windows 11 guest | Chrome / Edge / Firefox | Host VMware minimize | | | | | | | |
| Windows 11 host / Windows 11 guest | Chrome / Edge / Firefox | Guest Alt-Tab | | | | | | | |
| Windows 11 host / Ubuntu 24.04 guest | Chrome / Edge / Firefox | Host VMware minimize | | | | | | | |
| Windows 11 host / Ubuntu 24.04 guest | Chrome / Edge / Firefox | Guest Alt-Tab | | | | | | | |

Test each desired browser separately in the Windows 11 guest and Ubuntu 24.04 guest. Record VM version/settings, display mode, whether VMware itself was minimized or only unfocused, and clock differences if relevant. For the overlay test, note whether it appeared over the guest browser or only on the host desktop.

## Validation

After setup, run the automated tests from the project root. On Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

On Ubuntu:

```sh
.venv/bin/python -m pytest -q
```

The pytest configuration disables its cache and uses a fresh, project-local temporary directory for each run. This avoids access errors involving an existing `AppData\Local\Temp\pytest-of-...` or `.pytest_cache` directory on Windows. The temporary directory is removed when the run finishes. Then run the server and visit `/` to verify the page. Create a short test session, generate at least one event, wait for heartbeats, add a marker, end the test, and open its analysis and report endpoints. The tests exercise local API behavior; they cannot simulate a real host/guest focus transition or establish how a particular VMware installation behaves.

## Limitations and ethical use

This is a controlled measurement aid, not a proctoring product or an assessment bypass. JavaScript event delivery depends on the browser and OS. The page cannot observe arbitrary host processes, host windows, desktop overlays, or VM state unless those circumstances produce a browser-visible signal. Browser closure may prevent a final event from reaching the server. A full page reload creates a new idle client session; active-session recovery is not implemented. Manual markers are approximate. Heartbeat gaps are ambiguous. The mock editor has no real judge.

Use it only with systems and accounts you control. Do not inject it into third-party pages, disable monitoring, spoof or suppress signals, or use it during an actual examination. A report's language should remain observational: **“The browser did not observe a visibility change during this experiment,”** never **“this bypasses proctoring.”**
