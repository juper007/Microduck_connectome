"""Canonical end-to-end telemetry for the Phase-6 official simulator path."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import copy
import hashlib
import json
import math
from pathlib import Path, PurePosixPath, PureWindowsPath
import re


SCHEMA_VERSION = "p6-end-to-end-telemetry-v1"
_SCENARIOS = ("neutral", "left", "right", "center", "stop")
_CONFIG_FILES = {
    "sensory_mapping": "config/sensory_mapping_v1.json",
    "dn_readout": "config/dn_readout_v1.json",
    "steering": "config/steering_decoder_v1.json",
    "escape": "config/escape_decoder_v1.json",
    "safety": "config/safety_envelope_v1.json",
    "watchdog": "config/watchdog_v1.json",
    "motion_adapter": "config/motion_adapter_v1.json",
    "scheduler": "config/scheduler_v1.json",
    "integration": "config/telemetry_v1.json",
}
_SHA = re.compile(r"[0-9a-f]{64}")
_GIT_SHA = re.compile(r"[0-9a-f]{40}")
_SECRET_NAMES = re.compile(r"(?i)(password|passwd|secret|token|api[_-]?key|credential|private[_-]?key)")


class TelemetryError(ValueError):
    """A telemetry config, identity, or record violates P6-05."""


def sha256_file(path: str | Path) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError as error:
        raise TelemetryError("cannot hash required telemetry input") from error


def telemetry_config_hashes(root: str | Path) -> dict[str, str]:
    root = Path(root)
    return {name: sha256_file(root / relative) for name, relative in _CONFIG_FILES.items()}


def load_telemetry_config(path: str | Path) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise TelemetryError("cannot load telemetry config") from error
    required = {
        "schema_version", "format", "required_scenarios", "forbid_nonfinite",
        "forbid_sensitive_paths", "source", "scope",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise TelemetryError("telemetry config fields mismatch")
    if value["schema_version"] != "p6-telemetry-config-v1":
        raise TelemetryError("telemetry config schema mismatch")
    if value["format"] != "canonical-jsonl":
        raise TelemetryError("telemetry format must be canonical-jsonl")
    if value["required_scenarios"] != list(_SCENARIOS):
        raise TelemetryError("required scenario set/order mismatch")
    if value["forbid_nonfinite"] is not True or value["forbid_sensitive_paths"] is not True:
        raise TelemetryError("telemetry safety checks must remain enabled")
    if value["source"] != "male-cns-controller" or not isinstance(value["scope"], str):
        raise TelemetryError("telemetry source/scope mismatch")
    return dict(value)


def _canonical(value) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise TelemetryError("telemetry must be JSON-compatible and finite") from error


def _scan(value, path="record") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TelemetryError(f"{path} contains a non-string key")
            if _SECRET_NAMES.search(key):
                raise TelemetryError(f"{path} contains a secret-like field")
            _scan(item, f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _scan(item, f"{path}[{index}]")
    elif isinstance(value, float) and not math.isfinite(value):
        raise TelemetryError(f"{path} contains NaN/Inf")
    elif isinstance(value, str):
        # Artifact basenames and repository-relative paths are allowed; machine-
        # specific absolute paths are recorded only in compact evidence, never traces.
        if PureWindowsPath(value).is_absolute() or PurePosixPath(value).is_absolute():
            raise TelemetryError(f"{path} contains an absolute path")


def _intent(value, label: str) -> dict:
    required = {"timestamp_ns", "sequence", "vx", "vy", "vyaw", "stop", "confidence", "source"}
    if not isinstance(value, Mapping) or set(value) != required:
        raise TelemetryError(f"{label} intent fields mismatch")
    result = dict(value)
    if type(result["timestamp_ns"]) is not int or type(result["sequence"]) is not int:
        raise TelemetryError(f"{label} intent metadata must be integer")
    if type(result["stop"]) is not bool:
        raise TelemetryError(f"{label} stop must be bool")
    for name in ("vx", "vy", "vyaw", "confidence"):
        if isinstance(result[name], bool) or not isinstance(result[name], (int, float)) or not math.isfinite(float(result[name])):
            raise TelemetryError(f"{label}.{name} must be finite numeric")
        result[name] = float(result[name])
    return result


def build_run_identity(
    root: str | Path,
    *,
    run_id: str,
    project_commit: str,
    microduck_commit: str,
    microduck_rl_commit: str,
    graph_identity: str,
) -> dict:
    if not isinstance(run_id, str) or not run_id.strip():
        raise TelemetryError("run_id must be nonblank")
    for label, value in (
        ("project_commit", project_commit), ("microduck_commit", microduck_commit),
        ("microduck_rl_commit", microduck_rl_commit),
    ):
        if not isinstance(value, str) or _GIT_SHA.fullmatch(value) is None:
            raise TelemetryError(f"{label} must be a full lowercase Git SHA")
    if not isinstance(graph_identity, str) or not graph_identity.strip():
        raise TelemetryError("graph_identity must be nonblank")
    hashes = telemetry_config_hashes(root)
    return {
        "run_id": run_id,
        "project_commit": project_commit,
        "microduck_commit": microduck_commit,
        "microduck_rl_commit": microduck_rl_commit,
        "dataset_version": "male-cns:v1.0",
        "graph_identity": graph_identity,
        "config_hashes": hashes,
        "steering_yaw_sign": -1,
        "stop_transport": "robot_stop",
    }


class EndToEndTelemetry:
    """Validate, detach, and serialize correlated control records."""

    def __init__(self, config, identity: Mapping):
        self.config = load_telemetry_config(config) if isinstance(config, (str, Path)) else dict(config)
        if not isinstance(identity, Mapping):
            raise TelemetryError("identity must be a mapping")
        required_identity = {
            "run_id", "project_commit", "microduck_commit", "microduck_rl_commit",
            "dataset_version", "graph_identity", "config_hashes", "steering_yaw_sign",
            "stop_transport",
        }
        if set(identity) != required_identity:
            raise TelemetryError("run identity fields mismatch")
        if set(identity["config_hashes"]) != set(_CONFIG_FILES):
            raise TelemetryError("run identity config hashes mismatch")
        if any(_SHA.fullmatch(value) is None for value in identity["config_hashes"].values()):
            raise TelemetryError("config identities must be lowercase SHA256")
        if identity["steering_yaw_sign"] != -1 or identity["stop_transport"] != "robot_stop":
            raise TelemetryError("frozen P6-03 values changed")
        _scan(identity, "identity")
        self.identity = json.loads(_canonical(identity))
        self._records: list[dict] = []

    def append(
        self,
        *,
        trial_id: str,
        scenario: str,
        timestamp_ns: int,
        sequence: int,
        trace: Mapping,
        watchdog_output: Mapping,
        robotd_transport_result: str,
        robotd_connected: bool,
        robot_state: Mapping,
    ) -> dict:
        if not isinstance(trial_id, str) or not trial_id.strip():
            raise TelemetryError("trial_id must be nonblank")
        if scenario not in _SCENARIOS:
            raise TelemetryError("unknown P6-05 scenario")
        if type(timestamp_ns) is not int or timestamp_ns < 0 or type(sequence) is not int or sequence < 0:
            raise TelemetryError("record metadata must be non-negative integers")
        if self._records:
            previous = self._records[-1]
            if timestamp_ns <= previous["timestamp_ns"] or sequence <= previous["sequence"]:
                raise TelemetryError("timestamp and sequence must increase strictly")
        required_trace = {
            "camera_frame_id", "tof_frame_id", "perception_frame", "stimulus_channels",
            "male_cns", "dn_readout", "pre_safety_intent", "safety_result",
        }
        if not isinstance(trace, Mapping) or set(trace) != required_trace:
            raise TelemetryError("trace stage fields mismatch")
        perception = dict(trace["perception_frame"])
        required_perception = {
            "timestamp_ns", "frame_id", "target_x", "target_area", "looming",
            "proximity_left", "proximity_center", "proximity_right", "confidence", "valid",
        }
        if set(perception) != required_perception:
            raise TelemetryError("perception frame fields mismatch")
        readout = dict(trace["dn_readout"])
        for key in ("steering_left", "steering_right", "escape"):
            if key not in readout:
                raise TelemetryError("DN readout fields mismatch")
        pre = _intent(trace["pre_safety_intent"], "pre-safety")
        safety = trace["safety_result"]
        if not isinstance(safety, Mapping) or set(safety) != {"intent", "clamp_applied", "reasons"}:
            raise TelemetryError("safety result fields mismatch")
        post = _intent(safety["intent"], "post-safety")
        final = _intent(watchdog_output["intent"], "watchdog")
        state = watchdog_output.get("watchdog_state")
        if state not in ("healthy", "safe_stop") or type(watchdog_output.get("decoder_alive")) is not bool:
            raise TelemetryError("watchdog fields mismatch")
        if type(robotd_connected) is not bool or not isinstance(robotd_transport_result, str):
            raise TelemetryError("robotd result fields mismatch")
        command_type = "robot.stop" if final["stop"] else "robot.move"
        expected_results = {"robot_stop_refreshed"} if final["stop"] else {"move"}
        if robotd_transport_result not in expected_results:
            raise TelemetryError("robotd transport result does not match final command")
        record = {
            "schema_version": SCHEMA_VERSION,
            "run_id": self.identity["run_id"],
            "trial_id": trial_id,
            "scenario": scenario,
            "timestamp_ns": timestamp_ns,
            "sequence": sequence,
            "camera_frame_id": trace["camera_frame_id"],
            "tof_frame_id": trace["tof_frame_id"],
            "perception": perception,
            "stimulus_channels": dict(trace["stimulus_channels"]),
            "male_cns": dict(trace["male_cns"]),
            "dn_activity": {
                "steering_left": readout["steering_left"],
                "steering_right": readout["steering_right"],
                "escape": readout["escape"],
                "runtime_healthy": readout["runtime_healthy"],
                "timestamp_ns": readout["timestamp_ns"],
                "sequence": readout["sequence"],
            },
            "pre_safety_intent": pre,
            "post_safety_intent": post,
            "clamp_applied": safety["clamp_applied"],
            "clamp_reasons": list(safety["reasons"]),
            "watchdog_state": state,
            "watchdog_stale_reason": watchdog_output.get("stale_reason"),
            "decoder_alive": watchdog_output["decoder_alive"],
            "robot_facing_command_type": command_type,
            "robot_facing_vx": final["vx"],
            "robot_facing_vy": final["vy"],
            "robot_facing_vyaw": final["vyaw"],
            "robot_facing_stop": final["stop"],
            "robotd_connection_state": "connected" if robotd_connected else "disconnected",
            "robotd_transport_result": robotd_transport_result,
            "robot_state": copy.deepcopy(dict(robot_state)),
            "identities": copy.deepcopy(self.identity),
        }
        _scan(record)
        detached = json.loads(_canonical(record))
        self._records.append(detached)
        return copy.deepcopy(detached)

    def records(self) -> list[dict]:
        return copy.deepcopy(self._records)

    def to_jsonl(self) -> str:
        return "".join(_canonical(record) + "\n" for record in self._records)

    def write(self, path: str | Path) -> dict:
        payload = self.to_jsonl().encode("ascii")
        Path(path).write_bytes(payload)
        return {
            "sha256": hashlib.sha256(payload).hexdigest(),
            "record_count": len(self._records),
            "start_timestamp_ns": self._records[0]["timestamp_ns"] if self._records else None,
            "end_timestamp_ns": self._records[-1]["timestamp_ns"] if self._records else None,
        }
