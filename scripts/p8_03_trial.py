"""One official moving-body P8-03 control trial on Thor.

The synthetic center is derived only while rendering RGB. Evaluator geometry is
recorded separately; the frozen perception/neural/decoder/safety stack sees RGB.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import socket
import subprocess
import threading
import time

from microduck_connectome.fractional_rgb_v21 import render_fractional_pixels
from microduck_connectome.g8_r5d_fixture import IsolatedStopPublisher, SUPPRESSED_NEUTRAL
from microduck_connectome.g8_r5d_metrics import first_sustained, pose_speeds
from microduck_connectome.graph import ConnectomeGraph
from microduck_connectome.looming_scenario import load_config, pixels_sha256
from microduck_connectome.looming_v2 import LoomingEstimatorV2, LoomingV2Config
from microduck_connectome.motion_adapter import RobotMotionAdapter
from microduck_connectome.neural_stop_arbiter import MotionLatched, NeuralStopMotionArbiter
from microduck_connectome.neural_stop_scheduler import NeuralStopRefreshScheduler
from microduck_connectome.fault_stop import FaultStopLatch
from microduck_connectome.p8_03_geometry import relative_trial
from microduck_connectome.robotd_client import RobotdClient
from microduck_connectome.watchdog import ControllerWatchdog
from scripts.p6_motion_fixture import JsonLines
from scripts.p6_telemetry_runtime_fixture import RobotStateSampler
from scripts.p7_pretrial_acquisition import validate_loaded_walk_policy
from scripts.p8_02_r1_trial import (LoomingChain, acknowledged_precondition_move,
                                    precondition_deadman_after_motion)
from scripts.p8_03_local_reference import PoseWithLineage, create_durable_arm_marker, wrap


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8")


def jsonl_write(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, sort_keys=True, separators=(",", ":"),
                                        allow_nan=False) + "\n" for row in rows), encoding="utf-8")


def verify(args) -> tuple[dict, dict, dict, dict, dict]:
    root = args.root.resolve(strict=True)
    execution_path = root / "config/p8_03_local_reference_v1.json"
    master_path = root / "config/p8_v2_final_protocol_v1.json"
    execution = json.loads(execution_path.read_text())
    master = json.loads(master_path.read_text())
    if (not socket.gethostname().startswith("jetsonthor")
            or platform.python_version_tuple()[:2] != ("3", "12")):
        raise RuntimeError("official Thor Python 3.12 required")
    if (subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
            != args.source_head or subprocess.check_output(
                ["git", "-C", str(root), "status", "--porcelain"], text=True).strip()):
        raise RuntimeError("source must be clean at reviewed HEAD")
    if root != Path(execution["source_path"]).resolve():
        raise RuntimeError("source checkout path differs from frozen execution config")
    for rel in ("config/p8_03_local_reference_v1.json", "config/p8_v2_final_protocol_v1.json",
                "scripts/p8_03_trial.py", "scripts/p8_03_batch.py", "scripts/p8_03_score.py",
                "scripts/p8_03_finalize.py", "scripts/p8_03_local_reference.py",
                "microduck_connectome/p8_03_geometry.py"):
        if (root / rel).read_bytes() != subprocess.check_output(
                ["git", "-C", str(root), "show", f"HEAD:{rel}"]):
            raise RuntimeError(f"uncommitted frozen source bytes: {rel}")
    if (str(args.socket) != str(Path(execution["state_dir"]) / "duck-a.sock")
            or args.body_port != execution["body_port"]):
        raise RuntimeError("trial socket/port mismatch")
    stage_name = {"D": "development", "S": "static", "R": "receding"}[args.stage]
    output = Path(execution[f"{stage_name}_output"])
    rows = (execution["development_gate"]["ids"] if args.stage == "D" else
            execution[f"final_{stage_name}"])
    if not 0 <= args.trial_index < len(rows):
        raise ValueError("trial index outside fixed matrix")
    raw = rows[args.trial_index]
    row = {"reset_id": raw["reset_id"], "ordinal": raw["ordinal"],
           "motion": raw["mode"], "arm_elapsed_s": raw["arm_elapsed_s"]}
    folder = output / row["reset_id"] / f"attempt-{args.attempt:02d}"
    if any(p.resolve().parent != folder.resolve() for p in
           (args.events, args.ledger, args.visual, args.summary, args.armed_marker,
            args.progress, args.policy_readback)):
        raise RuntimeError("raw output must use frozen attempt directory")
    if any(p.exists() for p in (args.events, args.ledger, args.visual, args.summary,
                                args.armed_marker)):
        raise RuntimeError("raw output path already exists")
    selected = master["selected_pipeline"]
    if (selected != execution["selected_pipeline"] or
            selected["visual_representation"] != "fractional_rgb_v21"
            or selected["graph_v2_sha256"] != execution["graph_sha256"]
            or selected["visual_hz"] != execution["visual_hz"]
            or selected["neural_hz"] != execution["neural_hz"]
            or selected["escape_threshold"] != .5):
        raise RuntimeError("selected P8-V2 controller mismatch")
    names = {"neural_model": "neural_model_v1.json", "sensory_mapping": "sensory_mapping_v1.json",
             "dn_readout": "dn_readout_v1.json", "escape_decoder": "escape_decoder_v1.json",
             "safety_envelope": "safety_envelope_v1.json", "watchdog": "watchdog_v1.json",
             "motion_adapter": "motion_adapter_v1.json", "scheduler": "scheduler_v1.json",
             "telemetry": "telemetry_v1.json"}
    if any(sha(root / "config" / rel) != selected["config_sha256"][name]
           for name, rel in names.items()):
        raise RuntimeError("frozen controller/safety config hash mismatch")
    for rel, expected in (("microduck_connectome/fractional_rgb_v21.py",
                           selected["fractional_rgb_module_sha256"]),
                          ("microduck_connectome/looming_v2.py",
                           selected["looming_v2_module_sha256"]),
                          ("config/looming_scenario_v1.json", selected["scenario_config_sha256"]),
                          ("config/p8_r3_visual_scheduler_v1.json",
                           selected["visual_scheduler_config_sha256"]),
                          ("data/manifests/controller-graph-v2.json",
                           selected["graph_manifest_sha256"])):
        if sha(root / rel) != expected:
            raise RuntimeError(f"frozen material hash mismatch: {rel}")
    for source, expected in ((args.microduck, execution["microduck_commit"]),
                             (args.microduck_rl, execution["microduck_rl_commit"])):
        if subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"],
                                   text=True).strip() != expected:
            raise RuntimeError("upstream commit mismatch")
    if sha(Path(execution["graph_path"])) != execution["graph_sha256"]:
        raise RuntimeError("graph artifact hash mismatch")
    if sha(Path(execution["walking_policy_path"])) != execution["walking_policy_sha256"]:
        raise RuntimeError("walking policy hash mismatch")
    validate_loaded_walk_policy(json.loads(args.policy_readback.read_text()),
                                Path(execution["walking_policy_path"]),
                                execution["walking_policy_sha256"])
    if args.local_reference.resolve().parent != folder.resolve():
        raise RuntimeError("local reference path differs from frozen attempt")
    reset = json.loads(args.local_reference.read_text())
    if (reset.get("schema_version") != "p8-03-local-reference-v1" or
            reset.get("result") != "PASS" or
            reset.get("reset_id") != row["reset_id"] or
            reset.get("attempt") != args.attempt):
        raise RuntimeError("per-reset settled local reference was not verified")
    reference_hash = sha(args.local_reference)
    return master, execution, row, selected, load_config(root / "config/looming_scenario_v1.json")


def run(args) -> int:
    master, execution, planned, selected, scenario = verify(args)
    root = args.root.resolve()
    mode = planned["motion"]
    graph = ConnectomeGraph.from_cache(Path(execution["graph_path"]).parent,
                                        execution["graph_sha256"])
    estimator = selected["looming_estimator"]
    estimator_config = LoomingV2Config(
        method=estimator["method"], area_epsilon=estimator["area_epsilon"],
        full_scale_rate_per_s=estimator["full_scale_rate_per_s"],
        max_gap_ms=estimator["max_gap_ms"], window_ms=estimator["window_ms"])
    robot = RobotdClient(args.socket, timeout_s=2.0)
    robot.connect()
    robot.enable(True)
    health_before = robot.health()
    if health_before.get("healthy") is not True:
        raise RuntimeError("robotd health is not healthy before neural arm")
    adapter = RobotMotionAdapter(robot, root / "config/motion_adapter_v1.json")
    publisher = IsolatedStopPublisher(adapter)
    move_client = JsonLines(args.socket)
    move_client.request("hello", {"api_version": 31})
    sampler = RobotStateSampler(args.socket)
    pose_reader = PoseWithLineage(args.body_port)
    pose_lock = threading.Lock()
    arbiter = NeuralStopMotionArbiter()
    chain = LoomingChain(root, graph, scenario, pose_reader, pose_lock,
                         planned["arm_elapsed_s"], arbiter,
                         estimator=LoomingEstimatorV2(estimator_config), visual_hz=20,
                         visual_representation="fractional_rgb_v21")
    watchdog = ControllerWatchdog(root / "config/watchdog_v1.json")
    fault_latch = FaultStopLatch()
    events: list[dict] = []
    events.append({"kind": "robotd_health_before", "timestamp_ns": time.monotonic_ns(),
                   "healthy": health_before["healthy"]})
    geometry: list[dict] = []
    motion_errors: list[str] = []
    observer_errors: list[str] = []
    scheduler_errors: list[str] = []
    motion_rows: list[dict] = []
    precondition_rows: list[dict] = []
    if sha(args.local_reference) != reference_hash:
        raise RuntimeError("local reference changed after trial verification")
    reset = json.loads(args.local_reference.read_text())
    events.append({"kind": "local_reference", "timestamp_ns": time.monotonic_ns(),
                   "result": reset["result"], "reference": reset["reference"],
                   "capture_ns": reset["capture_ns"],
                   "reset_id": reset["reset_id"], "attempt": reset["attempt"]})
    arm_ns = None
    scheduler_result = None
    stop_acks: list[int] = []
    published: dict[int, tuple[int, int]] = {}
    lock = threading.Lock()

    def render(config, _trial, *, pose, elapsed_s):
        pose_source = pose_reader.source(pose)
        after_arm = max(0.0, elapsed_s - planned["arm_elapsed_s"])
        virtual, distance = relative_trial(
            pose=pose, trial_id=planned["reset_id"], ordinal=planned["ordinal"],
            mode=mode, elapsed_after_arm_s=after_arm)
        pixels = render_fractional_pixels(config, virtual, pose=pose, elapsed_s=0)
        area = sum(p[0] for row in pixels for p in row) / (
            255 * config["image_width_px"] * config["image_height_px"])
        geometry.append({"kind": "visual_frame", "timestamp_ns": time.monotonic_ns(),
                         "source_valid": True, "distance_m": distance,
                         "target_distance_m": distance, "image_area": area,
                         "pixels_sha256": pixels_sha256(pixels),
                         "bearing_rad": 0.0, "pose": dict(pose),
                         "pose_request_ns": pose_source["request_ns"],
                         "pose_response_ns": pose_source["response_ns"],
                         "raw_body_packet": pose_source["raw_packet"],
                         "virtual_center_x_m": virtual.anchor_x_m,
                         "virtual_center_y_m": virtual.anchor_y_m})
        return pixels

    chain.render_pixels = render

    original_perception = chain.perception

    def perception_with_tof_lineage(now_ns):
        frame = original_perception(now_ns)
        if frame is not None:
            chain.visual_frames[-1].update({
                "tof_left_mm": scenario["tof_mm"],
                "tof_center_mm": scenario["tof_mm"],
                "tof_right_mm": scenario["tof_mm"],
                "tof_timestamp_ns": now_ns,
                "tof_frame_id": chain.visual_frames[-1]["frame_id"],
                "tof_source": "frozen_synthetic_fixture"})
        return frame

    chain.perception = perception_with_tof_lineage

    def publish(output):
        call = time.monotonic_ns()
        result = publisher.send(output)
        ack = time.monotonic_ns()
        with lock:
            published[output["intent"]["sequence"]] = (call, ack)
            if result == "robot_stop_refreshed":
                stop_acks.append(ack)
        return result

    def observe(update, output, transport):
        seq = output["intent"]["sequence"]
        with lock:
            call, ack = published.pop(seq)
        if update is not None:
            chain.neural_stop_latch.confirm(
                output=output, transport_result=transport, ack_ns=ack,
                source_neural_sequence=update.readout["sequence"],
                source_intent_stop=bool(update.behavior_intent["stop"]))
        event = {"kind": "control_publish", "timestamp_ns": ack,
                 "sequence": seq, "ack_ns": ack,
                 "transport": "robot.stop" if transport == "robot_stop_refreshed" else transport,
                 "neural_origin": bool(update is not None and update.trace is not None
                                       and update.trace["male_cns"]["healthy"]
                                       and update.trace["dn_readout"]["escape"] >= .5
                                       and update.trace["raw_decoded_intent"]["stop"]),
                 "watchdog_state": output["watchdog_state"],
                 "stop": output["intent"]["stop"], "call_ns": call,
                 "intent": dict(output["intent"])}
        with lock:
            events.append(event)

    scheduler = NeuralStopRefreshScheduler(
        fault_latch=fault_latch, motion_arbiter=arbiter,
        config=root / "config/p8_r3_visual_scheduler_v1.json", watchdog=watchdog,
        perception_step=chain.perception, neural_step=chain.neural,
        publisher=publish, control_observer=observe)
    pre = master["scenario"]["moving_precondition"]
    move_gate = execution["moving_gate"]
    try:
        gate = execution["settled_gate"]
        transition: list[dict] = []
        transition_health = None
        transition_health_ns = 0
        transition_end = time.monotonic_ns() + int(gate["settle_window_s"] * 1e9)
        while time.monotonic_ns() <= transition_end:
            tick = time.monotonic_ns()
            if transition_health is None or tick - transition_health_ns >= 200_000_000:
                transition_health = robot.health()
                transition_health_ns = time.monotonic_ns()
            with pose_lock:
                stationary_pose = pose_reader.read()
                source = pose_reader.source(stationary_pose)
            state, state_ns = sampler.after(tick)
            reference = reset["reference"]
            drift = math.hypot(stationary_pose["x_m"] - reference["x_m"],
                               stationary_pose["y_m"] - reference["y_m"])
            z_drift = abs(stationary_pose["trunk_z_m"] - reference["trunk_z_m"])
            heading_drift = abs(wrap(stationary_pose["heading_rad"] -
                                     reference["heading_rad"]))
            applied = state["move"]["applied"]
            row = {"kind": "reference_transition", "timestamp_ns": source["response_ns"],
                   "pose": dict(stationary_pose), "pose_request_ns": source["request_ns"],
                   "raw_body_packet": source["raw_packet"], "state_ns": state_ns,
                   "health": transition_health,
                   "health_ns": transition_health_ns,
                   "policy": state.get("policy"),
                   "safety": state.get("safety"),
                   "applied_velocity": applied, "planar_drift_m": drift,
                   "z_drift_m": z_drift, "heading_drift_rad": heading_drift}
            transition.append(row)
            events.append(row)
            if (drift > gate["max_planar_drift_m"] or
                    z_drift > gate["max_z_drift_m"] or
                    heading_drift > gate["max_heading_drift_rad"] or
                    source["response_ns"] - source["request_ns"] >
                    gate["max_pose_response_age_ms"] * 1e6 or
                    abs(source["response_ns"] - state_ns) >
                    gate["max_robotd_state_age_ms"] * 1e6 or
                    abs(source["response_ns"] - transition_health_ns) >
                    gate["max_health_age_ms"] * 1e6 or
                    transition_health.get("healthy") is not True or
                    transition_health.get("degraded") not in (None, False) or
                    transition_health.get("control_loop", {}).get("ticks", 0) <= 0 or
                    state.get("policy") not in gate["allowed_observed_policy_states"] or
                    state.get("safety", {}).get("fallen") or
                    state.get("safety", {}).get("limp") or
                    any(abs(v) > gate[k] for v, k in zip(applied, (
                        "max_abs_applied_vx_mps", "max_abs_applied_vy_mps",
                        "max_abs_applied_vyaw_radps")))):
                raise RuntimeError("local reference invalidated before movement")
            time.sleep(max(0, .02 - (time.monotonic_ns() - tick) / 1e9))
        if (len(transition) < gate["minimum_distinct_pose_samples"] or
                transition[-1]["timestamp_ns"] - transition[0]["timestamp_ns"] <
                int((gate["settle_window_s"] - .06) * 1e9)):
            raise RuntimeError("reference transition telemetry incomplete")
        poses = []
        for i in range(round(pre["duration_s"] * 1000 / pre["command_period_ms"])):
            tick = time.monotonic_ns()
            result, call, write, ack = arbiter.move(lambda: acknowledged_precondition_move(
                move_client, vx=pre["vx_mps"], vy=pre["vy_mps"], vyaw=pre["vyaw_radps"]))
            state, state_ns = sampler.after(ack)
            with pose_lock:
                pose = pose_reader.read()
            pose_ns = time.monotonic_ns()
            poses.append({"timestamp_ns": pose_ns, "x_m": pose["x_m"],
                          "y_m": pose["y_m"]})
            precondition_rows.append({"kind": "precondition_motion", "timestamp_ns": ack,
                                      "robot_move_ack": result, "applied_velocity": state["move"]["applied"],
                                      "limited_by": state["move"].get("limited_by", []),
                                      "robot_t_ns": state.get("t_ns"), "state_ns": state_ns,
                                      "pose": dict(pose), "pose_ns": pose_ns})
            time.sleep(max(0, .020 - (time.monotonic_ns() - tick) / 1e9))
        speeds = pose_speeds(poses, window_ms=100, max_window_ms=140)
        confirmed = first_sustained(speeds, threshold_mps=.015,
                                    duration_ms=200, at_or_above=True)
        displacement = math.hypot(poses[-1]["x_m"] - poses[0]["x_m"],
                                  poses[-1]["y_m"] - poses[0]["y_m"])
        last_applied = precondition_rows[-1]["applied_velocity"][0]
        if (confirmed is None or confirmed <= reset["capture_ns"]
                or displacement < move_gate["minimum_trunk_displacement_m"]
                or last_applied < move_gate["minimum_fresh_applied_vx_mps"]
                or any(r["state_ns"] < r["timestamp_ns"] or
                       r["state_ns"] - r["timestamp_ns"] >
                       move_gate["maximum_state_age_ms"] * 1e6 or
                       r["pose_ns"] - r["state_ns"] >
                       move_gate["maximum_pose_age_ms"] * 1e6 or
                       r["applied_velocity"][0] < 0 or
                       any(reason in ("deadman", "fault", "safety")
                           for reason in r["limited_by"]) for r in precondition_rows)
                or precondition_deadman_after_motion(
                    [{"robot_state": {"limited_by": r["limited_by"],
                                      "robot_t_ns": r["robot_t_ns"]}} for r in precondition_rows],
                    confirmed)):
            raise RuntimeError("measured moving-body precondition failed")
        with pose_lock:
            pose = pose_reader.read()
        chain.trial, _ = relative_trial(pose=pose, trial_id=planned["reset_id"],
                                        ordinal=planned["ordinal"], mode=mode,
                                        elapsed_after_arm_s=0.0)
        baseline_pixels = render_fractional_pixels(scenario, chain.trial, pose=pose, elapsed_s=0)
        baseline_area = sum(p[0] for line in baseline_pixels for p in line) / (
            255 * scenario["image_width_px"] * scenario["image_height_px"])
        events.append({"kind": "prearm_visual_anchor", "timestamp_ns": time.monotonic_ns(),
                       "distance_m": .85, "image_area": baseline_area,
                       "pose": dict(pose)})
        health_prearm = robot.health()
        health_prearm_ns = time.monotonic_ns()
        if (health_prearm.get("healthy") is not True or
                health_prearm.get("degraded") not in (None, False) or
                health_prearm.get("control_loop", {}).get("ticks", 0) <= 0 or
                sha(args.local_reference) != reference_hash):
            raise RuntimeError("health or local reference invalid before arm")
        events.append({"kind": "prearm_health", "timestamp_ns": health_prearm_ns,
                       "health": health_prearm})
        candidate_arm_ns = time.monotonic_ns()
        if ((candidate_arm_ns - health_prearm_ns) / 1e6 >
                execution["settled_gate"]["max_prearm_health_age_ms"]):
            raise RuntimeError("prearm health stale")
        marker = {"schema_version": "p8-03-local-arm-v1",
                  "task": "P8-03-LOCAL-REFERENCE-PROTOCOL-V1",
                  "reset_id": planned["reset_id"], "ordinal": planned["ordinal"],
                  "attempt": args.attempt, "source_head": args.source_head,
                  "config_sha256": sha(root / "config/p8_03_local_reference_v1.json"),
                  "armed_at_utc_ns": time.time_ns(),
                  "armed_at_monotonic_ns": candidate_arm_ns, "state": "ARMED"}
        create_durable_arm_marker(args.armed_marker, marker)
        arm_ns = candidate_arm_ns
        jsonl_write(args.progress, [{"state": "NEURAL_OBSERVATION_ARMED",
                                    "timestamp_ns": arm_ns}])
        events.append({"kind": "arm", "timestamp_ns": arm_ns,
                       "reset_id": planned["reset_id"], "ordinal": planned["ordinal"],
                       "moving_confirmed_ns": confirmed,
                       "precondition_displacement_m": displacement,
                       "precondition_applied_vx_mps": last_applied})
        frame = chain.perception(arm_ns)
        update = chain.neural(frame, arm_ns)
        if (update is None or update.behavior_intent["stop"]
                or not watchdog.observe_neural(update.readout)
                or not watchdog.observe_behavior(update.behavior_intent)):
            raise RuntimeError("unhealthy or stopping neural prime")
        scheduler.prime_perception(frame, now_ns=time.monotonic_ns())
        deadline = arm_ns + execution["scored_window_ms"] * 1_000_000

        def motion_worker():
            while time.monotonic_ns() <= deadline and not arbiter.latched.is_set():
                tick = time.monotonic_ns()
                try:
                    result, call, write, ack = arbiter.move(
                        lambda: acknowledged_precondition_move(
                            move_client, vx=pre["vx_mps"], vy=pre["vy_mps"],
                            vyaw=pre["vyaw_radps"]))
                    state, state_ns = sampler.after(ack)
                    with pose_lock:
                        measured_pose = pose_reader.read()
                    with lock:
                        motion_rows.append({"kind": "motion_refresh", "timestamp_ns": ack,
                                            "positive_ack": result is not None,
                                            "robot_move_result": result,
                                            "call_ns": call, "write_ns": write})
                        events.append({"kind": "robot_state", "timestamp_ns": state_ns,
                                       "deadman_limited": "deadman" in str(
                                           state["move"].get("limited_by", [])).lower(),
                                       "requested_velocity": state["move"]["requested"],
                                       "applied_velocity": state["move"]["applied"],
                                       "pose": dict(measured_pose)})
                except MotionLatched:
                    break
                except BaseException as error:
                    motion_errors.append(f"{type(error).__name__}: {error}")
                    arbiter.latch("motion_refresh_fault")
                    break
                time.sleep(max(0, .020 - (time.monotonic_ns() - tick) / 1e9))

        motion_thread = threading.Thread(target=motion_worker, name="p8-03-motion")
        scheduler_thread = threading.Thread(target=lambda: run_scheduler(), name="p8-03-scheduler")

        def run_scheduler():
            nonlocal scheduler_result
            try:
                scheduler_result = scheduler.run(1.5)
            except BaseException as error:
                scheduler_errors.append(f"{type(error).__name__}: {error}")

        motion_thread.start()
        scheduler_thread.start()
        time.sleep(max(0, (deadline - time.monotonic_ns()) / 1e9))
        scheduler.request_complete()
        motion_thread.join(timeout=3)
        scheduler_thread.join(timeout=3)
        if motion_thread.is_alive() or scheduler_thread.is_alive():
            scheduler_errors.append("worker_join_timeout")
        events.append({"kind": "window_complete", "timestamp_ns": time.monotonic_ns()})
    except BaseException as error:
        events.append({"kind": "fixture_error", "timestamp_ns": time.monotonic_ns(),
                       "error": f"{type(error).__name__}: {error}"})
    finally:
        if scheduler._threads and not scheduler._fixture_complete.is_set():
            scheduler.request_complete()
        arbiter.latch("planned_cleanup" if arm_ns is not None else "safe_abort")
        for name in ("motion_thread", "scheduler_thread"):
            worker = locals().get(name)
            if worker is not None and worker.is_alive():
                worker.join(timeout=3)
                if worker.is_alive():
                    events.append({"kind": "fixture_error", "timestamp_ns": time.monotonic_ns(),
                                   "error": f"{name} did not stop before cleanup"})
        try:
            result = move_client.request("robot.stop", {})
            events.append({"kind": "cleanup", "timestamp_ns": time.monotonic_ns(),
                           "robot_stop_result": result})
        except BaseException as error:
            events.append({"kind": "fixture_error", "timestamp_ns": time.monotonic_ns(),
                           "error": f"cleanup:{type(error).__name__}: {error}"})
        try:
            health_after = robot.health()
        except BaseException as error:
            health_after = {"healthy": False, "error": f"{type(error).__name__}: {error}"}
            events.append({"kind": "fixture_error", "timestamp_ns": time.monotonic_ns(),
                           "error": "robotd health after trial unavailable"})
        events.append({"kind": "robotd_health_after", "timestamp_ns": time.monotonic_ns(),
                       "healthy": health_after.get("healthy") is True})
        move_client.close()
        sampler.close()
        pose_reader.close()
        robot.close()

    for row in chain.neural_ledger:
        events.append({"kind": "neural_step", "timestamp_ns": row["neural_call_timestamp_ns"],
                       "runtime_healthy": bool(row.get("dn_runtime_healthy")
                                               and row.get("male_cns_healthy")),
                       "dn_escape": row.get("dn_escape", 0),
                       "decoder_stop": row.get("raw_decoder_stop", False),
                       "source_age_ms": row.get("perception_age_ms", 1e9),
                       "source_frame_id": row.get("perception_frame_id")})
    for i, row in enumerate(geometry):
        if i < len(chain.visual_frames):
            row["timestamp_ns"] = chain.visual_frames[i]["timestamp_ns"]
            row["source_valid"] = chain.visual_frames[i]["perception_valid"]
            row["source_frame_id"] = chain.visual_frames[i]["frame_id"]
            row["tof_timestamp_ns"] = chain.visual_frames[i]["tof_timestamp_ns"]
            row["tof_frame_id"] = chain.visual_frames[i]["tof_frame_id"]
    events.extend(geometry)
    events.extend(motion_rows)
    events.extend(precondition_rows)
    for error in motion_errors + observer_errors + scheduler_errors:
        events.append({"kind": "scheduler_exception", "timestamp_ns": time.monotonic_ns(),
                       "error": error})
    violation_count = sum(
        any(not math.isfinite(v) for v in
            list(r.get("requested_velocity", [])) + list(r.get("applied_velocity", [])))
        or any(abs(v) > lim for v, lim in zip(r.get("applied_velocity", []), (.08, 0, .5)))
        or any(abs(v) > lim for v, lim in zip(r.get("requested_velocity", []), (.08, 0, .5)))
        for r in events if r["kind"] == "robot_state")
    violation_count += publisher.nonzero_count + publisher.post_stop_move_count
    events.append({"kind": "safety_snapshot", "timestamp_ns": time.monotonic_ns(),
                   "violations": violation_count, "scheduler_result": scheduler_result,
                   "stop_acks": stop_acks, "arbiter_latch_reason": arbiter.latch_reason})
    events.sort(key=lambda r: r["timestamp_ns"])
    jsonl_write(args.events, events)
    jsonl_write(args.ledger, chain.neural_ledger)
    jsonl_write(args.visual, chain.visual_frames)
    fixture_errors = [r["error"] for r in events if r["kind"] in
                      ("fixture_error", "scheduler_exception")]
    summary = {"schema_version": "p8-03-local-trial-v1", "reset_id": planned["reset_id"],
               "ordinal": planned["ordinal"], "stage": args.stage, "source_head": args.source_head,
               "armed": arm_ns is not None, "event_sha256": sha(args.events),
               "neural_ledger_sha256": sha(args.ledger), "visual_sha256": sha(args.visual),
               "scheduler_exceptions": len(scheduler_errors),
               "safety_limit_violations": violation_count,
               "neural_stop_acks": len(stop_acks), "fixture_errors": fixture_errors}
    summary["robotd_health_before"] = health_before
    summary["robotd_health_after"] = health_after
    json_write(args.summary, summary)
    return 0 if not summary["fixture_errors"] and arm_ns is not None else 1


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--stage", choices=("D", "S", "R"), required=True)
    ap.add_argument("--trial-index", type=int, required=True)
    ap.add_argument("--attempt", type=int, required=True)
    ap.add_argument("--socket", required=True)
    ap.add_argument("--body-port", type=int, required=True)
    ap.add_argument("--microduck", type=Path, required=True)
    ap.add_argument("--microduck-rl", type=Path, required=True)
    ap.add_argument("--source-head", required=True)
    for name in ("policy_readback", "local_reference", "armed_marker", "progress", "events", "ledger",
                 "visual", "summary"):
        ap.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
    raise SystemExit(run(ap.parse_args()))


if __name__ == "__main__":
    main()
