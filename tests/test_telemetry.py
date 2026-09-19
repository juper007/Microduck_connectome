from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from microduck_connectome.control_contracts import make_behavior_intent
from microduck_connectome.telemetry import (
    EndToEndTelemetry,
    TelemetryError,
    build_run_identity,
    load_telemetry_config,
    telemetry_config_hashes,
)
from microduck_connectome.watchdog import ControllerWatchdog


ROOT = Path(__file__).resolve().parents[1]
SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_C = "c" * 40


def identity():
    return build_run_identity(
        ROOT,
        run_id="p6-05-test-run",
        project_commit=SHA_A,
        microduck_commit=SHA_B,
        microduck_rl_commit=SHA_C,
        graph_identity="graph-cache:test",
    )


def stages(ts=10, seq=1):
    pre = make_behavior_intent(timestamp_ns=ts, sequence=seq, vyaw=0.2)
    post = make_behavior_intent(timestamp_ns=ts, sequence=seq, vyaw=0.1)
    return {
        "camera_frame_id": seq,
        "tof_frame_id": seq,
        "perception_frame": {
            "timestamp_ns": ts,
            "frame_id": seq,
            "target_x": -1.0,
            "target_area": 0.5,
            "looming": 0.0,
            "proximity_left": 0.0,
            "proximity_center": 0.0,
            "proximity_right": 0.0,
            "confidence": 1.0,
            "valid": True,
        },
        "stimulus_channels": {
            "lc10a_left": 0.5, "lc10a_right": 0.0,
            "lplc2_left": 0.0, "lplc2_right": 0.0,
        },
        "male_cns": {"step": seq, "healthy": True, "spike_count": 2},
        "dn_readout": {
            "timestamp_ns": ts, "sequence": seq, "steering_left": 0.0,
            "steering_right": 0.4, "escape": 0.0, "runtime_healthy": True,
        },
        "pre_safety_intent": pre,
        "safety_result": {"intent": post, "clamp_applied": True, "reasons": ["vyaw_slew"]},
    }


def watched(ts=20, seq=2, stop=False):
    watchdog = ControllerWatchdog(ROOT / "config" / "watchdog_v1.json")
    if not stop:
        readout = stages(ts - 1, seq - 1)["dn_readout"]
        behavior = stages(ts - 1, seq - 1)["safety_result"]["intent"]
        assert watchdog.observe_neural(readout)
        assert watchdog.observe_behavior(behavior)
    return watchdog.tick(now_ns=ts, output_sequence=seq)


def state(ts=20):
    return {
        "sample_timestamp_ns": ts,
        "robot_t_ns": 123,
        "policy": "stand",
        "requested_velocity": [0.0, 0.0, 0.1],
        "applied_velocity": [0.0, 0.0, 0.09],
        "heading_rad": 0.25,
        "velocity": [0.0, 0.0, 0.09],
    }


def logger():
    return EndToEndTelemetry(ROOT / "config" / "telemetry_v1.json", identity())


def append(log, *, ts=20, seq=2, trace=None, output=None, state_value=None, transport=None):
    actual_output = watched(ts, seq) if output is None else output
    return log.append(
        trial_id="trial-left",
        scenario="left",
        timestamp_ns=ts,
        sequence=seq,
        trace=stages(ts - 1, seq - 1) if trace is None else trace,
        watchdog_output=actual_output,
        robotd_transport_result=transport or ("robot_stop_refreshed" if actual_output["intent"]["stop"] else "move"),
        robotd_connected=True,
        robot_state=state(ts) if state_value is None else state_value,
    )


def test_config_and_all_required_hashes_are_pinned():
    config = load_telemetry_config(ROOT / "config" / "telemetry_v1.json")
    assert config["required_scenarios"] == ["neutral", "left", "right", "center", "stop"]
    assert set(telemetry_config_hashes(ROOT)) == {
        "sensory_mapping", "dn_readout", "steering", "escape", "safety",
        "watchdog", "motion_adapter", "scheduler", "integration",
    }


