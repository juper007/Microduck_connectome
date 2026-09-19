"""Strict, deterministic P6-06 fault evidence records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import math
from pathlib import Path


SCHEMA_VERSION = "p6-06-fault-matrix-v1"
REQUIRED_FAULTS = (
    "camera_dropout", "tof_dropout", "stale_perception", "invalid_perception",
    "compositor_invalid", "runtime_unhealthy", "neural_freeze",
    "malformed_neural", "neural_unavailable", "decoder_crash", "decoder_stale",
    "ipc_disconnect", "connection_refused", "read_timeout", "write_failure",
    "socket_close", "robotd_restart", "simulator_restart",
)
_TIMES = (
    "injected_at_ns", "detected_at_ns", "safe_command_at_ns",
    "motion_stopped_at_ns", "recovery_at_ns",
)


class FaultEvidenceError(ValueError):
    """Fault evidence is incomplete, non-monotonic, or unsafe."""


def validate_fault_record(value: Mapping) -> dict:
    required = {
        "fault", *_TIMES, "detection_latency_ms", "safe_command_latency_ms",
        "motion_stop_latency_ms", "recovery_latency_ms", "safe_state_reached",
        "old_command_replayed", "stop_transport", "state_evidence", "result",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise FaultEvidenceError("fault record fields mismatch")
    if value["fault"] not in REQUIRED_FAULTS:
        raise FaultEvidenceError("unknown fault")
    times = [value[name] for name in _TIMES]
    if any(type(item) is not int or item < 0 for item in times):
        raise FaultEvidenceError("fault timestamps must be non-negative integers")
    if times != sorted(times):
        raise FaultEvidenceError("fault timestamps must be monotonic")
    expected = (
        (times[1] - times[0]) / 1e6,
        (times[2] - times[0]) / 1e6,
        (times[3] - times[0]) / 1e6,
        (times[4] - times[0]) / 1e6,
    )
    for name, actual, target in zip(
        ("detection_latency_ms", "safe_command_latency_ms", "motion_stop_latency_ms", "recovery_latency_ms"),
        (value[name] for name in ("detection_latency_ms", "safe_command_latency_ms", "motion_stop_latency_ms", "recovery_latency_ms")),
        expected,
    ):
        if isinstance(actual, bool) or not isinstance(actual, (int, float)):
            raise FaultEvidenceError(f"{name} must be numeric")
        if not math.isfinite(float(actual)) or abs(float(actual) - target) > 1e-6:
            raise FaultEvidenceError(f"{name} does not match timestamps")
    if value["safe_state_reached"] is not True or value["old_command_replayed"] is not False:
        raise FaultEvidenceError("record does not prove safe state and no replay")
    if value["stop_transport"] != "robot_stop" or value["result"] != "PASS":
        raise FaultEvidenceError("record violates frozen transport or PASS contract")
    state = value["state_evidence"]
    if not isinstance(state, Mapping) or set(state) != {
        "requested", "applied", "heading_before_rad", "heading_after_rad", "heading_delta_rad"
    }:
        raise FaultEvidenceError("state evidence fields mismatch")
    for name in ("requested", "applied"):
        vector = state[name]
        if not isinstance(vector, Sequence) or isinstance(vector, (str, bytes)) or len(vector) != 3:
            raise FaultEvidenceError(f"state {name} must be a length-three vector")
        if any(isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(float(item)) for item in vector):
            raise FaultEvidenceError(f"state {name} must be finite")
        if any(abs(float(item)) > 1e-6 for item in vector):
            raise FaultEvidenceError(f"state {name} does not prove rest")
    for name in ("heading_before_rad", "heading_after_rad", "heading_delta_rad"):
        item = state[name]
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(float(item)):
            raise FaultEvidenceError(f"state {name} must be finite")
    if abs(abs(float(state["heading_after_rad"] - state["heading_before_rad"])) - float(state["heading_delta_rad"])) > 1e-9:
        raise FaultEvidenceError("heading delta mismatch")
    return json.loads(json.dumps(value, allow_nan=False))


def make_fault_record(*, fault: str, injected_at_ns: int, detected_at_ns: int,
                      safe_command_at_ns: int, motion_stopped_at_ns: int,
                      recovery_at_ns: int, state_evidence: Mapping) -> dict:
    record = {
        "fault": fault,
        "injected_at_ns": injected_at_ns,
        "detected_at_ns": detected_at_ns,
        "safe_command_at_ns": safe_command_at_ns,
        "motion_stopped_at_ns": motion_stopped_at_ns,
        "recovery_at_ns": recovery_at_ns,
        "detection_latency_ms": (detected_at_ns - injected_at_ns) / 1e6,
        "safe_command_latency_ms": (safe_command_at_ns - injected_at_ns) / 1e6,
        "motion_stop_latency_ms": (motion_stopped_at_ns - injected_at_ns) / 1e6,
        "recovery_latency_ms": (recovery_at_ns - injected_at_ns) / 1e6,
        "safe_state_reached": True,
        "old_command_replayed": False,
        "stop_transport": "robot_stop",
        "state_evidence": dict(state_evidence),
        "result": "PASS",
    }
    return validate_fault_record(record)


def build_fault_matrix(*, execution_target: str, source_head: str, identities: Mapping,
                       records: Sequence[Mapping], artifact: Mapping) -> dict:
    checked = [validate_fault_record(record) for record in records]
    names = [record["fault"] for record in checked]
    if names != list(REQUIRED_FAULTS):
        raise FaultEvidenceError("fault matrix must contain every required fault exactly once in canonical order")
    if execution_target != "Thor":
        raise FaultEvidenceError("runtime fault authority must be Thor")
    if not isinstance(source_head, str) or len(source_head) != 40:
        raise FaultEvidenceError("source_head must be a full Git SHA")
    result = {
        "schema_version": SCHEMA_VERSION,
        "execution_target": execution_target,
        "source_head": source_head,
        "identities": dict(identities),
        "fault_count": len(checked),
        "worst_detection_latency_ms": max(record["detection_latency_ms"] for record in checked),
        "worst_motion_stop_latency_ms": max(record["motion_stop_latency_ms"] for record in checked),
        "records": checked,
        "raw_artifact": dict(artifact),
        "result": "PASS",
    }
    return json.loads(json.dumps(result, sort_keys=True, allow_nan=False))


def write_fault_matrix(path: str | Path, value: Mapping) -> None:
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")

