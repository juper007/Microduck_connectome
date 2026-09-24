"""Run the full Phase-6 chain for 600+ wall-clock seconds on Thor."""

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
import time

from microduck_connectome.control_contracts import make_behavior_intent
from microduck_connectome.graph import ConnectomeGraph
from microduck_connectome.motion_adapter import RobotMotionAdapter
from microduck_connectome.robotd_client import RobotdClient
from microduck_connectome.scheduler import ClosedLoopScheduler, NeuralUpdate
from microduck_connectome.telemetry import EndToEndTelemetry, build_run_identity
from microduck_connectome.watchdog import ControllerWatchdog
from scripts.p6_telemetry_runtime_fixture import (
    BodyReader, FullChain, RobotStateSampler, compact_state, git_head,
)


SCENARIOS = ("neutral", "left", "right", "center", "stop", "sensor_loss")


class SoakChain(FullChain):
    """Repeat bounded deterministic frames; keep the frozen control stages."""

    def __init__(self, root: Path, graph: ConnectomeGraph, *, segment_s: float):
        super().__init__(root, graph)
        self.segment_ns = int(segment_s * 1e9)
        self.started_ns = None
        self.frame_scenarios = {}

    def perception(self, now_ns: int):
        if self.started_ns is None:
            self.started_ns = now_ns
        self.frame_id += 1
        segment = ((now_ns - self.started_ns) // self.segment_ns) % len(SCENARIOS)
        self.scenario = SCENARIOS[segment]
        self.frame_scenarios[self.frame_id] = self.scenario
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
            camera_source_valid=self.scenario != "sensor_loss",
        )

    def neural(self, frame, now_ns: int):
        self.neural_sequence += 1
        if frame is None:
            return None
        scenario = self.frame_scenarios[frame["frame_id"]]
        channels = self.mapper.map_channels(frame, now_ns=now_ns)
        mapped = self.mapper.build_external(frame, now_ns=now_ns)
        external = {body_id: value for body_id, value in mapped.items() if body_id in self.runtime_index}
        if scenario == "sensor_loss" and (frame["valid"] or any(channels.values()) or any(external.values())):
            raise RuntimeError("sensor-loss frame did not produce neutral stimulation")
        snapshot = self.runtime.step(external)
        projected = tuple(
            snapshot["spikes"][self.runtime_index[body_id]] if body_id in self.runtime_index else False
            for body_id in self.dn_ids
        )
        readout = self.aggregator.update(
            projected, timestamp_ns=now_ns, sequence=self.neural_sequence,
            runtime_healthy=snapshot["healthy"],
        )
        pre = self.escape.apply(readout, self.steering.decode(readout))
        if scenario == "stop":
            # This deterministic soak-only stop exercises the normal clamp,
            # watchdog, sealed adapter and official robot.stop transport.
            # It is an engineering test input, not a biological response.
            pre = make_behavior_intent(
                timestamp_ns=pre["timestamp_ns"], sequence=pre["sequence"],
                stop=True, confidence=pre["confidence"],
            )
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
                "scenario_fixture": scenario,
            },
            "dn_readout": readout,
            "pre_safety_intent": pre,
            "safety_result": safe,
        }
        return NeuralUpdate(readout, safe["intent"], trace)


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    index = (len(values) - 1) * fraction
    low, high = math.floor(index), math.ceil(index)
    return values[low] + (values[high] - values[low]) * (index - low)


