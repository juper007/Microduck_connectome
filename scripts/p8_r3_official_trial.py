"""P8-R3 frozen-encoder moving-body development recertification on Thor."""
from __future__ import annotations

import argparse
import copy
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import platform
import queue
import socket
import subprocess
import threading
import time
import tomllib

from microduck_connectome.g8_r5d_metrics import (
    bounded_neural_lineage, causal_timeline_ok, deadman_limiter_seen_before_stopped,
    deadman_timing, first_sustained,
    material_pre_stop_applied, neural_input_ended_by_ack, pose_speeds,
    safe_observation_horizon, stop_refresh_cadence, valid_state_path,
)
from microduck_connectome.g8_r5d_fixture import (
    IsolatedStopPublisher, SUPPRESSED_NEUTRAL,
)
from microduck_connectome.fault_stop import FaultStopLatch
from microduck_connectome.neural_stop_latch import NeuralStopIntentLatch
from microduck_connectome.neural_stop_scheduler import NeuralStopRefreshScheduler
from microduck_connectome.neural_stop_arbiter import NeuralStopMotionArbiter, MotionLatched
from microduck_connectome.looming_v2 import LoomingEstimatorV2, LoomingV2Config
from microduck_connectome.fractional_rgb_v21 import (
    FractionalRedTargetDetector, render_fractional_pixels,
)
from microduck_connectome.perception_compositor import PerceptionPipeline
from microduck_connectome.scheduler import NeuralUpdate
from microduck_connectome.graph import ConnectomeGraph
from microduck_connectome.looming_scenario import load_config, make_trial, render_pixels, pixels_sha256
from microduck_connectome.motion_adapter import RobotMotionAdapter
from microduck_connectome.robotd_client import RobotdClient
from microduck_connectome.looming_scenario import sphere_center
from microduck_connectome.telemetry import EndToEndTelemetry, build_run_identity
from microduck_connectome.watchdog import ControllerWatchdog
from scripts.p6_motion_fixture import JsonLines
from scripts.p6_telemetry_runtime_fixture import FullChain, RobotStateSampler, git_head
from scripts.p8_looming_scenario_smoke import OfficialPoseReader
from scripts.p7_pretrial_acquisition import validate_loaded_walk_policy


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def validate_frozen_selection(protocol):
    """Reject draft protocols before any official robot command can be sent."""
    versions = {
        "p8-r3-official-development-v1": ([885321, 885322, 885323], "binary_rgb_v1"),
        "p8-r3-v21-official-development-v1": ([885421, 885422, 885423], "fractional_rgb_v21"),
        "p8-r3-v22-official-development-v1": ([885521, 885522, 885523], "fractional_rgb_v21"),
        "p8-r3-v23-official-development-v1": ([885621, 885622, 885623], "fractional_rgb_v21"),
        "p8-r3-v24-official-development-v1": ([885721, 885722, 885723], "fractional_rgb_v21"),
    }
    version = protocol.get("schema_version")
    if version not in versions:
        raise ValueError("P8-R3 protocol version mismatch")
    if (protocol.get("internal_gate_status") != "PASS"
            or protocol.get("official_freeze_status") != "FROZEN"):
        raise RuntimeError("internal neural gate and official protocol freeze are required")
    selected = protocol.get("selected_v2")
    if not isinstance(selected, dict):
        raise RuntimeError("selected V2 encoder is missing")
    frozen_candidates = {
        "log_area": 0.5,
        "relative_radius": 0.25,
        "log_area_regression": 0.5,
    }
    if (set(selected) != {"method", "full_scale_rate_per_s", "area_epsilon",
                         "max_gap_ms", "window_ms"}
            or selected.get("method") not in frozen_candidates
            or selected.get("full_scale_rate_per_s") != frozen_candidates[selected["method"]]
            or selected.get("area_epsilon") != 1e-6
            or selected.get("max_gap_ms") != 150
            or selected.get("window_ms") != 200):
        raise RuntimeError("selected estimator differs from prospective P8-R3 candidates")
    config = LoomingV2Config(**selected)
    if version == "p8-r3-v21-official-development-v1" and config.method != "log_area":
        raise RuntimeError("V2.1 fractional RGB hypothesis requires V2 log-area estimator A")
    hz = protocol.get("visual_hz")
    if type(hz) is not int or hz not in (10, 20, 25):
        raise RuntimeError("visual cadence must be selected from the frozen sampling screen")
    if version == "p8-r3-v21-official-development-v1" and hz != 10:
        raise RuntimeError("V2.1 selected visual cadence must remain 10 Hz")
    if version in ("p8-r3-v22-official-development-v1",
                   "p8-r3-v23-official-development-v1",
                   "p8-r3-v24-official-development-v1"):
        if protocol.get("fault_gate_status") != "PASS":
            raise RuntimeError("V2.2/V2.3 fault-stop gate must PASS before official execution")
        if config.method != "log_area" or hz != 20:
            raise RuntimeError("V2.2/V2.3 requires unchanged estimator A at selected 20 Hz")
        if (protocol.get("selected_visual_period_ms") != 50
                or protocol.get("maximum_official_visual_frame_gap_ms") != 100
                or protocol.get("maximum_visual_lineage_age_ms") != 100
                or protocol.get("deadman_timeout_ms") != 500):
            raise RuntimeError("V2.2/V2.3 visual cadence or safety freshness changed")
        for key in ("internal_gate_script_path", "internal_gate_script_sha256",
                    "fault_gate_artifact_path", "fault_gate_artifact_sha256"):
            if not isinstance(protocol.get(key), str):
                raise RuntimeError(f"V2.2/V2.3 missing prospective {key}")
    if version in ("p8-r3-v23-official-development-v1",
                   "p8-r3-v24-official-development-v1"):
        if protocol.get("startup_gate_status") != "PASS":
            raise RuntimeError("V2.3/V2.4 startup handoff gate must PASS before official execution")
        for key in ("startup_gate_artifact_path", "startup_gate_artifact_sha256"):
            if not isinstance(protocol.get(key), str):
                raise RuntimeError(f"V2.3/V2.4 missing prospective {key}")
    if version == "p8-r3-v24-official-development-v1":
        for key in ("startup_gate_thor_artifact_path", "startup_gate_thor_artifact_sha256"):
            if not isinstance(protocol.get(key), str):
                raise RuntimeError(f"V2.4 missing prospective {key}")
    if not (isinstance(protocol.get("scenario_config_path"), str)
            and isinstance(protocol.get("scenario_config_sha256"), str)
            and isinstance(protocol.get("visual_scheduler_config_sha256"), str)
            and isinstance(protocol.get("internal_gate_artifact_path"), str)
            and isinstance(protocol.get("internal_gate_artifact_sha256"), str)):
        raise RuntimeError("scenario and internal-gate hashes must be frozen")
    runs = protocol.get("ordered_official_runs")
    if (not isinstance(runs, list) or len(runs) != 3
            or [row.get("seed") for row in runs] != versions[version][0]
            or len({row.get("run_id") for row in runs}) != 3):
        raise RuntimeError("P8-R3 official three-reset seed matrix mismatch")
    if version in ("p8-r3-v22-official-development-v1",
                   "p8-r3-v23-official-development-v1",
                   "p8-r3-v24-official-development-v1"):
        seeds = versions[version][0]
        expected = [(f"{i:02d}-{seed}", seed, arm) for i, (seed, arm) in enumerate(
            zip(seeds, (2.0, 2.6, 3.0)), start=1)]
        if ([(row.get("run_id"), row.get("seed"), row.get("arm_elapsed_s"))
             for row in runs] != expected
                or protocol.get("scenario_seeds") != list(seeds)
                or protocol.get("arm_elapsed_s") != [2.0, 2.6, 3.0]):
            raise RuntimeError("V2.2/V2.3 official run order or arm assignment changed")
    if protocol.get("visual_representation") != versions[version][1]:
        raise RuntimeError("frozen RGB representation mismatches protocol version")
    if (version in ("p8-r3-v21-official-development-v1",
                    "p8-r3-v22-official-development-v1",
                    "p8-r3-v23-official-development-v1",
                    "p8-r3-v24-official-development-v1")
            and not isinstance(protocol.get("fractional_rgb_module_sha256"), str)):
        raise RuntimeError("fractional RGB source hash must be frozen")
    return config, hz


def validate_v24_gate_artifact(gate: dict, *, source_sha: str, thor: bool) -> None:
    healthy_names = ("normal_handoff", "real_worker_start_and_stop_refresh")
    fault_names = ("missing_prime", "invalid_prime", "future_prime", "stale_prime",
                   "malformed_prime", "nan_prime", "delayed_start",
                   "visual_drop_stale_neural_persistence", "fault_supersedes_neural_stop")
    rows = gate.get("cases")
    group_a, group_b = gate.get("group_a", {}), gate.get("group_b", {})
    if (gate.get("schema_version") != "p8-r3-v24-startup-gate-v1"
            or gate.get("result") != "PASS"
            or gate.get("source_head") != source_sha
            or not isinstance(rows, list)
            or [row.get("name") for row in rows] != list(healthy_names + fault_names)
            or any(row.get("result") != "PASS" for row in rows)
            or group_a.get("result") != "PASS" or group_b.get("result") != "PASS"
            or group_a.get("case_names") != list(healthy_names)
            or group_b.get("case_names") != list(fault_names)
            or (group_a.get("planned"), group_a.get("passed")) != (2, 2)
            or (group_b.get("planned"), group_b.get("passed")) != (9, 9)
            or group_a.get("healthy_missing_count") != 0
            or not isinstance(group_b.get("injected_missing_count"), int)
            or group_b["injected_missing_count"] <= 0):
        raise RuntimeError("frozen V2.4 group gate artifact failed case/schema/source checks")
    for row in rows[:2]:
        metric = row.get("metrics", {})
        ages = metric.get("armed_age_ms")
        if (not isinstance(ages, list) or metric.get("armed_neural_ticks", 0) < 1
                or len(ages) != metric["armed_neural_ticks"]
                or metric.get("armed_missing_count") != 0
                or metric.get("armed_invalid_count") != 0
                or any(not isinstance(age, (int, float)) or age < 0 or age > 100
                       for age in ages)
                or any(gap > 100 for gap in metric.get("frame_gaps_ms", []))
                or metric.get("post_stop_positive_moves") != 0
                or row.get("scheduler_exceptions") != 0):
            raise RuntimeError("frozen V2.4 healthy group has missing/stale input")
    real_gaps = rows[1]["metrics"].get("stop_ack_gaps_ms", [])
    if not real_gaps or max(real_gaps) > 100:
        raise RuntimeError("frozen V2.4 real worker stop ACK refresh failed")
    drop = rows[9]
    if (drop.get("metrics", {}).get("armed_missing_count", 0) <= 0
            or group_b["injected_missing_count"] != drop["metrics"]["armed_missing_count"]
            or drop["metrics"].get("first_invalid_neural_ns") is None
            or drop["metrics"].get("first_fault_control_ns") is None
            or drop.get("arbiter_latch_reason") != "fault_stale_neural"
            or drop["metrics"].get("post_stop_positive_moves") != 0):
        raise RuntimeError("frozen V2.4 injected visual fault result is incomplete")
    for row in rows[2:9]:
        if (row.get("metrics", {}).get("command_ack_count") != 0
                or any(event.get("kind") == "command_ack"
                       for event in row.get("events", []))):
            raise RuntimeError("frozen V2.4 rejected prime/delay published a command")
    for row in rows[9:]:
        metric = row.get("metrics", {})
        gaps = metric.get("stop_ack_gaps_ms", [])
        commands = [event for event in row.get("events", [])
                    if event.get("kind") == "command_ack"]
        first_stop = next((index for index, event in enumerate(commands)
                           if event.get("action") == "robot.stop"), None)
        stop_commands = commands[first_stop:] if first_stop is not None else []
        actual_gaps = []
        if all(isinstance(event.get("ack_ns"), int) for event in stop_commands):
            actual_gaps = [(b["ack_ns"] - a["ack_ns"]) / 1e6
                           for a, b in zip(stop_commands, stop_commands[1:])]
        if (not gaps or len(gaps) != len(actual_gaps)
                or any(not isinstance(gap, (int, float)) or gap < 0 or gap > 100
                       or abs(gap - actual) > 1e-6
                       for gap, actual in zip(gaps, actual_gaps))
                or metric.get("post_stop_positive_moves") != 0
                or row.get("scheduler_exceptions") != 0
                or first_stop is None
                or metric.get("command_ack_count") != len(commands)
                or any(event.get("action") != "robot.stop" for event in stop_commands)):
            raise RuntimeError("frozen V2.4 fault stop ACK/persistence failed")
    external = rows[10]
    if (external.get("arbiter_latch_reason") != "fault_camera_loss"
            or (external.get("fault_latch") or {}).get("reason") != "camera_loss"):
        raise RuntimeError("frozen V2.4 external fault priority failed")
    hostname = str(gate.get("hostname", ""))
    if thor and (not hostname.startswith("jetsonthor")
                 or not str(gate.get("python_version", "")).startswith("3.12.")):
        raise RuntimeError("frozen V2.4 Thor gate provenance mismatch")
    if not thor and (not hostname or hostname.startswith("jetsonthor")):
        raise RuntimeError("frozen V2.4 local gate provenance mismatch")


