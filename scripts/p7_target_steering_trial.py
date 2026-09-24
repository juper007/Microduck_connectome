"""Run one official-Thor visual target trial through the frozen full P6 chain."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import platform
import socket
import threading
import time

from microduck_connectome.graph import ConnectomeGraph
from microduck_connectome.motion_adapter import RobotMotionAdapter
from microduck_connectome.robotd_client import RobotdClient
from microduck_connectome.scheduler import ClosedLoopScheduler
from microduck_connectome.steering_decoder import SteeringDecoder, load_steering_decoder_config
from microduck_connectome.target_scenario import (
    evaluator_truth, load_target_scenario_config, make_target_trial,
    render_camera_pixels, wrap_angle,
)
from microduck_connectome.target_stimulus_gain import (
    TargetDriveSensoryMapper, load_target_stimulus_drive,
)
from microduck_connectome.telemetry import EndToEndTelemetry, build_run_identity
from microduck_connectome.watchdog import ControllerWatchdog
from scripts.p6_telemetry_runtime_fixture import (
    BodyReader, FullChain, RobotStateSampler, compact_state, git_head,
)


class TargetChain(FullChain):
    def __init__(self, root, graph, config, trial, body, body_lock,
                 gain_config, gain_hash, steering_hash):
        super().__init__(root, graph)
        self.config = config
        self.trial = trial
        self.body = body
        self.body_lock = body_lock
        self.mapper = TargetDriveSensoryMapper(
            tuple(sorted(body_id for spec in self.mapper.config["populations"].values()
                         for body_id in spec["body_ids"])),
            self.mapper.config, gain_config,
        )
        self.gain_hash = gain_hash
        self.steering = SteeringDecoder(
            load_steering_decoder_config(root / "config/steering_decoder_p7_v1.json")
        )
        self.steering_hash = steering_hash
        self.started_ns = None
        self.scenario = trial.target_side if trial.target_present else "neutral"

    def perception(self, now_ns):
        if self.started_ns is None:
            self.started_ns = now_ns
        self.frame_id += 1
        elapsed_s = (now_ns - self.started_ns) / 1e9
        with self.body_lock:
            heading = self.body.read()["heading_rad"]
        pixels = render_camera_pixels(
            self.config, self.trial, heading_rad=heading,
            elapsed_s=elapsed_s, frame_index=self.frame_id - 1,
        )
        distance = self.config["tof_mm"]
        return self.pipeline.process(
            pixels, camera_timestamp_ns=now_ns,
            camera_frame_id=self.frame_id,
            tof_left_mm=distance, tof_center_mm=distance,
            tof_right_mm=distance, tof_timestamp_ns=now_ns,
            tof_frame_id=self.frame_id, now_ns=now_ns,
        )

    def neural(self, frame, now_ns):
        update = super().neural(frame, now_ns)
        if update is not None and update.trace is not None:
            update.trace["male_cns"]["target_drive_config_sha256"] = self.gain_hash
            update.trace["male_cns"]["steering_decoder_p7_sha256"] = self.steering_hash
        return update


def sustained_heading_response(records, *, stimulus_ns, threshold_rad=0.02, duration_s=0.2):
    """Find the first 200 ms net heading change supported by consistent samples."""
    active = [row for row in records if row["timestamp_ns"] >= stimulus_ns]
    for start in range(len(active)):
        initial = active[start]["robot_state"]["heading_rad"]
        for end in range(start + 1, len(active)):
            if (active[end]["timestamp_ns"] - active[start]["timestamp_ns"]) / 1e9 < duration_s:
                continue
            segment = active[start:end + 1]
            delta = wrap_angle(segment[-1]["robot_state"]["heading_rad"] - initial)
            if abs(delta) >= threshold_rad:
                increments = [wrap_angle(b["robot_state"]["heading_rad"] - a["robot_state"]["heading_rad"])
                              for a, b in zip(segment, segment[1:])]
                consistent = sum(1 for item in increments if item * delta > 0)
                if consistent >= math.ceil(0.8 * len(increments)):
                    return {
                        "start_timestamp_ns": segment[0]["timestamp_ns"],
                        "end_timestamp_ns": segment[-1]["timestamp_ns"],
                        "heading_delta_rad": delta,
                        "direction": "left" if delta > 0 else "right",
                        "latency_s": (segment[0]["timestamp_ns"] - stimulus_ns) / 1e9,
                    }
            break
    return None


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
    parser.add_argument("--trial-spec", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()
    if not socket.gethostname().startswith("jetsonthor") or platform.python_version_tuple()[:2] != ("3", "12"):
        raise RuntimeError("behavior evidence requires Thor Python 3.12")
    config_path = args.root / "config/target_scenario_v1.json"
    config = load_target_scenario_config(config_path)
    gain_path = args.root / "config/target_stimulus_drive_v2.json"
    gain_config = load_target_stimulus_drive(gain_path)
    gain_hash = hashlib.sha256(gain_path.read_bytes()).hexdigest()
    steering_path = args.root / "config/steering_decoder_p7_v1.json"
    steering_hash = hashlib.sha256(steering_path.read_bytes()).hexdigest()
    spec = json.loads(args.trial_spec.read_text(encoding="utf-8"))
    graph = ConnectomeGraph.from_cache(args.graph_cache, args.graph_key)
    identity = build_run_identity(
        args.root, run_id=args.run_id, project_commit=args.source_head,
        microduck_commit=git_head(args.microduck),
        microduck_rl_commit=git_head(args.microduck_rl), graph_identity=graph.root_key,
    )
    telemetry = EndToEndTelemetry(args.root / "config/telemetry_v1.json", identity)
    command_client = RobotdClient(args.socket, timeout_s=2.0)
    command_client.connect()
    command_client.enable(True)
    adapter = RobotMotionAdapter(command_client, args.root / "config/motion_adapter_v1.json")
    sampler = RobotStateSampler(args.socket)
    body = BodyReader(args.body_port)
    body_lock = threading.Lock()
    with body_lock:
        initial_body = body.read()
    trial = make_target_trial(config, **spec, initial_robot_heading_rad=initial_body["heading_rad"])
    chain = TargetChain(args.root, graph, config, trial, body, body_lock,
                        gain_config, gain_hash, steering_hash)
    health_before = command_client.health()
    observed = []

    def observe(update, output, transport_result):
        if update is None or update.trace is None:
            return
        command_ns = output["intent"]["timestamp_ns"]
        state, received_ns = sampler.after(command_ns)
        with body_lock:
            body_state = body.read()
        trace = copy.deepcopy(update.trace)
        trace["male_cns"].pop("scenario_fixture")
        record = telemetry.append(
            trial_id=trial.trial_id, scenario=chain.scenario,
            timestamp_ns=command_ns, sequence=output["intent"]["sequence"],
            trace=trace, watchdog_output=output,
            robotd_transport_result=transport_result,
            robotd_connected=command_client.status.connected,
            robot_state=compact_state(state, received_ns, body_state),
        )
        observed.append(record)

    scheduler = ClosedLoopScheduler(
        config=args.root / "config/scheduler_v1.json",
        watchdog=ControllerWatchdog(args.root / "config/watchdog_v1.json"),
        perception_step=chain.perception, neural_step=chain.neural,
        publisher=adapter.send, control_observer=observe,
    )
    started_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        scheduler_result = scheduler.run(trial.trial_timeout_s)
        health_after = command_client.health()
        with body_lock:
            final_body = body.read()
        args.artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact = telemetry.write(args.artifact)
    finally:
        command_client.close()
        sampler.close()
        body.close()

    if not observed:
        raise RuntimeError("no full-chain telemetry records")
    stimulus_ns = chain.started_ns + int(trial.stimulus_start_s * 1e9)
    active = [row for row in observed if row["timestamp_ns"] >= stimulus_ns]
    response = sustained_heading_response(observed, stimulus_ns=stimulus_ns)
    safety_violations = sum(
        not math.isfinite(row["robot_facing_vyaw"])
        or abs(row["robot_facing_vx"]) > 0.08 or row["robot_facing_vy"] != 0.0
        or abs(row["robot_facing_vyaw"]) > 0.50
        for row in observed
    )
    outcome = "no_response" if response is None else (
        "correct" if response["direction"] == trial.target_side else "incorrect"
    )
    if not trial.target_present:
        outcome = "no_target"
    if not health_before["healthy"] or not health_after["healthy"] or not active:
        outcome = "invalid"
    summary = {
        "schema_version": "p7-02-target-trial-v1",
        "execution_target": "Thor", "hostname": socket.gethostname(),
        "started_utc": started_utc,
        "ended_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "identity": identity, "trial": trial.metadata(),
        "scenario_config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
        "target_drive_config_sha256": gain_hash,
        "steering_decoder_p7_sha256": steering_hash,
        "trial_spec_sha256": hashlib.sha256(args.trial_spec.read_bytes()).hexdigest(),
        "fixture_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "health_before": health_before, "health_after": health_after,
        "initial_body": initial_body, "final_body": final_body,
        "initial_heading_rad": initial_body["heading_rad"],
        "final_heading_delta_rad": wrap_angle(final_body["heading_rad"] - initial_body["heading_rad"]),
        "response": response, "outcome": outcome,
        "safety_limit_violations": safety_violations,
        "perception_active_frames": sum(row["perception"]["target_area"] > 0 for row in active),
        "max_abs_robot_facing_vyaw": max(abs(row["robot_facing_vyaw"]) for row in observed),
        "max_dn_steering_left": max(row["dn_activity"]["steering_left"] for row in observed),
        "max_dn_steering_right": max(row["dn_activity"]["steering_right"] for row in observed),
        "scheduler": scheduler_result, "artifact": artifact,
        "evaluator_truth_at_stimulus": evaluator_truth(config, trial, elapsed_s=trial.stimulus_start_s),
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"trial_id": trial.trial_id, "outcome": outcome,
                      "response": response, "max_vyaw": summary["max_abs_robot_facing_vyaw"],
                      "dn_left": summary["max_dn_steering_left"],
                      "dn_right": summary["max_dn_steering_right"]}, sort_keys=True))
    if outcome == "invalid" or safety_violations:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