def main() -> None:
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
    parser.add_argument("--duration-s", type=float, default=605.0)
    parser.add_argument("--segment-s", type=float, default=10.0)
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()
    if not socket.gethostname().startswith("jetsonthor") or platform.python_version_tuple()[:2] != ("3", "12"):
        raise RuntimeError("runtime authority requires Thor Python 3.12")
    if args.duration_s <= 0 or args.segment_s <= 0:
        raise ValueError("duration and segment must be positive")
    if not args.preflight and args.duration_s < 600:
        raise ValueError("qualified soak requires at least 600 requested wall-clock seconds")
    graph = ConnectomeGraph.from_cache(args.graph_cache, args.graph_key)
    identity = build_run_identity(
        args.root, run_id=args.run_id, project_commit=args.source_head,
        microduck_commit=git_head(args.microduck),
        microduck_rl_commit=git_head(args.microduck_rl), graph_identity=graph.root_key,
    )
    telemetry = EndToEndTelemetry(args.root / "config/telemetry_v1.json", identity)
    chain = SoakChain(args.root, graph, segment_s=args.segment_s)
    command_client = RobotdClient(args.socket, timeout_s=2.0)
    command_client.connect()
    command_client.enable(True)
    adapter = RobotMotionAdapter(command_client, args.root / "config/motion_adapter_v1.json")
    sampler = RobotStateSampler(args.socket)
    body = BodyReader(args.body_port)
    published = []
    ipc_error_count = 0
    scenario_counts = Counter()
    telemetry_count = 0
    telemetry_gaps = 0
    post_command_states = 0
    unsafe_sensor_loss = 0
    safety_interventions = 0
    first_record_ns = None
    last_record_ns = None
    last_record_sequence = None
    trace_digest = hashlib.sha256()
    args.artifact.parent.mkdir(parents=True, exist_ok=True)
    trace_file = args.artifact.open("wb")
    started_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def publish(output):
        nonlocal ipc_error_count
        intent = output["intent"]
        values = (intent["vx"], intent["vy"], intent["vyaw"])
        if not all(math.isfinite(value) for value in values):
            raise RuntimeError("nonfinite robot-facing command")
        if abs(values[0]) > 0.08 or values[1] != 0.0 or abs(values[2]) > 0.50:
            raise RuntimeError("robot-facing command escaped frozen motion envelope")
        if output["watchdog_state"] != "healthy" and (not intent["stop"] or any(values)):
            raise RuntimeError("stale watchdog output continued motion")
        try:
            result = adapter.send(output)
        except Exception:
            ipc_error_count += 1
            raise
        published.append({
            "timestamp_ns": time.monotonic_ns(), "sequence": intent["sequence"],
            "vx": values[0], "vy": values[1], "vyaw": values[2],
            "stop": intent["stop"], "watchdog_state": output["watchdog_state"],
            "stale_reason": output["stale_reason"], "transport_result": result,
        })
        return result

    def observe(update, output, transport_result):
        nonlocal telemetry_count, telemetry_gaps, post_command_states
        nonlocal unsafe_sensor_loss, safety_interventions, first_record_ns
        nonlocal last_record_ns, last_record_sequence
        if update is None or update.trace is None:
            return
        command_ns = output["intent"]["timestamp_ns"]
        state, received_ns = sampler.after(command_ns)
        trace = copy.deepcopy(update.trace)
        scenario = trace["male_cns"].pop("scenario_fixture")
        record = telemetry.append(
            trial_id=f"{args.run_id}:{scenario}",
            scenario="neutral" if scenario == "sensor_loss" else scenario,
            timestamp_ns=command_ns, sequence=output["intent"]["sequence"],
            trace=trace, watchdog_output=output,
            robotd_transport_result=transport_result,
            robotd_connected=command_client.status.connected,
            robot_state=compact_state(state, received_ns, body.read()),
        )
        encoded = (json.dumps(record, sort_keys=True, separators=(",", ":"),
                              ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")
        trace_file.write(encoded)
        trace_digest.update(encoded)
        # Retain the previous validated record for EndToEndTelemetry's
        # monotonic check while streaming a 30k-record soak to disk.
        telemetry._records[:] = [record]
        telemetry_count += 1
        scenario_counts[scenario] += 1
        first_record_ns = command_ns if first_record_ns is None else first_record_ns
        last_record_ns = command_ns
        if last_record_sequence is not None:
            telemetry_gaps += max(0, record["sequence"] - last_record_sequence - 1)
        last_record_sequence = record["sequence"]
        post_command_states += record["robot_state"]["sample_timestamp_ns"] >= command_ns
        if scenario == "sensor_loss" and (
            record["perception"]["valid"] or any(record["stimulus_channels"].values()) or
            any(abs(record[key]) > 0 for key in ("robot_facing_vx", "robot_facing_vy", "robot_facing_vyaw"))
        ):
            unsafe_sensor_loss += 1
        safety_interventions += bool(record["clamp_applied"])

    scheduler = ClosedLoopScheduler(
        config=args.root / "config/scheduler_v1.json",
        watchdog=ControllerWatchdog(args.root / "config/watchdog_v1.json"),
        perception_step=chain.perception, neural_step=chain.neural,
        publisher=publish, control_observer=observe,
    )
    started_ns = time.monotonic_ns()
    try:
        scheduler_summary = scheduler.run(args.duration_s)
        ended_ns = time.monotonic_ns()
        health = command_client.health()
        connected_before_close = command_client.status.connected
    finally:
        trace_file.close()
        command_client.close()
        sampler.close()
        body.close()

    counts = Counter(item["transport_result"] for item in published)
    timestamps = [item["timestamp_ns"] for item in published]
    watchdog_periods = [(b - a) / 1e6 for a, b in zip(timestamps, timestamps[1:])]
    artifact = {
        "sha256": trace_digest.hexdigest(), "record_count": telemetry_count,
        "start_timestamp_ns": first_record_ns, "end_timestamp_ns": last_record_ns,
        "bytes": args.artifact.stat().st_size,
    }
    values = [value for item in published for value in (item["vx"], item["vy"], item["vyaw"])]
    nonfinite_count = sum(not math.isfinite(value) for value in values)
    stall_count = sum(period > 100.0 for period in watchdog_periods)
    wall_duration = (ended_ns - started_ns) / 1e9
    qualified = wall_duration >= 600 and scheduler_summary["duration_s"] >= 600
    checks = {
        "duration": qualified or args.preflight,
        "all_scenarios": all(scenario_counts[name] > 0 for name in SCENARIOS),
        "bounded_finite": nonfinite_count == 0 and all(abs(item["vx"]) <= 0.08 and item["vy"] == 0.0 and abs(item["vyaw"]) <= 0.50 for item in published),
        "no_stale_motion": all(item["watchdog_state"] == "healthy" or (item["stop"] and item["vx"] == item["vy"] == item["vyaw"] == 0.0) for item in published),
        "sensor_loss_safe": unsafe_sensor_loss == 0,
        "stop_present": counts["robot_stop_refreshed"] > 0,
        "watchdog_continuous": stall_count == 0 and scheduler_summary["watchdog_hz"] >= 45.0,
        "scheduler_and_ipc": scheduler_summary["scheduler_exceptions"] == 0 and ipc_error_count == 0 and connected_before_close,
        "telemetry": artifact["record_count"] == telemetry_count and telemetry_count > 0 and telemetry_gaps == 0 and post_command_states == telemetry_count,
    }
    result = "PRECHECK" if args.preflight and all(checks.values()) else "PASS" if all(checks.values()) else "FAIL"
    summary = {
        "schema_version": "p6-07-closed-loop-soak-v1",
        "execution_target": "Thor", "hostname": socket.gethostname(),
        "source_head": args.source_head, "run_id": args.run_id,
        "started_utc": started_utc, "ended_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "started_monotonic_ns": started_ns, "ended_monotonic_ns": ended_ns,
        "wall_clock_duration_s": wall_duration,
        "requested_duration_s": args.duration_s,
        "qualified_600s": qualified,
        "identities": identity,
        "fixture_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "perception_updates": len(scheduler._metrics.tick_ns["perception"]),
        "neural_updates": len(scheduler._metrics.tick_ns["neural"]),
        "watchdog_ticks": len(scheduler._metrics.tick_ns["watchdog"]),
        "robot_command_count": len(published),
        "stale_event_count": scheduler_summary["stale_events"],
        "fault_count": scheduler_summary["scheduler_exceptions"] + ipc_error_count,
        "reconnect_count": 0, "stop_count": sum(item["stop"] for item in published),
        "max_abs_vx": max(abs(item["vx"]) for item in published),
        "max_abs_vy": max(abs(item["vy"]) for item in published),
        "max_abs_vyaw": max(abs(item["vyaw"]) for item in published),
        "nan_count": sum(math.isnan(value) for value in values),
        "inf_count": sum(math.isinf(value) for value in values),
        "safety_intervention_count": safety_interventions,
        "safety_violation_count": 0 if checks["bounded_finite"] and checks["no_stale_motion"] and checks["sensor_loss_safe"] else 1,
        "watchdog_stall_count": stall_count,
        "scheduler_exception_count": scheduler_summary["scheduler_exceptions"],
        "ipc_error_count": ipc_error_count,
        "telemetry_record_count": telemetry_count,
        "telemetry_gap_count": telemetry_gaps,
        "post_command_state_count": post_command_states,
        "scenario_record_counts": dict(sorted(scenario_counts.items())),
        "transport_counts": dict(sorted(counts.items())),
        "period_ms_p50": percentile(watchdog_periods, 0.50),
        "period_ms_p95": percentile(watchdog_periods, 0.95),
        "period_ms_p99": percentile(watchdog_periods, 0.99),
        "jitter_ms_p50": scheduler_summary["watchdog_jitter_ms_p50"],
        "jitter_ms_p95": scheduler_summary["watchdog_jitter_ms_p95"],
        "jitter_ms_p99": scheduler_summary["watchdog_jitter_ms_p99"],
        "processing_latency_ms_p50": scheduler_summary["watchdog_processing_latency_ms_p50"],
        "processing_latency_ms_p95": scheduler_summary["watchdog_processing_latency_ms_p95"],
        "processing_latency_ms_p99": scheduler_summary["watchdog_processing_latency_ms_p99"],
        "scheduler": scheduler_summary,
        "robotd_health": health,
        "telemetry_artifact": {"name": args.artifact.name, **artifact},
        "checks": checks,
        "result": result,
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"result": result, "wall_clock_duration_s": wall_duration,
                      "robot_command_count": len(published), "checks": checks}, sort_keys=True))
    if result == "FAIL":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
