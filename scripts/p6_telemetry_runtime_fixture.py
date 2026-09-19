"""Capture P6-05 full-chain telemetry against official robotd/MuJoCo on Thor."""

from __future__ import annotations

import argparse
from collections import Counter
import copy
import hashlib
import json
import math
from pathlib import Path
import platform
import socket
import subprocess
import threading
import time

from microduck_connectome.dn_aggregator import DNActivityAggregator, load_dn_readout_config
from microduck_connectome.escape_decoder import EscapeDecoder, load_escape_decoder_config
from microduck_connectome.graph import ConnectomeGraph
from microduck_connectome.motion_adapter import RobotMotionAdapter
from microduck_connectome.perception_compositor import PerceptionPipeline
from microduck_connectome.robotd_client import RobotdClient
from microduck_connectome.safety_clamp import SafetyClamp, load_safety_envelope
from microduck_connectome.scheduler import ClosedLoopScheduler, NeuralUpdate
from microduck_connectome.sensory_mapping import SensoryMapper, load_sensory_mapping_config
from microduck_connectome.sparse_runtime import SparseNeuralRuntime
from microduck_connectome.steering_decoder import SteeringDecoder, load_steering_decoder_config
from microduck_connectome.telemetry import EndToEndTelemetry, build_run_identity
from microduck_connectome.watchdog import ControllerWatchdog


def git_head(path: Path) -> str:
    return subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()


def quaternion_yaw(wxyz) -> float:
    w, x, y, z = wxyz
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


class BodyReader:
    """Read MuJoCo state only; the controller never writes the body interface."""

    def __init__(self, port: int):
        self.socket = socket.create_connection(("127.0.0.1", port), timeout=2.0)
        self.file = self.socket.makefile("rwb")
        self.file.write(b'{"op":"hello","protocol":1,"joints":15}\n')
        self.file.flush()
        if json.loads(self.file.readline()) != {"protocol": 1}:
            raise RuntimeError("unexpected MuJoCo body hello")

    def read(self) -> dict:
        self.file.write(b'{"op":"read"}\n')
        self.file.flush()
        value = json.loads(self.file.readline())
        return {
            "heading_rad": quaternion_yaw(value["imu"]["quat"]),
            "trunk_quaternion_wxyz": value["imu"]["quat"],
            "trunk_z": value["trunk_z"],
        }

    def close(self) -> None:
        self.file.close()
        self.socket.close()


class RobotStateSampler:
    """Keep actual robot.state notifications off the 50 Hz controller socket."""

    def __init__(self, socket_path: str):
        self.client = RobotdClient(socket_path, timeout_s=2.0)
        self.client.connect()
        self.condition = threading.Condition()
        self.latest = None
        self.received_ns = None
        self.error = None
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, name="p6-05-state", daemon=False)
        self.thread.start()

    def _run(self):
        try:
            while not self.stop.is_set():
                state = self.client.state(hz=50)
                received_ns = time.monotonic_ns()
                with self.condition:
                    self.latest = copy.deepcopy(state)
                    self.received_ns = received_ns
                    self.condition.notify_all()
        except BaseException as error:
            if not self.stop.is_set():
                with self.condition:
                    self.error = error
                    self.condition.notify_all()

    def after(self, timestamp_ns: int) -> tuple[dict, int]:
        deadline = time.monotonic() + 0.15
        with self.condition:
            while self.error is None and (self.received_ns is None or self.received_ns < timestamp_ns):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError("no post-command robot.state within 150 ms")
                self.condition.wait(remaining)
            if self.error is not None:
                raise RuntimeError("robot.state sampler failed") from self.error
            return copy.deepcopy(self.latest), self.received_ns

    def close(self):
        self.stop.set()
        self.client.close()
        self.thread.join(timeout=2.0)


