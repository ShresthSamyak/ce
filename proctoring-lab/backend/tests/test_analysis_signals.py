"""Guard the distinction between observed signals and inferred activity."""

from backend.analysis import _marker_observation


def test_fetch_failure_does_not_claim_network_change() -> None:
    when = "2026-01-01T00:00:05+00:00"
    marker = {"id": "marker-1", "label": "Network test", "timestamp_server": when}
    event = {
        "event_type": "fetch_failure",
        "timestamp_server": when,
        "timestamp_client": when,
        "sequence": 1,
        "performance_ms": 5000.125,
        "visibility_state": "visible",
        "document_has_focus": True,
        "fullscreen": True,
        "metadata": {"operation": "heartbeat"},
    }
    correlation, matrix = _marker_observation(marker, [event], [])

    assert correlation["observed"]["fetch_failure"] is True
    assert correlation["observed"]["network_change"] is False
    assert matrix["network_change"] == "not observed"
    assert matrix["fetch_failure"] == "observed"


def test_normal_heartbeat_is_reported_without_inventing_transition() -> None:
    when = "2026-01-01T00:00:05+00:00"
    marker = {"id": "marker-2", "label": "Host action", "timestamp_server": when}
    heartbeat = {
        "timestamp_server": when, "delta_ms": 2004.0,
        "gap_level": "NORMAL", "visibility_state": "visible",
        "has_focus": True, "fullscreen": True,
    }
    correlation, matrix = _marker_observation(marker, [], [heartbeat])

    assert correlation["observed"]["heartbeat_gap_ms"] == 2004.0
    assert correlation["observed"]["browser_state_snapshot"] == {
        "visibility_state": "visible", "has_focus": True, "fullscreen": True,
    }
    assert correlation["signals"] == []
    assert matrix["browser_observable"] == "no listed transition or anomaly observed in ±3 s"