def validate_frozen_material(root: Path, protocol: dict) -> None:
    """Verify selected source ancestor and committed local evidence/config bytes."""
    root = root.resolve()
    source = protocol.get("source_freeze_sha")
    if (not isinstance(source, str) or len(source) != 40
            or any(char not in "0123456789abcdef" for char in source)
            or subprocess.run(["git", "-C", str(root), "merge-base", "--is-ancestor",
                               source, "HEAD"], check=False,
                              stderr=subprocess.DEVNULL).returncode != 0):
        raise RuntimeError("frozen pre-config source SHA is not an ancestor of HEAD")
    files = {
        "graph_manifest_sha256": "data/manifests/controller-graph-v2.json",
        "scenario_config_sha256": protocol["scenario_config_path"],
        "visual_scheduler_config_sha256": protocol["visual_scheduler_config_path"],
        "internal_gate_artifact_sha256": protocol["internal_gate_artifact_path"],
    }
    if protocol["visual_representation"] == "fractional_rgb_v21":
        files.update({
            "fractional_rgb_module_sha256": "microduck_connectome/fractional_rgb_v21.py",
            "looming_v2_module_sha256": "microduck_connectome/looming_v2.py",
            "initial_internal_gate_artifact_sha256": protocol["initial_internal_gate_artifact_path"],
            "internal_gate_manifest_sha256": protocol["internal_gate_manifest_path"],
            "sampling_gate_manifest_sha256": protocol["sampling_gate_manifest_path"],
        })
    if protocol["schema_version"] in ("p8-r3-v22-official-development-v1",
                                       "p8-r3-v23-official-development-v1",
                                       "p8-r3-v24-official-development-v1"):
        files.update({
            "internal_gate_script_sha256": protocol["internal_gate_script_path"],
            "fault_gate_artifact_sha256": protocol["fault_gate_artifact_path"],
        })
    if protocol["schema_version"] in ("p8-r3-v23-official-development-v1",
                                       "p8-r3-v24-official-development-v1"):
        files["startup_gate_artifact_sha256"] = protocol["startup_gate_artifact_path"]
    if protocol["schema_version"] == "p8-r3-v24-official-development-v1":
        files["startup_gate_thor_artifact_sha256"] = protocol["startup_gate_thor_artifact_path"]
    config_paths = {
        "neural_model": "neural_model_v1.json", "sensory_mapping": "sensory_mapping_v1.json",
        "dn_readout": "dn_readout_v1.json", "escape_decoder": "escape_decoder_v1.json",
        "safety_envelope": "safety_envelope_v1.json", "watchdog": "watchdog_v1.json",
        "motion_adapter": "motion_adapter_v1.json", "scheduler": "scheduler_v1.json",
        "telemetry": "telemetry_v1.json",
    }
    files.update({f"config_sha256.{key}": f"config/{name}"
                  for key, name in config_paths.items()})
    for key, relative in files.items():
        target = (root / relative).resolve()
        if not target.is_relative_to(root):
            raise RuntimeError(f"frozen {key} path escapes source")
        expected = (protocol["config_sha256"][key.split(".", 1)[1]]
                    if key.startswith("config_sha256.") else protocol[key])
        committed = subprocess.check_output(
            ["git", "-C", str(root), "show", f"HEAD:{target.relative_to(root).as_posix()}"])
        if hashlib.sha256(committed).hexdigest() != expected:
            raise RuntimeError(f"frozen {key} hash mismatch")
        if subprocess.run(["git", "-C", str(root), "diff", "--quiet", "HEAD", "--",
                           target.relative_to(root).as_posix()], check=False).returncode != 0:
            raise RuntimeError(f"frozen {key} differs from committed content")
    if protocol["schema_version"] in ("p8-r3-v22-official-development-v1",
                                       "p8-r3-v23-official-development-v1",
                                       "p8-r3-v24-official-development-v1"):
        fault_gate = json.loads((root / protocol["fault_gate_artifact_path"]).read_text())
        if (fault_gate.get("schema_version") != "p8-r3-v22-fault-gate-v1"
                or fault_gate.get("result") != "PASS"):
            raise RuntimeError("frozen V2.2 fault-stop gate artifact is not PASS")
    if protocol["schema_version"] == "p8-r3-v23-official-development-v1":
        startup_gate = json.loads((root / protocol["startup_gate_artifact_path"]).read_text())
        if (startup_gate.get("schema_version") != "p8-r3-v23-startup-gate-v1"
                or startup_gate.get("result") != "PASS"):
            raise RuntimeError("frozen V2.3 startup handoff gate artifact is not PASS")
    if protocol["schema_version"] == "p8-r3-v24-official-development-v1":
        for key in ("startup_gate_artifact_path", "startup_gate_thor_artifact_path"):
            gate = json.loads((root / protocol[key]).read_text())
            validate_v24_gate_artifact(
                gate, source_sha=protocol["source_freeze_sha"],
                thor=key == "startup_gate_thor_artifact_path")
    scenario = load_config(root / protocol["scenario_config_path"])
    if (scenario["safety_boundary_center_distance_m"] != 0.25
            or protocol["visual_representation"] == "fractional_rgb_v21"
            and (scenario["image_width_px"], scenario["image_height_px"]) != (65, 33)):
        raise RuntimeError("frozen scenario dimensions or 0.25 m boundary changed")


def validate_frozen_output_dir(protocol: dict, output: Path) -> None:
    frozen = protocol.get("frozen_output_dir")
    if (not isinstance(frozen, str) or not PurePosixPath(frozen).is_absolute()
            or output.resolve() != Path(frozen).resolve()):
        raise RuntimeError("official output must use the frozen raw directory")


def acknowledged_precondition_move(client, *, vx, vy, vyaw):
    """Use official request-form robot.move to obtain an actual robotd ACK."""
    request_id = client.next_id
    client.next_id += 1
    payload = {"jsonrpc": "2.0", "id": request_id, "method": "robot.move",
               "params": {"vx": vx, "vy": vy, "vyaw": vyaw}}
    call_ns = time.monotonic_ns()
    client.file.write((json.dumps(payload, separators=(",", ":"), allow_nan=False) + "\n").encode())
    client.file.flush()
    write_done_ns = time.monotonic_ns()
    while True:
        reply = json.loads(client.file.readline())
        if reply.get("id") != request_id:
            continue
        ack_ns = time.monotonic_ns()
        if "error" in reply:
            raise RuntimeError(reply["error"])
        result = reply["result"]
        if not isinstance(result, dict) or result.get("accepted") is not True:
            raise RuntimeError(f"robot.move was not accepted: {result!r}")
        return result, call_ns, write_done_ns, ack_ns


class VisualCadence:
    """Select 10/20/25 Hz camera ticks from the frozen 50 Hz producer clock."""

    def __init__(self, hz: int):
        if hz not in (10, 20, 25):
            raise ValueError("unsupported P8-R3 visual cadence")
        self.period_ns = round(1_000_000_000 / hz)
        self.next_ns = None
        self.last_due_ns = None

    def due(self, now_ns: int) -> bool:
        if self.next_ns is None:
            self.last_due_ns = now_ns
            self.next_ns = now_ns + self.period_ns
            return True
        if now_ns < self.next_ns:
            return False
        self.last_due_ns = self.next_ns
        while self.next_ns <= now_ns:
            self.next_ns += self.period_ns
        return True