class FullChain:
    def __init__(self, root: Path, graph: ConnectomeGraph):
        self.pipeline = PerceptionPipeline()
        sensory_config = load_sensory_mapping_config(root / "config" / "sensory_mapping_v1.json")
        sensory_ids = tuple(sorted(body_id for spec in sensory_config["populations"].values() for body_id in spec["body_ids"]))
        self.mapper = SensoryMapper(sensory_ids, sensory_config)
        self.runtime = SparseNeuralRuntime(graph, json.loads((root / "config" / "neural_model_v1.json").read_text()))
        dn_config = load_dn_readout_config(root / "config" / "dn_readout_v1.json")
        self.dn_ids = tuple(sorted(body_id for spec in dn_config["populations"].values() for body_id in spec["body_ids"]))
        self.aggregator = DNActivityAggregator(self.dn_ids, dn_config)
        self.runtime_index = {body_id: index for index, body_id in enumerate(graph.body_ids)}
        self.steering = SteeringDecoder(load_steering_decoder_config(root / "config" / "steering_decoder_v1.json"))
        self.escape = EscapeDecoder(load_escape_decoder_config(root / "config" / "escape_decoder_v1.json"))
        self.safety = SafetyClamp(load_safety_envelope(root / "config" / "safety_envelope_v1.json"))
        self.frame_id = 0
        self.neural_sequence = 0
        self.scenario = "neutral"

    @staticmethod
    def _pixels(scenario: str, phase: int):
        black, red = (0, 0, 0), (255, 0, 0)
        if scenario == "left":
            return ((red, black, black),)
        if scenario == "right":
            return ((black, black, red),)
        if scenario == "center":
            return ((black, red, black),)
        if scenario == "stop":
            # Increasing bounded target area exercises looming before the final
            # watchdog shutdown stop, without injecting neural or decoder values.
            return ((red, red, red),) if phase % 2 else ((black, red, black),)
        return ((black, black, black),)

    def perception(self, now_ns: int):
        self.frame_id += 1
        segment = min((self.frame_id - 1) // 30, 4)
        self.scenario = ("neutral", "left", "right", "center", "stop")[segment]
        pixels = self._pixels(self.scenario, self.frame_id)
        return self.pipeline.process(
            pixels,
            camera_timestamp_ns=now_ns,
            camera_frame_id=self.frame_id,
            tof_left_mm=500,
            tof_center_mm=500,
            tof_right_mm=500,
            tof_timestamp_ns=now_ns,
            tof_frame_id=self.frame_id,
            now_ns=now_ns,
        )

    def neural(self, frame, now_ns: int):
        self.neural_sequence += 1
        if frame is None:
            return None
        channels = self.mapper.map_channels(frame, now_ns=now_ns)
        mapped = self.mapper.build_external(frame, now_ns=now_ns)
        external = {body_id: value for body_id, value in mapped.items() if body_id in self.runtime_index}
        snapshot = self.runtime.step(external)
        projected_spikes = tuple(
            snapshot["spikes"][self.runtime_index[body_id]] if body_id in self.runtime_index else False
            for body_id in self.dn_ids
        )
        readout = self.aggregator.update(
            projected_spikes,
            timestamp_ns=now_ns,
            sequence=self.neural_sequence,
            runtime_healthy=snapshot["healthy"],
        )
        pre = self.escape.apply(readout, self.steering.decode(readout))
        safe = self.safety.apply(pre, now_ns=now_ns, fallback_sequence=self.neural_sequence)
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
            },
            "dn_readout": readout,
            "pre_safety_intent": pre,
            "safety_result": safe,
            "scenario": self.scenario,
        }
        # Scenario is transport metadata, not a neural input; remove it from the
        # schema-bound trace and carry it alongside for the fixture observer.
        scenario = trace.pop("scenario")
        trace["male_cns"]["scenario_fixture"] = scenario
        return NeuralUpdate(readout, safe["intent"], trace)


