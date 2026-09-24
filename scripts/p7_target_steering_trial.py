"""Run one official-Thor visual target trial through the frozen full P6 chain."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import platform
import queue
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


def sustained_heading_response(records, *, stimulus_ns, threshold_rad=0.02,
                               duration_s=0.2, same_sign_fraction=0.8):
    """Find the first 200 ms net heading change supported by consistent samples."""
    active = [row for row in records
              if row["robot_state"]["body_sample_timestamp_ns"] >= stimulus_ns]
    for start in range(len(active)):
        initial = active[start]["robot_state"]["heading_rad"]
        for end in range(start + 1, len(active)):
            if (active[end]["robot_state"]["body_sample_timestamp_ns"]
                    - active[start]["robot_state"]["body_sample_timestamp_ns"]) / 1e9 < duration_s:
                continue
            segment = active[start:end + 1]
            delta = wrap_angle(segment[-1]["robot_state"]["heading_rad"] - initial)
            if abs(delta) >= threshold_rad:
                increments = [wrap_angle(b["robot_state"]["heading_rad"] - a["robot_state"]["heading_rad"])
                              for a, b in zip(segment, segment[1:])]
                consistent = sum(1 for item in increments if item * delta > 0)
                if consistent >= math.ceil(same_sign_fraction * len(increments)):
                    return {
                        "start_timestamp_ns": segment[0]["robot_state"]["body_sample_timestamp_ns"],
                        "end_timestamp_ns": segment[-1]["robot_state"]["body_sample_timestamp_ns"],
                        "heading_delta_rad": delta,
                        "direction": "left" if delta > 0 else "right",
                        "latency_s": (segment[0]["robot_state"]["body_sample_timestamp_ns"] - stimulus_ns) / 1e9,
                    }
            break
    return None


def score_target_response(config, trial, response, response_row, *, started_ns,
                          center_tolerance_rad):
    """Score actual heading against the rendered bearing at response onset."""
    if response is None:
        return "no_response", None
    response = dict(response)
    sample_ns = response_row["robot_state"]["body_sample_timestamp_ns"]
    elapsed_s = (sample_ns - started_ns) / 1e9
    truth = evaluator_truth(config, trial, elapsed_s=elapsed_s)
    relative = wrap_angle(
        truth["target_world_bearing_rad"] - response_row["robot_state"]["heading_rad"]
    )
    perception_age_ns = sample_ns - response_row["perception"]["timestamp_ns"]
    visible = (response_row["perception"]["target_area"] > 0
               and 0 <= perception_age_ns <= 100_000_000)
    side = "left" if relative > 0 else "right"
    response.update(target_relative_bearing_rad=relative,
                    target_visible=visible, target_side_at_response=side,
                    perception_age_ms=perception_age_ns / 1e6)
    outcome = "correct" if (
        visible and abs(relative) > center_tolerance_rad
        and response["direction"] == side
    ) else "incorrect"
    return outcome, response


def initial_pose_matches(body, reference):
    return (
        abs(wrap_angle(body["heading_rad"] - reference["heading_rad"]))
        <= reference["heading_tolerance_rad"]
        and abs(body["trunk_z"] - reference["trunk_z_m"])
        <= reference["trunk_z_tolerance_m"]
    )


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
    parser.add_argument("--experiment", type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()
    if not socket.gethostname().startswith("jetsonthor") or platform.python_version_tuple()[:2] != ("3", "12"):
        raise RuntimeError("behavior evidence requires Thor Python 3.12")
    config_path = args.root / "config/target_scenario_v1.json"
    config = load_target_scenario_config(config_path)
    gain_path = args.root / "config/target_stimulus_drive_v3.json"
    gain_config = load_target_stimulus_drive(gain_path)
    gain_hash = hashlib.sha256(gain_path.read_bytes()).hexdigest()
    steering_path = args.root / "config/steering_decoder_p7_v1.json"
    steering_hash = hashlib.sha256(steering_path.read_bytes()).hexdigest()
    experiment = None
    experiment_hash = None
    if args.experiment is not None:
        from scripts.p7_preregister import HASH_PATHS
        experiment = json.loads(args.experiment.read_text(encoding="utf-8"))
        if experiment["schema_version"] != "steering-experiment-v3":
            raise ValueError("unexpected experiment schema")
        for name, relative in HASH_PATHS.items():
            actual = hashlib.sha256((args.root / relative).read_bytes()).hexdigest()
            if actual != experiment["config_sha256"][name]:
                raise ValueError(f"preregistered {name} hash mismatch")
        experiment_hash = hashlib.sha256(args.experiment.read_bytes()).hexdigest()
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
    if experiment is not None:
        reference = experiment["reset_reference"]
        if not initial_pose_matches(initial_body, reference):
            command_client.close()
            sampler.close()
            body.close()
            raise RuntimeError("official simulator initial pose outside preregistered tolerance")
    trial = make_target_trial(config, **spec, initial_robot_heading_rad=initial_body["heading_rad"])
    chain = TargetChain(args.root, graph, config, trial, body, body_lock,
                        gain_config, gain_hash, steering_hash)
    health_before = command_client.health()
    observed = []
    observation_queue = queue.Queue(maxsize=256)
    observer_error = []

    def process_observation(update, output, transport_result):
        if update is None or update.trace is None:
            return
        command_ns = output["intent"]["timestamp_ns"]
        state, received_ns = sampler.after(command_ns)
        with body_lock:
            body_state = body.read()
            body_sample_ns = time.monotonic_ns()
        trace = copy.deepcopy(update.trace)
        trace["male_cns"].pop("scenario_fixture")
        record = telemetry.append(
            trial_id=trial.trial_id, scenario=chain.scenario,
            timestamp_ns=command_ns, sequence=output["intent"]["sequence"],
            trace=trace, watchdog_output=output,
            robotd_transport_result=transport_result,
            robotd_connected=command_client.status.connected,
            robot_state={**compact_state(state, received_ns, body_state),
                         "body_sample_timestamp_ns": body_sample_ns},
        )
        observed.append(record)

    def observation_worker():
        while True:
            item = observation_queue.get()
            try:
                if item is None:
                    return
                if not observer_error:
                    process_observation(*item)
            except BaseException as error:
                observer_error.append(error)
            finally:
                observation_queue.task_done()

    observer_thread = threading.Thread(target=observation_worker, name="p7-02-telemetry", daemon=False)
    observer_thread.start()

    def observe(update, output, transport_result):
        if observer_error:
            raise RuntimeError("telemetry observer failed") from observer_error[0]
        try:
            observation_queue.put_nowait((update, output, transport_result))
        except queue.Full as error:
            raise RuntimeError("telemetry observer queue overran") from error

    scheduler = ClosedLoopScheduler(
        config=args.root / "config/scheduler_v1.json",
        watchdog=ControllerWatchdog(args.root / "config/watchdog_v1.json"),
        perception_step=chain.perception, neural_step=chain.neural,
        publisher=adapter.send, control_observer=observe,
    )
    started_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        scheduler_result = scheduler.run(trial.trial_timeout_s)
        observation_queue.join()
        if observer_error:
            raise RuntimeError("telemetry observer failed") from observer_error[0]
        health_after = command_client.health()
        with body_lock:
            final_body = body.read()
        args.artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact = telemetry.write(args.artifact)
    finally:
        observation_queue.put(None)
        observation_queue.join()
        observer_thread.join(timeout=5.0)
        command_client.close()
        sampler.close()
        body.close()

    if not observed:
        raise RuntimeError("no full-chain telemetry records")
    stimulus_ns = chain.started_ns + int(trial.stimulus_start_s * 1e9)
    active = [row for row in observed
              if row["robot_state"]["body_sample_timestamp_ns"] >= stimulus_ns]
    response_rules = experiment["target_response"] if experiment is not None else {}
    response = sustained_heading_response(
        observed, stimulus_ns=stimulus_ns,
        threshold_rad=response_rules.get("min_abs_heading_delta_rad", 0.02),
        duration_s=response_rules.get("first_sustained_window_s", 0.2),
        same_sign_fraction=response_rules.get("min_same_sign_increment_fraction", 0.8),
    )
    safety_violations = sum(
        not math.isfinite(row["robot_facing_vyaw"])
        or abs(row["robot_facing_vx"]) > 0.08 or row["robot_facing_vy"] != 0.0
        or abs(row["robot_facing_vyaw"]) > 0.50
        for row in observed
    )
    outcome = "no_response"
    if response is not None and trial.target_present:
        response_row = next(row for row in active
                            if row["robot_state"]["body_sample_timestamp_ns"]
                            >= response["start_timestamp_ns"])
        outcome, response = score_target_response(
            config, trial, response, response_row, started_ns=chain.started_ns,
            center_tolerance_rad=response_rules.get("center_tolerance_rad", 0.05),
        )
    if not trial.target_present:
        outcome = "no_target"
    perception_active_frames = sum(row["perception"]["target_area"] > 0 for row in active)
    invalid_reasons = []
    if not health_before["healthy"] or not health_after["healthy"]:
        invalid_reasons.append("official_robotd_unhealthy")
    if not active or scheduler_result["scheduler_exceptions"]:
        invalid_reasons.append("missing_active_records_or_scheduler_exception")
    if scheduler_result["missed_deadlines"]["watchdog"]:
        invalid_reasons.append("missed_control_deadline")
    if trial.target_present and perception_active_frames == 0:
        invalid_reasons.append("camera_fixture_failed_to_show_target")
    if not trial.target_present and perception_active_frames:
        invalid_reasons.append("no_target_camera_fixture_contaminated")
    if any(row["robot_state"]["sample_timestamp_ns"] < row["timestamp_ns"] for row in observed):
        invalid_reasons.append("missing_post_command_state")
    heading_sample_skew_ms = [
        (row["robot_state"]["body_sample_timestamp_ns"] - row["timestamp_ns"]) / 1e6
        for row in observed
    ]
    max_skew_ms = experiment["validity"]["max_body_sample_delay_ms"] if experiment else 100.0
    if any(skew < 0 or skew > max_skew_ms for skew in heading_sample_skew_ms):
        invalid_reasons.append("heading_sample_too_late_for_command")
    if invalid_reasons:
        outcome = "invalid"
    summary = {
        "schema_version": "p7-02-target-trial-v1",
        "execution_target": "Thor", "hostname": socket.gethostname(),
        "started_utc": started_utc,
        "ended_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "identity": identity, "trial": trial.metadata(),
        "scenario_config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
        "experiment_sha256": experiment_hash,
        "target_drive_config_sha256": gain_hash,
        "steering_decoder_p7_sha256": steering_hash,
        "trial_spec_sha256": hashlib.sha256(args.trial_spec.read_bytes()).hexdigest(),
        "fixture_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "health_before": health_before, "health_after": health_after,
        "initial_body": initial_body, "final_body": final_body,
        "initial_heading_rad": initial_body["heading_rad"],
        "final_heading_delta_rad": wrap_angle(final_body["heading_rad"] - initial_body["heading_rad"]),
        "response": response, "outcome": outcome, "invalid_reasons": invalid_reasons,
        "max_heading_sample_delay_ms": max(heading_sample_skew_ms),
        "safety_limit_violations": safety_violations,
        "perception_active_frames": perception_active_frames,
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