class LoomingChain(FullChain):
    def __init__(self, root, graph, scenario, pose_reader, pose_lock, elapsed_start_s,
                 arbiter, *, estimator, visual_hz, visual_representation):
        super().__init__(root, graph)
        self.pipeline = PerceptionPipeline(
            camera_detector=(FractionalRedTargetDetector()
                             if visual_representation == "fractional_rgb_v21" else None),
            looming_estimator=estimator,
        )
        self.render_pixels = (render_fractional_pixels
                              if visual_representation == "fractional_rgb_v21"
                              else render_pixels)
        self.visual_cadence = VisualCadence(visual_hz)
        self.scenario_config = scenario
        self.pose_reader = pose_reader
        self.pose_lock = pose_lock
        self.elapsed_start_s = elapsed_start_s
        self.trial = None
        self.started_ns = None
        self.scenario = "stop"
        self.neural_ledger = []
        self.graph_identity = graph.root_key
        self.handoff_ack_ns = None
        self.discarded_visual_after_ack = []
        self.arbiter = arbiter
        self.visual_frames = []
        self.neural_stop_latch = NeuralStopIntentLatch(
            escape_threshold=self.escape.config.threshold)

    def perception(self, now_ns):
        if not self.visual_cadence.due(now_ns):
            return None
        if self.trial is None:
            raise RuntimeError("looming cannot start before motion confirmation")
        if self.started_ns is None:
            self.started_ns = now_ns
        self.frame_id += 1
        elapsed = self.elapsed_start_s + (now_ns - self.started_ns) / 1e9
        with self.pose_lock:
            pose = self.pose_reader.read()
        pixels = self.render_pixels(self.scenario_config, self.trial, pose=pose, elapsed_s=elapsed)
        tof = self.scenario_config["tof_mm"]
        processing_started_ns = time.monotonic_ns()
        frame = self.pipeline.process(
            pixels, camera_timestamp_ns=now_ns, camera_frame_id=self.frame_id,
            tof_left_mm=tof, tof_center_mm=tof, tof_right_mm=tof,
            tof_timestamp_ns=now_ns, tof_frame_id=self.frame_id, now_ns=now_ns,
        )
        processing_finished_ns = time.monotonic_ns()
        self.visual_frames.append({"frame_id": self.frame_id, "timestamp_ns": now_ns,
                                   "scheduled_due_ns": self.visual_cadence.last_due_ns,
                                   "processing_started_ns": processing_started_ns,
                                   "processing_finished_ns": processing_finished_ns,
                                   "pixel_area": sum(pixel != (0, 0, 0)
                                                     for row in pixels for pixel in row),
                                   "pixels_sha256": pixels_sha256(pixels),
                                   "perception_valid": frame["valid"],
                                   "perception_target_area": frame["target_area"],
                                   "perception_looming": frame["looming"]})
        return frame

    def _compute_neural(self, frame, now_ns):
        """Run the ordinary decoder once, then apply the stop latch and safety once."""
        self.neural_sequence += 1
        if frame is None:
            return None
        channels = self.mapper.map_channels(frame, now_ns=now_ns)
        mapped = self.mapper.build_external(frame, now_ns=now_ns)
        external = {body_id: value for body_id, value in mapped.items()
                    if body_id in self.runtime_index}
        snapshot = self.runtime.step(external)
        projected_spikes = tuple(
            snapshot["spikes"][self.runtime_index[body_id]]
            if body_id in self.runtime_index else False for body_id in self.dn_ids)
        readout = self.aggregator.update(
            projected_spikes, timestamp_ns=now_ns,
            sequence=self.neural_sequence, runtime_healthy=snapshot["healthy"])
        raw_decoded = self.escape.apply(readout, self.steering.decode(readout))
        selected, safe, held_nonstop = self.neural_stop_latch.apply(
            readout=readout, decoded_intent=raw_decoded, safety=self.safety,
            now_ns=now_ns, graph_runtime_step=self.neural_sequence)
        latched = self.neural_stop_latch.snapshot()
        trace = {
            "camera_frame_id": frame["frame_id"],
            "tof_frame_id": frame["frame_id"],
            "perception_frame": dict(frame),
            "stimulus_channels": channels,
            "male_cns": {
                "runtime_step": self.neural_sequence,
                "healthy": snapshot["healthy"],
                "spike_count": sum(bool(value) for value in snapshot["spikes"]),
                "external_input_count": len(external),
                "scenario_fixture": self.scenario,
            },
            "dn_readout": readout,
            "raw_decoded_intent": raw_decoded,
            "pre_safety_intent": selected,
            "safety_result": safe,
            "neural_stop_latch": {
                "source": latched.source if latched is not None else None,
                "held_nonstop_decoder_output": held_nonstop,
                "first_healthy_stop_ack_ns": (
                    latched.first_healthy_stop_ack_ns if latched is not None else None),
            },
        }
        return NeuralUpdate(readout, safe["intent"], trace)

    def neural(self, frame, now_ns):
        call_started_ns = time.monotonic_ns()
        update = self.arbiter.neural_step(lambda: self._compute_neural(frame, now_ns))
        call_returned_ns = time.monotonic_ns()
        if update is None or update.trace is None:
            self.neural_ledger.append({"neural_call_timestamp_ns": now_ns,
                                       "neural_call_started_ns": call_started_ns,
                                       "neural_call_returned_ns": call_returned_ns,
                                       "result_none": True, "input_none": frame is None,
                                       "perception_age_ms": None})
            return update
        trace = update.trace
        perception = trace["perception_frame"]
        stimulus = trace["stimulus_channels"]
        readout = trace["dn_readout"]
        self.neural_ledger.append({
            "neural_call_timestamp_ns": now_ns,
            "neural_call_started_ns": call_started_ns,
            "neural_call_returned_ns": call_returned_ns,
            "graph_identity": self.graph_identity,
            "result_none": False, "input_none": frame is None,
            "runtime_step": trace["male_cns"]["runtime_step"],
            "male_cns_healthy": trace["male_cns"]["healthy"],
            "dn_sequence": readout["sequence"],
            "dn_timestamp_ns": readout["timestamp_ns"],
            "dn_runtime_healthy": readout["runtime_healthy"],
            "dn_escape": readout["escape"],
            "perception_timestamp_ns": perception["timestamp_ns"],
            "perception_frame_id": perception["frame_id"],
            "perception_valid": perception["valid"],
            "perception_age_ms": (call_started_ns - perception["timestamp_ns"]) / 1e6,
            "looming": perception["looming"],
            "proximity_left": perception["proximity_left"],
            "proximity_center": perception["proximity_center"],
            "proximity_right": perception["proximity_right"],
            "stimulus_channels": copy.deepcopy(stimulus),
            "external_input_count": trace["male_cns"]["external_input_count"],
            "raw_decoder_stop": trace["raw_decoded_intent"]["stop"],
            "raw_decoder_confidence": trace["raw_decoded_intent"]["confidence"],
            "held_nonstop_decoder_output": trace["neural_stop_latch"]["held_nonstop_decoder_output"],
            "latched_stop_source": trace["neural_stop_latch"]["source"],
            "post_safety_stop": trace["safety_result"]["intent"]["stop"],
        })
        return update


def verify_protocol(root, protocol_path, protocol, args):
    if socket.gethostname().startswith("jetsonthor") is False or platform.python_version_tuple()[:2] != ("3", "12"):
        raise RuntimeError("official Thor Python 3.12 required")
    estimator_config, visual_hz = validate_frozen_selection(protocol)
    if not 0 < protocol["maximum_stop_refresh_gap_ms"] < protocol["deadman_timeout_ms"]:
        raise ValueError("stop refresh gap must be below frozen deadman timeout")
    if git_head(root) != args.source_head:
        raise RuntimeError("source head mismatch")
    if subprocess.check_output(
            ["git", "-C", str(root), "status", "--porcelain"], text=True).strip():
        raise RuntimeError("development trial requires a clean frozen source checkout")
    committed = subprocess.check_output(["git", "-C", str(root), "show",
                                         f"HEAD:{protocol_path.relative_to(root).as_posix()}"])
    if protocol_path.read_bytes() != committed:
        raise RuntimeError("protocol differs from committed bytes")
    validate_frozen_material(root, protocol)
    frozen_folder = Path(protocol["frozen_output_dir"]) / protocol["ordered_official_runs"][args.trial_index]["run_id"]
    if any(path.resolve().parent != frozen_folder.resolve()
           for path in (args.raw, args.events, args.ledger, args.visual, args.summary, args.policy_readback)):
        raise RuntimeError("trial artifacts must use the frozen raw directory")
    if any(path.exists() for path in (args.raw, args.events, args.ledger, args.visual, args.summary)):
        raise RuntimeError("official trial raw artifacts must use unused paths")
    manifest_path = root / "data/manifests/controller-graph-v2.json"
    manifest = json.loads(manifest_path.read_text())
    if sha(manifest_path) != protocol["graph_manifest_sha256"]:
        raise RuntimeError("graph manifest hash mismatch")
    graph_path = Path(manifest["thor_artifact"])
    if (manifest["graph_sha256"] != protocol["graph_sha256"]
            or sha(graph_path) != protocol["graph_sha256"]):
        raise RuntimeError("graph v2 artifact mismatch")
    if git_head(args.microduck) != protocol["microduck_commit"] or git_head(args.microduck_rl) != protocol["microduck_rl_commit"]:
        raise RuntimeError("official upstream commit mismatch")
    if sha(protocol["walking_policy_path"]) != protocol["walking_policy_sha256"]:
        raise RuntimeError("walking policy hash mismatch")
    readback = json.loads(args.policy_readback.read_text())
    validate_loaded_walk_policy(readback, Path(protocol["walking_policy_path"]),
                                protocol["walking_policy_sha256"])
    paths = {"neural_model": "neural_model_v1.json", "sensory_mapping": "sensory_mapping_v1.json",
             "dn_readout": "dn_readout_v1.json", "escape_decoder": "escape_decoder_v1.json",
             "safety_envelope": "safety_envelope_v1.json", "watchdog": "watchdog_v1.json",
             "motion_adapter": "motion_adapter_v1.json", "scheduler": "scheduler_v1.json",
             "telemetry": "telemetry_v1.json"}
    if any(sha(root / "config" / relative) != protocol["config_sha256"][name]
           for name, relative in paths.items()):
        raise RuntimeError("frozen controller/safety config hash mismatch")
    scenario_path = (root / protocol["scenario_config_path"]).resolve()
    if not scenario_path.is_relative_to(root):
        raise RuntimeError("scenario path escapes frozen source")
    if sha(scenario_path) != protocol["scenario_config_sha256"]:
        raise RuntimeError("frozen scenario hash mismatch")
    gate_path = (root / protocol["internal_gate_artifact_path"]).resolve()
    if not gate_path.is_relative_to(root) or sha(gate_path) != protocol["internal_gate_artifact_sha256"]:
        raise RuntimeError("internal gate artifact hash mismatch")
    if sha(root / "config/p8_r3_visual_scheduler_v1.json") != protocol["visual_scheduler_config_sha256"]:
        raise RuntimeError("frozen visual scheduler hash mismatch")
    if (protocol["visual_representation"] == "fractional_rgb_v21"
            and sha(root / "microduck_connectome/fractional_rgb_v21.py")
            != protocol["fractional_rgb_module_sha256"]):
        raise RuntimeError("frozen fractional RGB source hash mismatch")
    adapter = json.loads((root / "config/motion_adapter_v1.json").read_text())
    escape = json.loads((root / "config/escape_decoder_v1.json").read_text())
    envelope = json.loads((root / "config/safety_envelope_v1.json").read_text())
    if adapter["stop_transport"] != protocol["stop_transport"] or escape["threshold"] != protocol["escape_threshold"]:
        raise RuntimeError("frozen stop transport/threshold mismatch")
    pre = protocol["precondition"]
    if (abs(pre["vx_mps"]) > envelope["max_abs_vx_mps"] or pre["vy_mps"] != 0
            or abs(pre["vyaw_radps"]) > envelope["max_abs_vyaw_radps"]):
        raise RuntimeError("precondition exceeds frozen safety envelope")
    params_source = (args.microduck / "robotd-params/src/lib.rs").read_text()
    if f"deadman_ms: {protocol['deadman_timeout_ms']}" not in params_source:
        raise RuntimeError("pinned official deadman default differs from frozen protocol")
    effective = tomllib.loads((Path(args.socket).parent / "robotd.toml").read_text())
    active_deadman = effective.get("safety", {}).get("deadman_ms", protocol["deadman_timeout_ms"])
    if active_deadman != protocol["deadman_timeout_ms"]:
        raise RuntimeError("active robotd deadman differs from frozen protocol")
    scenario = load_config(scenario_path)
    if scenario["safety_boundary_center_distance_m"] != 0.25:
        raise RuntimeError("frozen 0.25 m center-distance boundary changed")
    return manifest, graph_path, scenario, estimator_config, visual_hz


def robot_state_record(state, received_ns, pose, pose_ns, publish_started_ns=None,
                       publish_ack_ns=None):
    move = state["move"]
    odom = state.get("odom") or {}
    return {
        "state_sample_timestamp_ns": received_ns, "body_sample_timestamp_ns": pose_ns,
        "robot_t_ns": state.get("t_ns"), "policy": state["policy"],
        "requested_velocity": list(move["requested"]),
        "applied_velocity": list(move["applied"]),
        "reported_odom_velocity": [odom.get("vx"), odom.get("vy"), odom.get("vyaw")],
        "trunk_x_m": pose["x_m"], "trunk_y_m": pose["y_m"],
        "heading_rad": pose["heading_rad"], "trunk_z_m": pose["trunk_z_m"],
        "publish_call_started_ns": publish_started_ns,
        "publish_ack_returned_ns": publish_ack_ns,
        "limited_by": list(move.get("limited_by", [])),
    }


def neural_stop_origin(chain, ack_record, *, threshold):
    """Verify first ACK against the original neural candidate, not held readout.

    A later held stop may be published after escape has fallen below threshold.
    The source step is independently retained in the raw neural ledger.
    """
    record = chain.neural_stop_latch.snapshot()
    if record is None or record.first_healthy_stop_ack_ns is None:
        return None
    if (ack_record["robot_state"]["publish_ack_returned_ns"]
            != record.first_healthy_stop_ack_ns
            or ack_record["watchdog_state"] != "healthy"
            or not ack_record["pre_safety_intent"]["stop"]
            or not ack_record["post_safety_intent"]["stop"]
            or ack_record["robot_facing_command_type"] != "robot.stop"
            or ack_record["robotd_transport_result"] != "robot_stop_refreshed"
            or ack_record["dn_activity"]["sequence"] < record.neural_sequence):
        return None
    origin = next((row for row in chain.neural_ledger
                   if row.get("runtime_step") == record.graph_runtime_step), None)
    if (origin is None or origin.get("dn_sequence") != record.neural_sequence
            or origin.get("dn_timestamp_ns") != record.neural_timestamp_ns
            or origin.get("dn_escape", 0) < threshold
            or origin.get("raw_decoder_stop") is not True
            or origin.get("post_safety_stop") is not True
            or origin.get("dn_runtime_healthy") is not True
            or origin.get("male_cns_healthy") is not True
            or origin.get("graph_identity") != chain.graph_identity):
        return None
    # This verifier input is reconstructed exclusively from the retained raw
    # origin ledger row; it is not a fabricated robot-facing telemetry record.
    lineage_source = {
        "dn_activity": {"sequence": origin["dn_sequence"],
                        "timestamp_ns": origin["dn_timestamp_ns"],
                        "escape": origin["dn_escape"]},
        "male_cns": {"runtime_step": origin["runtime_step"]},
        "identities": {"graph_identity": origin["graph_identity"]},
    }
    return record, origin, lineage_source