def compact_state(state: dict, received_ns: int, body: dict) -> dict:
    move = state["move"]
    applied = list(move["applied"])
    odom = state.get("odom") or {}
    return {
        "sample_timestamp_ns": received_ns,
        "robot_t_ns": state.get("t_ns"),
        "policy": state["policy"],
        "requested_velocity": list(move["requested"]),
        "applied_velocity": applied,
        "velocity": [odom.get("vx", applied[0]), odom.get("vy", applied[1]), odom.get("vyaw", applied[2])],
        "heading_rad": body["heading_rad"],
        "trunk_quaternion_wxyz": body["trunk_quaternion_wxyz"],
        "trunk_z": body["trunk_z"],
        "limited_by": list(move.get("limited_by", [])),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--graph-cache", type=Path, required=True)
    parser.add_argument("--graph-key", required=True)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--body-port", type=int, required=True)
    parser.add_argument("--microduck", type=Path, required=True)
    parser.add_argument("--microduck-rl", type=Path, required=True)
    parser.add_argument("--source-head", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--duration-s", type=float, default=6.4)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()
    hostname = socket.gethostname()
    if not hostname.startswith("jetsonthor"):
        raise RuntimeError(f"runtime authority must be Thor, got {hostname!r}")
    if platform.python_version_tuple()[:2] != ("3", "12"):
        raise RuntimeError("Thor runtime evidence requires Python 3.12")

    graph = ConnectomeGraph.from_cache(args.graph_cache, args.graph_key)
    identity = build_run_identity(
        args.root,
        run_id=args.run_id,
        project_commit=args.source_head,
        microduck_commit=git_head(args.microduck),
        microduck_rl_commit=git_head(args.microduck_rl),
        graph_identity=graph.root_key,
    )
    telemetry = EndToEndTelemetry(args.root / "config" / "telemetry_v1.json", identity)
    chain = FullChain(args.root, graph)
    command_client = RobotdClient(args.socket, timeout_s=2.0)
    command_client.connect()
    command_client.enable(True)
    adapter = RobotMotionAdapter(command_client, args.root / "config" / "motion_adapter_v1.json")
    sampler = RobotStateSampler(args.socket)
    body = BodyReader(args.body_port)
    started_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def observe(update, output, transport_result):
        if update is None or update.trace is None:
            return
        command_ns = output["intent"]["timestamp_ns"]
        state, received_ns = sampler.after(command_ns)
        scenario = update.trace["male_cns"]["scenario_fixture"]
        trace = copy.deepcopy(update.trace)
        trace["male_cns"].pop("scenario_fixture")
        telemetry.append(
            trial_id=f"{args.run_id}:{scenario}",
            scenario=scenario,
            timestamp_ns=command_ns,
            sequence=output["intent"]["sequence"],
            trace=trace,
            watchdog_output=output,
            robotd_transport_result=transport_result,
            robotd_connected=command_client.status.connected,
            robot_state=compact_state(state, received_ns, body.read()),
        )

    scheduler = ClosedLoopScheduler(
        config=args.root / "config" / "scheduler_v1.json",
        watchdog=ControllerWatchdog(args.root / "config" / "watchdog_v1.json"),
        perception_step=chain.perception,
        neural_step=chain.neural,
        publisher=adapter.send,
        control_observer=observe,
    )
    try:
        scheduler_summary = scheduler.run(args.duration_s)
        artifact = telemetry.write(args.artifact)
    finally:
        try:
            command_client.close()
        finally:
            sampler.close()
            body.close()

    records = telemetry.records()
    scenario_counts = Counter(record["scenario"] for record in records)
    command_counts = Counter(record["robot_facing_command_type"] for record in records)
    all_scenarios = all(scenario_counts[name] > 0 for name in ("neutral", "left", "right", "center", "stop"))
    stop_present = command_counts["robot.stop"] > 0
    strict_timestamps = all(a["timestamp_ns"] < b["timestamp_ns"] for a, b in zip(records, records[1:]))
    strict_sequences = all(a["sequence"] < b["sequence"] for a, b in zip(records, records[1:]))
    telemetry_gaps = sum(max(0, b["sequence"] - a["sequence"] - 1) for a, b in zip(records, records[1:]))
    post_command_state_count = sum(
        record["robot_state"]["sample_timestamp_ns"] >= record["timestamp_ns"]
        for record in records
    )
    command_state_mismatch_count = 0
    for record in records:
        commanded = [
            record["robot_facing_vx"], record["robot_facing_vy"], record["robot_facing_vyaw"]
        ]
        requested = record["robot_state"]["requested_velocity"]
        if any(abs(float(actual) - float(expected)) > 1e-9 for actual, expected in zip(requested, commanded)):
            command_state_mismatch_count += 1
    heading_range_by_scenario = {
        scenario: {
            "min_rad": min(record["robot_state"]["heading_rad"] for record in records if record["scenario"] == scenario),
            "max_rad": max(record["robot_state"]["heading_rad"] for record in records if record["scenario"] == scenario),
        }
        for scenario in ("neutral", "left", "right", "center", "stop")
        if scenario_counts[scenario]
    }
    result = "PASS" if (
        records and all_scenarios and stop_present and strict_timestamps and strict_sequences
        and telemetry_gaps == 0 and post_command_state_count == len(records)
        and command_state_mismatch_count == 0
    ) else "FAIL"
    report = {
        "schema_version": "p6-05-telemetry-summary-v1",
        "execution_target": "Thor",
        "hostname": hostname,
        "started_utc": started_utc,
        "ended_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_head": args.source_head,
        "run_id": args.run_id,
        "identities": identity,
        "trace_schema": "p6-end-to-end-telemetry-v1 canonical-jsonl",
        "sensor_to_command_correlation": "complete",
        "command_to_robot_state_correlation": "complete; post-command official robot.state plus MuJoCo body heading per record",
        "scenario_record_counts": dict(sorted(scenario_counts.items())),
        "command_counts": dict(sorted(command_counts.items())),
        "record_count": artifact["record_count"],
        "start_timestamp_ns": artifact["start_timestamp_ns"],
        "end_timestamp_ns": artifact["end_timestamp_ns"],
        "artifact_name": args.artifact.name,
        "artifact_sha256": artifact["sha256"],
        "nonfinite_count": 0,
        "strict_monotonic_timestamps": strict_timestamps,
        "strict_sequences": strict_sequences,
        "telemetry_gap_count": telemetry_gaps,
        "post_command_state_count": post_command_state_count,
        "command_state_mismatch_count": command_state_mismatch_count,
        "heading_range_by_scenario": heading_range_by_scenario,
        "scheduler": scheduler_summary,
        "fixture_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "result": result,
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    if result != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