def test_complete_record_is_correlated_and_canonical():
    log = logger()
    record = append(log)
    assert record["camera_frame_id"] == 1
    assert record["dn_activity"]["steering_right"] == 0.4
    assert record["clamp_reasons"] == ["vyaw_slew"]
    assert record["robot_facing_command_type"] == "robot.move"
    assert record["robot_state"]["heading_rad"] == 0.25
    line = log.to_jsonl()
    assert line == json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"


def test_records_are_deep_detached():
    trace = stages()
    robot_state = state()
    log = logger()
    record = append(log, trace=trace, state_value=robot_state)
    trace["stimulus_channels"]["lc10a_left"] = 99
    robot_state["heading_rad"] = 99
    record["robot_state"]["heading_rad"] = 88
    saved = log.records()[0]
    assert saved["stimulus_channels"]["lc10a_left"] == 0.5
    assert saved["robot_state"]["heading_rad"] == 0.25


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_nonfinite_values_are_rejected(bad):
    robot_state = state()
    robot_state["heading_rad"] = bad
    with pytest.raises(TelemetryError, match="NaN/Inf|finite"):
        append(logger(), state_value=robot_state)


def test_secret_like_fields_are_rejected():
    robot_state = state()
    robot_state["api_token"] = "do-not-log"
    with pytest.raises(TelemetryError, match="secret-like"):
        append(logger(), state_value=robot_state)


@pytest.mark.parametrize("path", ["/home/user/private.log", r"C:\\Users\\user\\private.log"])
def test_absolute_machine_paths_are_rejected(path):
    robot_state = state()
    robot_state["artifact"] = path
    with pytest.raises(TelemetryError, match="absolute path"):
        append(logger(), state_value=robot_state)


def test_timestamp_and_sequence_are_strict():
    log = logger()
    append(log)
    with pytest.raises(TelemetryError, match="increase strictly"):
        append(log, ts=20, seq=3)
    with pytest.raises(TelemetryError, match="increase strictly"):
        append(log, ts=21, seq=2)


def test_stop_transport_is_explicit():
    output = watched(20, 2, stop=True)
    record = append(logger(), output=output)
    assert record["robot_facing_command_type"] == "robot.stop"
    assert record["robot_facing_stop"] is True
    assert record["robotd_transport_result"] == "robot_stop_refreshed"
    assert record["identities"]["stop_transport"] == "robot_stop"


def test_write_returns_artifact_summary(tmp_path):
    log = logger()
    append(log)
    summary = log.write(tmp_path / "trace.jsonl")
    assert summary["record_count"] == 1
    assert len(summary["sha256"]) == 64
    assert summary["start_timestamp_ns"] == summary["end_timestamp_ns"] == 20


def test_committed_thor_evidence_is_complete_and_correlated():
    evidence = json.loads(
        (ROOT / "docs" / "evidence" / "p6-05" / "telemetry-summary-v1.json").read_text(encoding="utf-8")
    )
    assert evidence["execution_target"] == "Thor"
    assert evidence["result"] == "PASS"
    assert evidence["record_count"] == 322
    assert evidence["post_command_state_count"] == evidence["record_count"]
    assert evidence["command_state_mismatch_count"] == 0
    assert evidence["strict_monotonic_timestamps"] is True
    assert evidence["strict_sequences"] is True
    assert evidence["telemetry_gap_count"] == 0
    assert evidence["nonfinite_count"] == 0
    assert set(evidence["scenario_record_counts"]) == {"neutral", "left", "right", "center", "stop"}
    assert all(count > 0 for count in evidence["scenario_record_counts"].values())
    assert evidence["command_counts"]["robot.stop"] >= 1
    assert evidence["identities"]["steering_yaw_sign"] == -1
    assert evidence["identities"]["stop_transport"] == "robot_stop"
    assert evidence["scheduler"]["scheduler_exceptions"] == 0