def ensure_healthy_neutral_priming(chain, update):
    """Reject a stop before the atomic scheduler/motion-refresh phase begins."""
    if (update is None or not update.readout["runtime_healthy"]
            or update.behavior_intent["stop"]
            or chain.neural_stop_latch.snapshot() is not None):
        raise RuntimeError("neural stop or fault arose during priming before atomic scheduler handoff")


def last_pre_stop_state(history, stop_call_ns):
    """Only a state received before the stop call can prove pre-stop motion."""
    candidates = [sample for sample in history
                  if sample["state_received_ns"] <= stop_call_ns]
    return candidates[-1] if candidates else None


def precondition_deadman_after_motion(rows, motion_confirmed_ns):
    """Detect deadman after established motion using the robot state's sample time.

    The first readback can still describe robotd's state from before the first
    acknowledged move. Preserve that startup marker in raw evidence, but do
    not attribute it to the later moving interval.
    """
    for row in rows:
        state = row["robot_state"]
        if not any("deadman" in str(reason).lower()
                   for reason in state["limited_by"]):
            continue
        sampled_ns = state.get("robot_t_ns")
        if (motion_confirmed_ns is None or sampled_ns is None
                or sampled_ns >= motion_confirmed_ns):
            return True
    return False


def run(args):
    root = args.root.resolve()
    protocol_path = (root / args.protocol).resolve()
    if not protocol_path.is_relative_to(root / "config"):
        raise RuntimeError("official protocol path must be inside source config")
    protocol = json.loads(protocol_path.read_text())
    manifest, graph_path, scenario, estimator_config, visual_hz = verify_protocol(
        root, protocol_path, protocol, args)
    row = protocol["ordered_official_runs"][args.trial_index]
    seed = row["seed"]
    trial_id = f"p8-r3-dev-{row['run_id']}"
    graph = ConnectomeGraph.from_cache(graph_path.parent, protocol["graph_sha256"])
    identity = build_run_identity(
        root, run_id=trial_id, project_commit=args.source_head,
        microduck_commit=git_head(args.microduck), microduck_rl_commit=git_head(args.microduck_rl),
        graph_identity=graph.root_key,
    )
    pre = protocol["precondition"]
    metric = protocol["motion_metric"]
    stopped_rule = protocol["stopped_metric"]
    robot = RobotdClient(args.socket, timeout_s=2.0)
    robot.connect()
    robot.enable(True)
    adapter = RobotMotionAdapter(robot, root / "config/motion_adapter_v1.json")
    isolated_publisher = IsolatedStopPublisher(adapter)
    precondition = JsonLines(args.socket)
    precondition.request("hello", {"api_version": 31})
    sampler = RobotStateSampler(args.socket)
    pose_reader = OfficialPoseReader(args.body_port)
    pose_lock = threading.Lock()
    telemetry = EndToEndTelemetry(root / "config/telemetry_v1.json", identity)
    arbiter = NeuralStopMotionArbiter()
    arm_elapsed_s = row["arm_elapsed_s"]
    observation_ms = protocol["maximum_neural_observation_ms_by_run"][args.trial_index]
    chain = LoomingChain(root, graph, scenario, pose_reader, pose_lock,
                         arm_elapsed_s, arbiter,
                         estimator=LoomingEstimatorV2(estimator_config), visual_hz=visual_hz,
                         visual_representation=protocol["visual_representation"])
    watchdog = ControllerWatchdog(root / "config/watchdog_v1.json")
    fault_latch = FaultStopLatch()
    health_before = robot.health()
    pose_rows = []
    events = []
    state_path = []
    event_lock = threading.Lock()
    observer_errors = []
    pending = queue.Queue(maxsize=512)
    publish_time = {}
    first_stop = {}
    first_stop_observed = threading.Event()
    stop_refreshes = []
    scheduler_errors = []
    last_motion = {}
    pre_stop_state_history = []
    motion_refresh_errors = []
    motion_refreshes = []
    sphere_bound = None
    initial_pose = None
    geometry_rows = []
    post_ack_virtual_center = {}
    started_ns = time.monotonic_ns()

    def transition(state, when_ns):
        with event_lock:
            state_path.append(state)
            if not valid_state_path(state_path, complete=False):
                raise RuntimeError(f"invalid fixture state transition: {state_path!r}")
            events.append({"timestamp_ns": when_ns, "kind": "transition", "state": state})

    transition("SETUP", started_ns)

    def record_geometry(pose, sample_ns, phase):
        if initial_pose is None or chain.trial is None or chain.started_ns is None:
            return
        elapsed_s = arm_elapsed_s + max(
            0.0, (sample_ns - chain.started_ns) / 1e9)
        center_x, center_y = sphere_center(scenario, chain.trial, elapsed_s)
        target_mode = "continuous_original_approaching_visual_scenario"
        distance = math.hypot(center_x - pose["x_m"], center_y - pose["y_m"])
        forward = ((pose["x_m"] - initial_pose["x_m"]) * chain.trial.axis_x
                   + (pose["y_m"] - initial_pose["y_m"]) * chain.trial.axis_y)
        row = {"timestamp_ns": sample_ns, "kind": "virtual_geometry",
               "phase": phase, "sphere_center_distance_m": distance,
               "sphere_surface_clearance_m": distance - scenario["virtual_sphere_radius_m"],
               "robot_forward_displacement_m": forward,
               "scenario_elapsed_s": elapsed_s,
               "virtual_target_mode": target_mode}
        geometry_rows.append(row)
        events.append(row)
        if forward > protocol["maximum_robot_forward_displacement_m"]:
            raise RuntimeError("actual forward displacement exceeded frozen fixture bound")
        row["boundary_margin_m"] = distance - scenario["safety_boundary_center_distance_m"]
        row["crossed_virtual_boundary"] = row["boundary_margin_m"] <= 0

    def observer_worker():
        while True:
            item = pending.get()
            try:
                if item is None:
                    return
                update, output, transport, call_ns, ack_ns = item
                state, received_ns = sampler.after(ack_ns)
                with pose_lock:
                    pose = pose_reader.read()
                    pose_ns = time.monotonic_ns()
                pose_rows.append({"timestamp_ns": pose_ns, "x_m": pose["x_m"],
                                  "y_m": pose["y_m"], "phase": "neural"})
                record_geometry(pose, pose_ns, "neural")
                event = {"timestamp_ns": ack_ns, "kind": "control_publish",
                               "sequence": output["intent"]["sequence"],
                               "watchdog_state": output["watchdog_state"],
                               "watchdog_intent": dict(output["intent"]),
                               "robot_facing_stop": output["intent"]["stop"],
                               "transport_action": transport,
                               "transport_call_started_ns": call_ns if transport != SUPPRESSED_NEUTRAL else None,
                               "transport_ack_returned_ns": ack_ns if transport != SUPPRESSED_NEUTRAL else None,
                               "robot_state": robot_state_record(state, received_ns, pose, pose_ns)}
                if update is not None and update.trace is not None:
                    event["neural_trace"] = copy.deepcopy(update.trace)
                events.append(event)
                if update is None or update.trace is None:
                    continue
                trace = copy.deepcopy(update.trace)
                trace["male_cns"].pop("scenario_fixture", None)
                trace.pop("raw_decoded_intent", None)
                trace.pop("neural_stop_latch", None)
                if trace["perception_frame"]["looming"] > 0 and "NEURAL_LOOMING" not in state_path:
                    transition("NEURAL_LOOMING", trace["perception_frame"]["timestamp_ns"])
                if transport == SUPPRESSED_NEUTRAL:
                    last_motion.update({"state": state, "pose": pose,
                                        "state_received_ns": received_ns,
                                        "pose_sample_ns": pose_ns})
                    pre_stop_state_history.append({
                        "state": state, "pose": pose,
                        "state_received_ns": received_ns,
                        "pose_sample_ns": pose_ns,
                    })
                    continue
                telemetry.append(
                    trial_id=trial_id, scenario="stop",
                    timestamp_ns=output["intent"]["timestamp_ns"],
                    sequence=output["intent"]["sequence"], trace=trace,
                    watchdog_output=output, robotd_transport_result=transport,
                    robotd_connected=robot.status.connected,
                    robot_state=robot_state_record(state, received_ns, pose, pose_ns,
                                                   call_ns, ack_ns),
                )
                record = telemetry.records()[-1]
                if record["robot_facing_stop"] and not first_stop:
                    before = last_pre_stop_state(pre_stop_state_history, call_ns)
                    first_stop.update({"record": record,
                                       "state_before": before["state"] if before else None,
                                       "state_before_received_ns": (before["state_received_ns"]
                                                                    if before else None),
                                       "pose_before": before["pose"] if before else None})
                    origin = neural_stop_origin(
                        chain, record, threshold=protocol["escape_threshold"])
                    if origin is not None:
                        transition("NEURAL_STOP_DETECTED", origin[0].neural_timestamp_ns)
                        transition("ROBOT_STOP_SENT", call_ns)
                        transition("ROBOT_STOP_ACK", ack_ns)
                        transition("STOP_REFRESHING", ack_ns + 1)
                    first_stop_observed.set()
                if not record["robot_facing_stop"]:
                    last_motion.update({"state": state, "pose": pose,
                                        "state_received_ns": received_ns,
                                        "pose_sample_ns": pose_ns})
            except BaseException as error:
                observer_errors.append(f"{type(error).__name__}: {error}")
                arbiter.latch("fixture_observer_fault")
                scheduler._fail("fixture_observer", error)
            finally:
                pending.task_done()

    observer = threading.Thread(target=observer_worker, name="g8-r5d-observer")
    observer.start()

    def publish(output):
        call_ns = time.monotonic_ns()
        # NeuralStopRefreshScheduler owns arbiter.publish around this callback.
        result = isolated_publisher.send(output)
        ack_ns = time.monotonic_ns()
        if result == "robot_stop_refreshed":
            stop_refreshes.append({"sent_at_ns": call_ns, "ack_at_ns": ack_ns,
                                   "sequence": output["intent"]["sequence"],
                                   "source": output["watchdog_state"],
                                   "stale_reason": output["stale_reason"]})
        if result == "robot_stop_refreshed" and chain.handoff_ack_ns is None:
            chain.handoff_ack_ns = ack_ns
        publish_time[output["intent"]["sequence"]] = (call_ns, ack_ns)
        return result

    def observe(update, output, transport):
        if observer_errors:
            raise RuntimeError(observer_errors[0])
        sequence = output["intent"]["sequence"]
        call_ns, ack_ns = publish_time.pop(sequence)
        if update is not None:
            chain.neural_stop_latch.confirm(
                output=output, transport_result=transport, ack_ns=ack_ns,
                source_neural_sequence=update.readout["sequence"],
                source_intent_stop=bool(update.behavior_intent["stop"]),
            )
        if transport == "robot_stop_refreshed" and len(stop_refreshes) > 1:
            events.append({"timestamp_ns": ack_ns, "kind": "stop_refresh_ack",
                           "sequence": sequence, "sent_at_ns": call_ns,
                           "ack_at_ns": ack_ns, "watchdog_state": output["watchdog_state"],
                           "stale_reason": output["stale_reason"],
                           "transport_action": transport})
            return
        pending.put_nowait((update, output, transport, call_ns, ack_ns))
        # Synchronous control-thread handoff happens immediately after the first
        # ACK, before async state/pose sampling can allow another 50 Hz publish.
        if transport == "robot_stop_refreshed":
            events.append({"timestamp_ns": ack_ns, "kind": "continuous_visual_after_stop_ack",
                           "visual_producer_continues_until_actual_stop": True})

    scheduler = NeuralStopRefreshScheduler(
        fault_latch=fault_latch, motion_arbiter=arbiter,
        config=root / "config/p8_r3_visual_scheduler_v1.json", watchdog=watchdog,
        perception_step=chain.perception, neural_step=chain.neural,
        publisher=publish, control_observer=observe,
    )
    scheduler_result = None
    phase_started_ns = None
    precondition_status = None
    runtime_finished_ns = None
    first_applied_reduction_ns = None
    first_applied_near_zero_ns = None
    first_stopped_observed_ns = None
    later_deadman_events = []
    try:
        transition("MOTION_PRECONDITION", time.monotonic_ns())
        for index in range(round(pre["duration_s"] * 1000 / pre["command_period_ms"])):
            tick_ns = time.monotonic_ns()
            move_result, move_call_ns, move_write_ns, move_ack_ns = arbiter.move(
                lambda: acknowledged_precondition_move(
                    precondition, vx=pre["vx_mps"], vy=pre["vy_mps"], vyaw=pre["vyaw_radps"]))
            state, received_ns = sampler.after(move_ack_ns)
            with pose_lock:
                pose = pose_reader.read()
                pose_ns = time.monotonic_ns()
            pose_rows.append({"timestamp_ns": pose_ns, "x_m": pose["x_m"],
                              "y_m": pose["y_m"], "phase": "precondition"})
            events.append({"timestamp_ns": pose_ns, "kind": "precondition_motion",
                           "source_label": pre["source_label"], "index": index,
                           "command_created_at_ns": tick_ns,
                           "request_call_started_at_ns": move_call_ns,
                           "request_socket_write_completed_at_ns": move_write_ns,
                           "robot_move_ack_at_ns": move_ack_ns,
                           "robot_move_result": move_result,
                           "robot_state": robot_state_record(state, received_ns, pose, pose_ns)})
            time.sleep(max(0, pre["command_period_ms"] / 1000 -
                           (time.monotonic_ns() - tick_ns) / 1e9))
        measured = pose_speeds(pose_rows, window_ms=metric["speed_window_ms"],
                               max_window_ms=metric["speed_window_max_ms"])
        motion_confirmed_ns = first_sustained(
            measured, threshold_mps=metric["moving_threshold_mps"],
            duration_ms=metric["moving_confirmation_ms"], at_or_above=True)
        displacement = math.hypot(pose_rows[-1]["x_m"] - pose_rows[0]["x_m"],
                                  pose_rows[-1]["y_m"] - pose_rows[0]["y_m"])
        precondition_status = {
            "motion_first_observed_at_ns": next(
                (r["timestamp_ns"] for r in measured
                 if r["pose_speed_mps"] is not None
                 and r["pose_speed_mps"] >= metric["moving_threshold_mps"]), None),
            "motion_confirmed_at_ns": motion_confirmed_ns,
            "precondition_displacement_m": displacement,
            "precondition_peak_pose_speed_mps": max(
                (r["pose_speed_mps"] or 0 for r in measured), default=0),
            "handoff_pose_speed_mps": measured[-1]["pose_speed_mps"],
            "walk_policy_observed": any(e.get("robot_state", {}).get("policy") == "walk"
                                        for e in events if e["kind"] == "precondition_motion"),
        }
        if (motion_confirmed_ns is None or displacement < pre["minimum_trunk_displacement_m"]
                or (measured[-1]["pose_speed_mps"] or 0) < metric["moving_threshold_mps"]
                or not precondition_status["walk_policy_observed"]):
            raise RuntimeError("bounded precondition did not establish observed moving body")
        transition("MOTION_CONFIRMED", motion_confirmed_ns)
        positive_moves = [e for e in events if e["kind"] == "precondition_motion"]
        last_motion["request_call_ns"] = positive_moves[-1]["request_call_started_at_ns"]
        last_motion["ack_ns"] = positive_moves[-1]["robot_move_ack_at_ns"]
        last_motion["result"] = positive_moves[-1]["robot_move_result"]
        with pose_lock:
            initial_pose = pose_reader.read()
        chain.trial = make_trial(scenario, trial_id=trial_id, seed=seed,
                                 motion="approaching", initial_pose=initial_pose)
        center_x, center_y = sphere_center(scenario, chain.trial, arm_elapsed_s)
        center_distance = math.hypot(center_x - initial_pose["x_m"],
                                     center_y - initial_pose["y_m"])
        sphere_bound = safe_observation_horizon(
            center_distance, scenario["virtual_sphere_radius_m"],
            scenario["approach_speed_m_s"], protocol["maximum_robot_forward_displacement_m"],
            observation_ms=observation_ms,
            margin_ms=protocol["sphere_entry_safety_margin_ms"])
        if not sphere_bound["safe"]:
            raise RuntimeError("frozen neural observation horizon can enter virtual sphere")
        phase_started_ns = time.monotonic_ns()
        transition("NEURAL_OBSERVATION_ARMED", phase_started_ns)
        first_frame = chain.perception(phase_started_ns)
        first_update = chain.neural(first_frame, phase_started_ns)
        ensure_healthy_neutral_priming(chain, first_update)
        if first_update.trace["perception_frame"] != first_frame:
            raise RuntimeError("neutral priming used a different perception frame")
        if not watchdog.observe_neural(first_update.readout) or not watchdog.observe_behavior(first_update.behavior_intent):
            raise RuntimeError("cannot prime healthy watchdog at neural phase handoff")
        cache_prime_call_ns = time.monotonic_ns()
        cached_frame = scheduler.prime_perception(first_frame, now_ns=cache_prime_call_ns)
        if cached_frame != first_update.trace["perception_frame"]:
            raise RuntimeError("scheduler cache differs from neutral priming frame")
        cache_prime_return_ns = time.monotonic_ns()
        events.append({"timestamp_ns": cache_prime_return_ns, "kind": "visual_cache_primed",
                       "frame_id": first_frame["frame_id"],
                       "source_timestamp_ns": first_frame["timestamp_ns"],
                       "cache_prime_call_ns": cache_prime_call_ns,
                       "cache_prime_return_ns": cache_prime_return_ns})

        def refresh_positive_motion():
            index = 0
            while not arbiter.latched.is_set():
                tick_ns = time.monotonic_ns()
                try:
                    result, call_ns, write_ns, ack_ns = arbiter.move(
                        lambda: acknowledged_precondition_move(
                            precondition, vx=pre["vx_mps"], vy=pre["vy_mps"],
                            vyaw=pre["vyaw_radps"]))
                except MotionLatched:
                    break
                except BaseException as error:
                    motion_refresh_errors.append(f"{type(error).__name__}: {error}")
                    arbiter.latch("motion_refresh_fault")
                    first_stop_observed.set()
                    break
                last_motion.update({"request_call_ns": call_ns, "ack_ns": ack_ns,
                                    "result": result})
                row = {"timestamp_ns": ack_ns, "kind": "positive_motion_refresh",
                       "index": index, "request_call_started_at_ns": call_ns,
                       "request_socket_write_completed_at_ns": write_ns,
                       "robot_move_ack_at_ns": ack_ns, "robot_move_result": result}
                motion_refreshes.append(row)
                events.append(row)
                index += 1
                time.sleep(max(0, pre["command_period_ms"] / 1000 -
                               (time.monotonic_ns() - tick_ns) / 1e9))

        motion_thread = threading.Thread(target=refresh_positive_motion,
                                         name="p8-positive-motion-refresh")
        motion_thread.start()
        elapsed_neural_ms = (time.monotonic_ns() - phase_started_ns) / 1e6
        remaining_neural_s = (observation_ms
                              - elapsed_neural_ms) / 1000
        if remaining_neural_s <= 0:
            raise RuntimeError("neural priming consumed frozen observation horizon")
        def run_scheduler():
            nonlocal scheduler_result
            try:
                scheduler_result = scheduler.run(
                    remaining_neural_s + protocol["maximum_post_ack_stop_observation_ms"] / 1000)
            except BaseException as error:
                scheduler_errors.append(f"{type(error).__name__}: {error}")
                arbiter.latch("scheduler_run_fault")
                first_stop_observed.set()

        scheduler_thread = threading.Thread(target=run_scheduler, name="g8-r5d-scheduler")
        scheduler_thread.start()
        first_stop_observed.wait(remaining_neural_s)
        if not first_stop:
            arbiter.latch("neural_observation_timeout")
        motion_thread.join(timeout=3)
        if motion_thread.is_alive() or motion_refresh_errors:
            raise RuntimeError(f"motion refresh failed: {motion_refresh_errors}")
        if not first_stop:
            raise RuntimeError("no robot.stop ACK before frozen neural observation deadline")
        if observer_errors:
            raise RuntimeError(observer_errors[0])
        if scheduler_errors or state_path[-1] != "STOP_REFRESHING":
            raise RuntimeError("no healthy neural stop ACK before frozen observation deadline")
        first_record = first_stop.get("record")
        origin_now = (neural_stop_origin(
            chain, first_record, threshold=protocol["escape_threshold"])
            if first_record is not None else None)
        if origin_now is None:
            raise RuntimeError("first robot-facing stop was not healthy neural escape")
        lineage_now = bounded_neural_lineage(
            chain.neural_ledger, origin_now[2],
            max_age_ms=protocol["maximum_visual_lineage_age_ms"],
            max_runtime_step_gap=protocol["maximum_visual_lineage_runtime_step_gap"])
        if not lineage_now["valid"]:
            raise RuntimeError(f"first stop lacks complete bounded neural lineage: {lineage_now['reason']}")
        stop_ack = first_record["robot_state"]["publish_ack_returned_ns"]
        if any("deadman" in str(reason).lower()
               for reason in first_record["robot_state"]["limited_by"]):
            raise RuntimeError("deadman limiter in first post-stop robot.state sample")
        preceding_state = first_stop.get("state_before")
        preceding_state_ns = first_stop.get("state_before_received_ns")
        stop_call = first_record["robot_state"]["publish_call_started_ns"]
        if (preceding_state is None or type(preceding_state_ns) is not int
                or not 0 <= stop_call - preceding_state_ns
                <= metric["maximum_gap_before_neural_stop_ms"] * 1_000_000
                or not material_pre_stop_applied(
                    preceding_state["move"]["applied"][0],
                    protocol["minimum_fresh_pre_stop_applied_vx_mps"])
                or any("deadman" in str(reason).lower()
                       for reason in preceding_state["move"].get("limited_by", []))):
            raise RuntimeError("fresh pre-stop robot.state does not exclude deadman")
        before_decoder = [row for row in pose_speeds(
            pose_rows, window_ms=metric["speed_window_ms"],
            max_window_ms=metric["speed_window_max_ms"])
            if row["timestamp_ns"] < origin_now[0].neural_timestamp_ns
            and row["pose_speed_mps"] is not None]
        if (not before_decoder
                or origin_now[0].neural_timestamp_ns
                   - before_decoder[-1]["timestamp_ns"]
                   > metric["maximum_gap_before_neural_stop_ms"] * 1_000_000
                or before_decoder[-1]["pose_speed_mps"] < metric["moving_threshold_mps"]):
            raise RuntimeError("actual body was not freshly moving before neural stop")
        deadman_now = deadman_timing(
            last_motion.get("request_call_ns"), last_motion.get("ack_ns"), stop_ack,
            timeout_ms=protocol["deadman_timeout_ms"],
            minimum_margin_ms=protocol["minimum_deadman_margin_ms"])
        if not deadman_now["valid"]:
            raise RuntimeError("robot.stop ACK did not exclude frozen deadman timeout")
        if not arbiter.latched.is_set() or arbiter.first_stop_ack_ns is None:
            raise RuntimeError("motion arbiter did not latch before official stop ACK")
        preceding_applied_vx = preceding_state["move"]["applied"][0]
        reduction_limit = preceding_applied_vx * (
            1 - protocol["minimum_applied_vx_reduction_fraction_after_first_stop"])
        post_deadline_ns = stop_ack + int(protocol["maximum_post_ack_stop_observation_ms"] * 1e6)
        while time.monotonic_ns() < post_deadline_ns:
            sample_start_ns = time.monotonic_ns()
            state, received_ns = sampler.after(sample_start_ns)
            with pose_lock:
                pose = pose_reader.read()
                pose_ns = time.monotonic_ns()
            pose_rows.append({"timestamp_ns": pose_ns, "x_m": pose["x_m"],
                              "y_m": pose["y_m"], "phase": "post_ack_read_only"})
            record_geometry(pose, pose_ns, "post_ack_read_only")
            events.append({"timestamp_ns": pose_ns, "kind": "post_ack_read_only_sample",
                           "robot_state": robot_state_record(state, received_ns, pose, pose_ns)})
            requested = state["move"]["requested"]
            applied_vx = state["move"]["applied"][0]
            limited_by = state["move"].get("limited_by", [])
            if any(value != 0 for value in requested):
                raise RuntimeError("post-ACK requested twist was not exact zero")
            if any("deadman" in str(reason).lower() for reason in limited_by):
                later_deadman_events.append({"timestamp_ns": received_ns,
                                             "limited_by": list(limited_by)})
                raise RuntimeError("deadman limiter before actual stopped confirmation")
            if first_applied_reduction_ns is None and applied_vx <= reduction_limit:
                first_applied_reduction_ns = received_ns
            if (first_applied_near_zero_ns is None
                    and abs(applied_vx) <= protocol["applied_stop_threshold_mps"]):
                first_applied_near_zero_ns = received_ns
            measured = pose_speeds(pose_rows, window_ms=metric["speed_window_ms"],
                                   max_window_ms=metric["speed_window_max_ms"])
            newest_speed = measured[-1]["pose_speed_mps"]
            if (first_stopped_observed_ns is None and pose_ns >= stop_ack
                    and newest_speed is not None
                    and newest_speed <= stopped_rule["stopped_threshold_mps"]):
                first_stopped_observed_ns = pose_ns
            confirmed = first_sustained(
                measured, threshold_mps=stopped_rule["stopped_threshold_mps"],
                duration_ms=stopped_rule["stop_confirmation_ms"],
                at_or_above=False, after_ns=stop_ack)
            if confirmed is not None:
                if first_applied_reduction_ns is None or first_applied_near_zero_ns is None:
                    raise RuntimeError("applied-vx causal deceleration evidence is incomplete")
                transition("MOTION_STOPPED", confirmed)
                transition("COMPLETE", time.monotonic_ns())
                scheduler.request_complete()
                break
        if state_path[-1] != "COMPLETE":
            raise RuntimeError("actual motion did not stop in frozen post-ACK window")
        scheduler_thread.join(timeout=3)
        if scheduler_thread.is_alive() or scheduler_errors or scheduler_result is None:
            raise RuntimeError(f"scheduler did not finish cleanly: {scheduler_errors}")
        if scheduler_result["scheduler_exceptions"] != 0:
            raise RuntimeError("scheduler exception count is nonzero")
        runtime_finished_ns = time.monotonic_ns()
    except BaseException as error:
        runtime_finished_ns = time.monotonic_ns()
        events.append({"timestamp_ns": time.monotonic_ns(), "kind": "fixture_error",
                       "error": f"{type(error).__name__}: {error}"})
    finally:
        arbiter.latch("cleanup")
        if 'motion_thread' in locals():
            motion_thread.join(timeout=3)
        if scheduler._threads and not scheduler._fixture_complete.is_set():
            scheduler._stop.set()
            scheduler._fixture_wake.set()
        if 'scheduler_thread' in locals():
            scheduler_thread.join(timeout=3)
        pending.put(None)
        pending.join()
        observer.join(timeout=5)
        try:
            cleanup_kind = ("cleanup_stop_after_complete" if state_path[-1] == "COMPLETE"
                            else "safe_abort_stop")
            cleanup_result = precondition.request("robot.stop", {})
            events.append({"timestamp_ns": time.monotonic_ns(), "kind": cleanup_kind,
                           "robot_stop_result": cleanup_result})
        except BaseException as error:
            events.append({"timestamp_ns": time.monotonic_ns(), "kind": "cleanup_error",
                           "error": f"{type(error).__name__}: {error}"})
        health_after = robot.health()
        precondition.close()
        pose_reader.close()
        sampler.close()
        robot.close()

    records = telemetry.records()
    events.extend(chain.discarded_visual_after_ack)
    args.raw.parent.mkdir(parents=True, exist_ok=True)
    trace_artifact = telemetry.write(args.raw) if records else None
    args.ledger.parent.mkdir(parents=True, exist_ok=True)
    args.ledger.write_text("".join(json.dumps(row, sort_keys=True, separators=(",", ":"),
                                           allow_nan=False) + "\n"
                                   for row in chain.neural_ledger), encoding="ascii")
    args.visual.parent.mkdir(parents=True, exist_ok=True)
    args.visual.write_text("".join(json.dumps(row, sort_keys=True, separators=(",", ":"),
                                           allow_nan=False) + "\n"
                                   for row in chain.visual_frames), encoding="ascii")
    all_speeds = pose_speeds(pose_rows, window_ms=metric["speed_window_ms"],
                             max_window_ms=metric["speed_window_max_ms"])
    neural = [row for row in chain.neural_ledger
              if row.get("raw_decoder_stop")
              and row.get("post_safety_stop")
              and row.get("dn_runtime_healthy")
              and row.get("dn_escape", 0) >= protocol["escape_threshold"]]
    first_stop_state_before = first_stop.get("state_before")
    first_stop_state_before_ns = first_stop.get("state_before_received_ns")
    first_stop = next((record for record in records if record["robot_facing_stop"]), None)
    first_actual_stop_event = next((e for e in events if e["kind"] == "control_publish"
                                    and e["robot_facing_stop"]
                                    and e["transport_action"] == "robot_stop_refreshed"), None)
    origin = (neural_stop_origin(chain, first_stop, threshold=protocol["escape_threshold"])
              if first_stop is not None else None)
    first_stop_is_neural = bool(origin and first_actual_stop_event
                                and first_stop["sequence"] == first_actual_stop_event["sequence"])
    first_neural = first_stop if first_stop_is_neural else None
    stop_created_ns = origin[0].neural_timestamp_ns if origin else None
    stop_ack_ns = first_stop["robot_state"]["publish_ack_returned_ns"] if first_stop_is_neural else None
    pre_stop_speeds = [row for row in all_speeds if stop_created_ns and row["timestamp_ns"] < stop_created_ns
                       and row["pose_speed_mps"] is not None]
    latest_pre_stop = pre_stop_speeds[-1] if pre_stop_speeds else None
    pre_stop_displacement = (math.hypot(pre_stop_speeds[-1]["x_m"] - pose_rows[0]["x_m"],
                                        pre_stop_speeds[-1]["y_m"] - pose_rows[0]["y_m"])
                             if pre_stop_speeds else None)
    pre_stop_moving = bool(latest_pre_stop
                           and stop_created_ns - latest_pre_stop["timestamp_ns"]
                           <= metric["maximum_gap_before_neural_stop_ms"] * 1_000_000
                           and latest_pre_stop["pose_speed_mps"] >= metric["moving_threshold_mps"])
    stopped_confirmed_ns = (first_sustained(
        all_speeds, threshold_mps=stopped_rule["stopped_threshold_mps"],
        duration_ms=stopped_rule["stop_confirmation_ms"], at_or_above=False,
        after_ns=stop_ack_ns)
        if stop_ack_ns is not None else None)
    post_stop_speeds = [row for row in all_speeds if stop_ack_ns is not None
                        and row["timestamp_ns"] >= stop_ack_ns]
    confirmed_sample = next((row for row in post_stop_speeds
                             if row["timestamp_ns"] == stopped_confirmed_ns), None)
    first_stopped_ns = first_stopped_observed_ns
    last_nonzero_ns = next((row["timestamp_ns"] for row in reversed(post_stop_speeds)
                            if row["pose_speed_mps"] is not None
                            and row["pose_speed_mps"] > stopped_rule["stopped_threshold_mps"]), None)
    violation_count = sum(
        not math.isfinite(row["robot_facing_vx"]) or not math.isfinite(row["robot_facing_vyaw"])
        or abs(row["robot_facing_vx"]) > .08 or row["robot_facing_vy"] != 0
        or abs(row["robot_facing_vyaw"]) > .5 for row in records)
    violation_count += sum(
        any(not math.isfinite(value) for value in e["robot_state"]["requested_velocity"]
            + e["robot_state"]["applied_velocity"])
        or abs(e["robot_state"]["requested_velocity"][0]) > .08
        or e["robot_state"]["requested_velocity"][1] != 0
        or abs(e["robot_state"]["requested_velocity"][2]) > .5
        for e in events if e["kind"] == "precondition_motion")
    violation_count += sum(
        any(not math.isfinite(value) for value in e["robot_state"]["requested_velocity"]
            + e["robot_state"]["applied_velocity"])
        or abs(e["robot_state"]["requested_velocity"][0]) > .08
        or e["robot_state"]["requested_velocity"][1] != 0
        or abs(e["robot_state"]["requested_velocity"][2]) > .5
        for e in events if e["kind"] == "post_ack_read_only_sample")
    lplc2_peak = max((max(row["stimulus_channels"]["lplc2_left"],
                          row["stimulus_channels"]["lplc2_right"]) for row in records), default=0)
    looming_peak = max((row["perception"]["looming"] for row in records), default=0)
    escape_peak = max((row["dn_activity"]["escape"] for row in records), default=0)
    first_looming_ns = next((e["neural_trace"]["perception_frame"]["timestamp_ns"]
                             for e in events if e["kind"] == "control_publish"
                             and e.get("neural_trace", {}).get("perception_frame", {}).get("looming", 0) > 0), None)
    first_lplc2_ns = next((e["neural_trace"]["dn_readout"]["timestamp_ns"]
                           for e in events if e["kind"] == "control_publish"
                           and e.get("neural_trace", {}).get("stimulus_channels", {}).get("lplc2_left", 0) > 0
                           or e["kind"] == "control_publish"
                           and e.get("neural_trace", {}).get("stimulus_channels", {}).get("lplc2_right", 0) > 0), None)
    first_escape_ns = next((r["dn_timestamp_ns"] for r in chain.neural_ledger
                            if r.get("dn_escape", 0) >= protocol["escape_threshold"]), None)
    scheduler_exceptions = scheduler_result["scheduler_exceptions"] if scheduler_result else None
    precondition_rows = [e for e in events if e["kind"] == "precondition_motion"]
    precondition_call_gaps_ms = [
        (b["request_call_started_at_ns"] - a["request_call_started_at_ns"]) / 1e6
        for a, b in zip(precondition_rows, precondition_rows[1:])]
    max_precondition_call_gap_ms = max(precondition_call_gaps_ms, default=None)
    precondition_deadman_limited = precondition_deadman_after_motion(
        precondition_rows,
        precondition_status["motion_confirmed_at_ns"] if precondition_status else None)
    startup_deadman_markers = sum(
        1 for row in precondition_rows
        if any("deadman" in str(reason).lower()
               for reason in row["robot_state"]["limited_by"])
        and precondition_status is not None
        and row["robot_state"].get("robot_t_ns") is not None
        and row["robot_state"]["robot_t_ns"]
            < precondition_status["motion_confirmed_at_ns"])
    deadman = deadman_timing(
        last_motion.get("request_call_ns"), last_motion.get("ack_ns"), stop_ack_ns,
        timeout_ms=protocol["deadman_timeout_ms"],
        minimum_margin_ms=protocol["minimum_deadman_margin_ms"])
    lineage = (bounded_neural_lineage(
        chain.neural_ledger, origin[2],
        max_age_ms=protocol["maximum_visual_lineage_age_ms"],
        max_runtime_step_gap=protocol["maximum_visual_lineage_runtime_step_gap"])
        if origin is not None else {"valid": False, "reason": "missing_neural_origin"})
    last_move_ack_to_stop_ack_ms = deadman["age_from_ack_ms"]
    pre_stop_limited_by = (first_stop_state_before or {}).get("move", {}).get("limited_by", [])
    pre_stop_applied_vx = (first_stop_state_before or {}).get("move", {}).get("applied", [None])[0]
    stop_call_ns = (first_neural["robot_state"]["publish_call_started_ns"]
                    if first_neural else None)
    fresh_state_before_stop = bool(type(first_stop_state_before_ns) is int
                                   and stop_call_ns is not None
                                   and 0 <= stop_call_ns - first_stop_state_before_ns
                                   <= metric["maximum_gap_before_neural_stop_ms"] * 1_000_000)
    transition_states = [e["state"] for e in events if e["kind"] == "transition"]
    post_ack_commands = [e for e in events if e["kind"] in ("control_publish", "stop_refresh_ack")
                         and first_actual_stop_event is not None
                         and e["timestamp_ns"] > first_actual_stop_event["timestamp_ns"]
                         and e["transport_action"] != SUPPRESSED_NEUTRAL]
    state_samples_for_audit = [e["robot_state"] for e in events
                               if e["kind"] in ("control_publish", "post_ack_read_only_sample")
                               and e.get("robot_state") is not None]
    deadman_before_stopped = deadman_limiter_seen_before_stopped(
        state_samples_for_audit, stopped_confirmed_ns)
    cadence = stop_refresh_cadence(
        [row for row in stop_refreshes if stopped_confirmed_ns is None
         or row["ack_at_ns"] <= stopped_confirmed_ns],
        maximum_gap_ms=protocol["maximum_stop_refresh_gap_ms"],
        deadman_timeout_ms=protocol["deadman_timeout_ms"],
        stopped_confirmed_ns=stopped_confirmed_ns)

    def sampled_boundary(event_ns):
        if event_ns is None or not pose_rows or chain.started_ns is None:
            return None
        samples = sorted(pose_rows, key=lambda item: item["timestamp_ns"])
        before = next((row for row in reversed(samples)
                       if row["timestamp_ns"] <= event_ns), None)
        after = next((row for row in samples
                      if row["timestamp_ns"] >= event_ns), None)
        if before is not None and after is not None:
            gap_ns = after["timestamp_ns"] - before["timestamp_ns"]
            if gap_ns > 100_000_000:
                return None
            weight = ((event_ns - before["timestamp_ns"]) / gap_ns
                      if gap_ns else 0.0)
            x = before["x_m"] + weight * (after["x_m"] - before["x_m"])
            y = before["y_m"] + weight * (after["y_m"] - before["y_m"])
            method = "bracketed_linear_pose_interpolation"
            uncertainty_ms = gap_ns / 1e6
        else:
            nearest = before or after
            uncertainty_ms = abs(nearest["timestamp_ns"] - event_ns) / 1e6
            if uncertainty_ms > 100:
                return None
            x, y = nearest["x_m"], nearest["y_m"]
            method = "nearest_pose_sample"
        elapsed_s = arm_elapsed_s + max(0.0, (event_ns - chain.started_ns) / 1e9)
        center_x, center_y = sphere_center(scenario, chain.trial, elapsed_s)
        distance = math.hypot(center_x - x, center_y - y)
        return {"margin_m": distance - scenario["safety_boundary_center_distance_m"],
                "distance_m": distance, "event_timestamp_ns": event_ns,
                "pose_method": method, "pose_gap_bound_ms": uncertainty_ms,
                "scenario_elapsed_s": elapsed_s}

    refresh_call_gaps_ms = [
        (b["request_call_started_at_ns"] - a["request_call_started_at_ns"]) / 1e6
        for a, b in zip(motion_refreshes, motion_refreshes[1:])]
    trigger_boundary = sampled_boundary(stop_created_ns)
    request_boundary = sampled_boundary(stop_call_ns)
    visual_frame_gaps_ms = [
        (b["timestamp_ns"] - a["timestamp_ns"]) / 1e6
        for a, b in zip(chain.visual_frames, chain.visual_frames[1:])]
    visual_ages_ms = [
        (row["neural_call_started_ns"] - row["perception_timestamp_ns"]) / 1e6
        for row in chain.neural_ledger
        if row.get("perception_valid") and type(row.get("perception_timestamp_ns")) is int]
    checks = {
        "precondition_motion_confirmed": bool(precondition_status and precondition_status["motion_confirmed_at_ns"]),
        "precondition_cadence_and_deadman": (len(precondition_rows) == round(
            pre["duration_s"] * 1000 / pre["command_period_ms"])
            and max_precondition_call_gap_ms is not None
            and max_precondition_call_gap_ms <= pre["maximum_command_call_gap_ms"]
            and not precondition_deadman_limited),
        "pre_stop_body_still_moving": pre_stop_moving,
        "positive_motion_refresh_cadence": bool(motion_refreshes and
            max(refresh_call_gaps_ms, default=0) <= pre["maximum_command_call_gap_ms"]),
        "no_move_after_neural_latch": bool(arbiter.latch_at_ns and
            all(row["call_ns"] <= arbiter.latch_at_ns
                for row in arbiter.move_transactions) and
            all(row["ack_ns"] <= arbiter.first_stop_ack_ns
                for row in arbiter.move_transactions) if arbiter.first_stop_ack_ns else False),
        "trigger_before_frozen_boundary": bool(trigger_boundary and
            trigger_boundary["margin_m"] > 0 and
            trigger_boundary["pose_gap_bound_ms"] <= 100),
        "stop_request_before_frozen_boundary": bool(request_boundary and
            request_boundary["margin_m"] > 0 and
            request_boundary["pose_gap_bound_ms"] <= 100),
        "continuous_valid_rgb": bool(chain.visual_frames and
            all(row["perception_valid"] for row in chain.visual_frames) and
            visual_frame_gaps_ms and max(visual_frame_gaps_ms) <=
            protocol.get("maximum_official_visual_frame_gap_ms", 150) and
            abs(sum(visual_frame_gaps_ms) / len(visual_frame_gaps_ms)
                - 1000 / visual_hz) <= 20),
        "healthy_neural_stop_first": first_stop_is_neural,
        "bounded_temporal_neural_lineage": first_stop_is_neural and lineage["valid"],
        "robot_stop_ack": stop_ack_ns is not None,
        "neural_stop_ack_confirmed": bool(
            chain.neural_stop_latch.snapshot()
            and chain.neural_stop_latch.snapshot().first_healthy_stop_ack_ns == stop_ack_ns),
        "deadman_excluded": deadman["valid"] and last_move_ack_to_stop_ack_ms is not None
                            and last_move_ack_to_stop_ack_ms <= protocol["maximum_last_motion_ack_to_stop_ack_ms"]
                            and fresh_state_before_stop
                            and material_pre_stop_applied(
                                pre_stop_applied_vx,
                                protocol["minimum_fresh_pre_stop_applied_vx_mps"])
                            and first_applied_reduction_ns is not None
                            and first_applied_near_zero_ns is not None
                            and deadman_before_stopped is False
                            and not any("deadman" in str(reason).lower()
                                        for reason in pre_stop_limited_by),
        "production_stop_refresh_cadence": cadence["valid"],
        "continuous_visual_after_stop_ack": bool(stop_ack_ns and any(
            row["timestamp_ns"] > stop_ack_ns for row in chain.visual_frames)),
        "continuous_neural_after_stop_ack": bool(stop_ack_ns and any(
            row.get("dn_timestamp_ns", 0) > stop_ack_ns
            for row in chain.neural_ledger)),
        "neutral_only_suppression": isolated_publisher.nonzero_count == 0,
        "sphere_horizon_safe": bool(sphere_bound and sphere_bound["safe"]),
        "sphere_clearance_and_body_displacement": bool(geometry_rows and all(
            r["sphere_surface_clearance_m"] > protocol["minimum_center_clearance_after_ack_m"]
            and r["robot_forward_displacement_m"] <= protocol["maximum_robot_forward_displacement_m"]
            for r in geometry_rows)),
        "post_ack_transport_stop_only": (len(post_ack_commands) >= 1
            and all(e["transport_action"] == "robot_stop_refreshed" for e in post_ack_commands)
            and isolated_publisher.post_stop_move_count == 0),
        "actual_stopped_confirmed": stopped_confirmed_ns is not None,
        "safety_bounds": violation_count == protocol["safety_limit_violations_max"],
        "scheduler_healthy": scheduler_exceptions == protocol["scheduler_exceptions_max"],
        "no_fault_stop": fault_latch.snapshot() is None,
        "robotd_healthy": bool(health_before["healthy"] and health_after["healthy"]),
        "timing_reconstructible": causal_timeline_ok(
            precondition_status["motion_confirmed_at_ns"] if precondition_status else None,
            phase_started_ns, first_looming_ns, first_lplc2_ns, first_escape_ns, stop_created_ns,
            first_neural["timestamp_ns"] if first_neural else None,
            first_neural["robot_state"]["publish_call_started_ns"] if first_neural else None,
            stop_ack_ns, stopped_confirmed_ns),
        "within_frozen_trial_duration": (runtime_finished_ns - started_ns) / 1e9
                                         <= protocol["maximum_total_trial_duration_s"],
        "state_machine_complete": valid_state_path(transition_states, complete=True),
    }
    if protocol["schema_version"] in ("p8-r3-v22-official-development-v1",
                                       "p8-r3-v23-official-development-v1",
                                       "p8-r3-v24-official-development-v1"):
        checks["visual_age_within_ttl"] = bool(
            len(visual_ages_ms) == len(chain.neural_ledger)
            and all(0 <= age <= protocol["maximum_visual_lineage_age_ms"]
                    for age in visual_ages_ms))
    if protocol["schema_version"] in ("p8-r3-v23-official-development-v1",
                                       "p8-r3-v24-official-development-v1"):
        checks["continuous_neural_visual_input"] = bool(chain.neural_ledger and all(
            not row.get("input_none") and not row.get("result_none")
            and row.get("perception_valid") and row.get("perception_age_ms") is not None
            for row in chain.neural_ledger))
    transport_checks = {key: value for key, value in checks.items()
                        if key != "trigger_before_frozen_boundary"}
    result = "PASS" if all(checks.values()) and not observer_errors else "FAIL"
    behavior_result = result
    primary_screen_checks = {
        "moving_before_trigger": checks["precondition_motion_confirmed"]
                                 and bool(pre_stop_applied_vx is not None and
                                          pre_stop_applied_vx >= protocol["minimum_fresh_pre_stop_applied_vx_mps"])
                                 and bool(latest_pre_stop and
                                          latest_pre_stop["pose_speed_mps"] >= metric["moving_threshold_mps"]),
        "healthy_neural_lineage": checks["healthy_neural_stop_first"]
                                  and checks["bounded_temporal_neural_lineage"],
        "before_frozen_boundary": checks["trigger_before_frozen_boundary"],
        "stop_request_before_frozen_boundary": checks["stop_request_before_frozen_boundary"],
        "no_prior_fault_or_deadman": checks["no_fault_stop"]
                                     and deadman_before_stopped is False
                                     and not any("deadman" in str(reason).lower()
                                                 for reason in pre_stop_limited_by),
        "safety_bounds": checks["safety_bounds"],
    }
    primary_screen_result = "PASS" if all(primary_screen_checks.values()) else "FAIL"
    events.sort(key=lambda item: item["timestamp_ns"])
    args.events.parent.mkdir(parents=True, exist_ok=True)
    args.events.write_text("".join(json.dumps(row, sort_keys=True, separators=(",", ":"),
                                        allow_nan=False) + "\n" for row in events), encoding="ascii")
    summary = {
        "schema_version": "p8-r3-official-trial-v1", "result": result,
        "validity_class": ("ARMED" if "NEURAL_OBSERVATION_ARMED" in transition_states
                           else "PRE_ARM_REVIEW"),
        "behavior_result": behavior_result,
        "r3_official_screen_result": primary_screen_result,
        "r3_official_screen_checks": primary_screen_checks,
        "encoder": protocol["selected_v2"],
        "visual_representation": protocol["visual_representation"],
        "visual_hz": protocol["visual_hz"],
        "protocol_schema_version": protocol["schema_version"],
        "scenario_config_sha256": protocol["scenario_config_sha256"],
        "maximum_neural_observation_ms": observation_ms,
        "transport_checks": transport_checks,
        "evidence_role": "development_probe",
        "source_checkout_uncommitted": False,
        "trial_id": trial_id, "seed": seed, "execution_target": "Thor",
        "arm_elapsed_s": arm_elapsed_s,
        "project_commit": args.source_head, "protocol_sha256": sha(protocol_path),
        "graph_sha256": protocol["graph_sha256"],
        "graph_manifest_sha256": protocol["graph_manifest_sha256"],
        "microduck_commit": protocol["microduck_commit"],
        "microduck_rl_commit": protocol["microduck_rl_commit"],
        "walking_policy_sha256": protocol["walking_policy_sha256"],
        "walking_policy_readback_sha256": sha(args.policy_readback),
        "identity": identity, "precondition": precondition_status,
        "precondition_max_command_call_gap_ms": max_precondition_call_gap_ms,
        "precondition_deadman_limited": precondition_deadman_limited,
        "precondition_startup_deadman_marker_count": startup_deadman_markers,
        "motion_confirmed_at_ns": precondition_status["motion_confirmed_at_ns"] if precondition_status else None,
        "motion_first_observed_at_ns": precondition_status["motion_first_observed_at_ns"] if precondition_status else None,
        "last_precondition_move_request_call_started_at_ns": last_motion.get("request_call_ns"),
        "last_precondition_move_ack_at_ns": last_motion.get("ack_ns"),
        "last_precondition_move_result": last_motion.get("result"),
        "motion_arbiter_latch_reason": arbiter.latch_reason,
        "motion_arbiter_latch_at_ns": arbiter.latch_at_ns,
        "healthy_neural_stop_latch": (asdict(chain.neural_stop_latch.snapshot())
                                      if chain.neural_stop_latch.snapshot() else None),
        "post_ack_nonstop_decoder_output_held_count": sum(
            row.get("dn_timestamp_ns", 0) > stop_ack_ns
            and row.get("held_nonstop_decoder_output")
            and row.get("post_safety_stop")
            for row in chain.neural_ledger) if stop_ack_ns else 0,
        "fault_stop_latch": (asdict(fault_latch.snapshot())
                             if fault_latch.snapshot() else None),
        "motion_refresh_count": len(motion_refreshes),
        "motion_refresh_max_call_gap_ms": max(refresh_call_gaps_ms, default=None),
        "motion_refresh_errors": motion_refresh_errors,
        "positive_move_after_latch_count": sum(
            row["call_ns"] > arbiter.latch_at_ns for row in arbiter.move_transactions
        ) if arbiter.latch_at_ns else None,
        "positive_move_ack_after_first_stop_ack_count": sum(
            row["ack_ns"] > arbiter.first_stop_ack_ns for row in arbiter.move_transactions
        ) if arbiter.first_stop_ack_ns else None,
        "deadman_timeout_ms": protocol["deadman_timeout_ms"],
        "deadman_limiter_seen_before_stopped": deadman_before_stopped,
        "stop_refresh_count": cadence["count"],
        "stop_refresh_ack_timestamps_ns": cadence["ack_timestamps_ns"],
        "stop_refresh_requests": stop_refreshes,
        "max_stop_refresh_gap_ms": cadence["max_gap_ms"],
        "mean_stop_refresh_gap_ms": cadence["mean_gap_ms"],
        "stop_refresh_tail_to_stopped_ms": cadence["tail_to_stopped_ms"],
        "maximum_allowed_stop_refresh_gap_ms": protocol["maximum_stop_refresh_gap_ms"],
        "first_applied_vx_reduction_at_ns": first_applied_reduction_ns,
        "first_applied_vx_near_zero_at_ns": first_applied_near_zero_ns,
        "applied_vx_near_zero_threshold_mps": protocol["applied_stop_threshold_mps"],
        "later_deadman_events": later_deadman_events,
        "deadman_margin_ms": deadman["margin_from_call_ms"],
        "last_motion_call_to_stop_ack_ms": deadman["age_from_call_ms"],
        "last_motion_ack_to_stop_ack_ms": last_move_ack_to_stop_ack_ms,
        "pre_stop_robot_state_limited_by": pre_stop_limited_by,
        "pre_stop_robot_state_applied_vx_mps": pre_stop_applied_vx,
        "pre_stop_robot_state_sample_at_ns": first_stop_state_before_ns,
        "pre_stop_robot_state_sample_age_ms": ((stop_call_ns - first_stop_state_before_ns) / 1e6
                                               if stop_call_ns is not None
                                               and first_stop_state_before_ns is not None else None),
        "looming_phase_started_at_ns": phase_started_ns,
        "looming_first_nonzero_at_ns": first_looming_ns,
        "lplc2_first_nonzero_at_ns": first_lplc2_ns,
        "dn_escape_threshold_crossed_at_ns": first_escape_ns,
        "decoder_stop_created_at_ns": stop_created_ns,
        "watchdog_stop_created_at_ns": first_neural["timestamp_ns"] if first_neural else None,
        "robot_stop_rpc_call_started_ns": first_neural["robot_state"]["publish_call_started_ns"] if first_neural else None,
        "robot_stop_rpc_ack_returned_ns": stop_ack_ns,
        "boundary_at_decoder_stop": trigger_boundary,
        "boundary_at_first_stop_request": request_boundary,
        "boundary_at_first_looming": sampled_boundary(first_looming_ns),
        "boundary_at_first_lplc2": sampled_boundary(first_lplc2_ns),
        "boundary_at_first_dn_escape": sampled_boundary(first_escape_ns),
        "boundary_at_stop_ack": sampled_boundary(stop_ack_ns),
        "boundary_at_stopped_confirmation": sampled_boundary(stopped_confirmed_ns),
        "robot_stop_rpc_exact_socket_write_ns": None,
        "first_stopped_state_at_ns": first_stopped_ns,
        "last_nonzero_velocity_at_ns": last_nonzero_ns,
        "stopped_confirmed_at_ns": stopped_confirmed_ns,
        "motion_stop_latency_ms": (stopped_confirmed_ns - stop_ack_ns) / 1e6
                                  if stopped_confirmed_ns and stop_ack_ns else None,
        "pre_stop_pose_speed_mps": latest_pre_stop["pose_speed_mps"] if latest_pre_stop else None,
        "pre_stop_displacement_m": pre_stop_displacement,
        "pre_stop_speed_sample_at_ns": latest_pre_stop["timestamp_ns"] if latest_pre_stop else None,
        "pre_stop_speed_sample_age_ms": ((stop_created_ns - latest_pre_stop["timestamp_ns"]) / 1e6
                                         if stop_created_ns is not None and latest_pre_stop else None),
        "post_stop_confirmed_pose_speed_mps": confirmed_sample["pose_speed_mps"] if confirmed_sample else None,
        "peak_looming": looming_peak, "peak_lplc2_stimulus": lplc2_peak,
        "peak_dn_escape": escape_peak, "neural_stop_count": len(neural),
        "bounded_neural_lineage": lineage,
        "first_stop_source": "healthy_neural_escape" if first_stop_is_neural else
                             (first_actual_stop_event["watchdog_state"]
                              if first_actual_stop_event else None),
        "neutral_publish_suppressed_count": isolated_publisher.suppressed_count,
        "unexpected_nonzero_publish_count": isolated_publisher.nonzero_count,
        "post_ack_robot_facing_command_count_before_complete": len(post_ack_commands),
        "post_stop_robot_move_count": isolated_publisher.post_stop_move_count,
        "discarded_visual_after_ack": chain.discarded_visual_after_ack,
        "sphere_entry_bound": sphere_bound,
        "post_ack_virtual_center": post_ack_virtual_center or None,
        "visual_frame_count": len(chain.visual_frames),
        "visual_max_frame_gap_ms": max(visual_frame_gaps_ms, default=None),
        "visual_mean_frame_gap_ms": (sum(visual_frame_gaps_ms) / len(visual_frame_gaps_ms)
                                     if visual_frame_gaps_ms else None),
        "visual_max_neural_frame_age_ms": max(visual_ages_ms, default=None),
        "visual_neural_missing_count": sum(row.get("input_none", False)
                                            or row.get("result_none", False)
                                            for row in chain.neural_ledger),
        "visual_neural_invalid_count": sum(not row.get("result_none", False)
                                            and not row.get("perception_valid", False)
                                            for row in chain.neural_ledger),
        "visual_neural_age_count": len(visual_ages_ms),
        "visual_after_ack_count": sum(row["timestamp_ns"] > stop_ack_ns
                                      for row in chain.visual_frames) if stop_ack_ns else None,
        "visual_frame_artifact": {"path": str(args.visual), "sha256": sha(args.visual),
                                  "record_count": len(chain.visual_frames),
                                  "bytes": args.visual.stat().st_size},
        "geometry_min_surface_clearance_m": min(
            (r["sphere_surface_clearance_m"] for r in geometry_rows), default=None),
        "geometry_max_forward_displacement_m": max(
            (r["robot_forward_displacement_m"] for r in geometry_rows), default=None),
        "complete_transition_observed": "COMPLETE" in transition_states,
        "complete_transition_at_ns": next((e["timestamp_ns"] for e in events
                                            if e["kind"] == "transition" and e["state"] == "COMPLETE"), None),
        "safety_limit_violations": violation_count, "scheduler_exceptions": scheduler_exceptions,
        "scheduler_result_available": scheduler_result is not None,
        "fixture_exceptions": [e["error"] for e in events if e["kind"] == "fixture_error"],
        "scheduler_errors": scheduler_errors,
        "scheduler": scheduler_result, "checks": checks,
        "health_before": health_before, "health_after": health_after,
        "observer_errors": observer_errors,
        "trace_artifact": {"path": str(args.raw), "sha256": trace_artifact["sha256"],
                           "record_count": trace_artifact["record_count"],
                           "start_timestamp_ns": trace_artifact["start_timestamp_ns"],
                           "end_timestamp_ns": trace_artifact["end_timestamp_ns"],
                           "bytes": args.raw.stat().st_size} if trace_artifact else None,
        "events_artifact": {"path": str(args.events), "sha256": sha(args.events),
                            "record_count": len(events), "bytes": args.events.stat().st_size,
                            "start_timestamp_ns": events[0]["timestamp_ns"],
                            "end_timestamp_ns": events[-1]["timestamp_ns"]},
        "neural_ledger_artifact": {"path": str(args.ledger), "sha256": sha(args.ledger),
                                   "record_count": len(chain.neural_ledger),
                                   "bytes": args.ledger.stat().st_size,
                                   "start_timestamp_ns": (chain.neural_ledger[0]["neural_call_timestamp_ns"]
                                                          if chain.neural_ledger else None),
                                   "end_timestamp_ns": (chain.neural_ledger[-1]["neural_call_timestamp_ns"]
                                                        if chain.neural_ledger else None)},
        "timing_limits": ["request-form precondition robot.move has official acknowledgement",
                          "exact robot.stop socket-write instant unavailable; call start and ACK return bracket it",
                          "robot.state odometry velocity unavailable; official MuJoCo pose-derived speed is primary"],
    }
    write_json(args.summary, summary)
    print(json.dumps({"trial_id": trial_id, "result": result, "checks": checks,
                      "pre_stop_pose_speed_mps": summary["pre_stop_pose_speed_mps"],
                      "neural_stop_count": len(neural)}, sort_keys=True))
    return 0 if result == "PASS" else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--protocol", type=Path, required=True)
    ap.add_argument("--trial-index", type=int, choices=range(3), required=True)
    ap.add_argument("--socket", required=True)
    ap.add_argument("--body-port", type=int, required=True)
    ap.add_argument("--microduck", type=Path, required=True)
    ap.add_argument("--microduck-rl", type=Path, required=True)
    ap.add_argument("--source-head", required=True)
    ap.add_argument("--policy-readback", type=Path, required=True)
    ap.add_argument("--raw", type=Path, required=True)
    ap.add_argument("--events", type=Path, required=True)
    ap.add_argument("--ledger", type=Path, required=True)
    ap.add_argument("--visual", type=Path, required=True)
    ap.add_argument("--summary", type=Path, required=True)
    args = ap.parse_args()
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
