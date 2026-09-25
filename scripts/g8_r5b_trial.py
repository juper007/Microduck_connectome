"""Official Thor moving-body neural-stop recertification, one frozen trial."""
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
import subprocess
import threading
import time

from microduck_connectome.g8_r5b_metrics import (
    causal_timeline_ok, first_sustained, is_healthy_neural_stop, pose_speeds,
    valid_state_path,
)
from microduck_connectome.graph import ConnectomeGraph
from microduck_connectome.looming_scenario import load_config, make_trial, render_pixels
from microduck_connectome.motion_adapter import RobotMotionAdapter
from microduck_connectome.robotd_client import RobotdClient
from microduck_connectome.scheduler import ClosedLoopScheduler
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


class LoomingChain(FullChain):
    def __init__(self, root, graph, scenario, pose_reader, pose_lock, elapsed_start_s):
        super().__init__(root, graph)
        self.scenario_config = scenario
        self.pose_reader = pose_reader
        self.pose_lock = pose_lock
        self.elapsed_start_s = elapsed_start_s
        self.trial = None
        self.started_ns = None
        self.scenario = "stop"

    def perception(self, now_ns):
        if self.trial is None:
            raise RuntimeError("looming cannot start before motion confirmation")
        if self.started_ns is None:
            self.started_ns = now_ns
        self.frame_id += 1
        elapsed = self.elapsed_start_s + (now_ns - self.started_ns) / 1e9
        with self.pose_lock:
            pose = self.pose_reader.read()
        pixels = render_pixels(self.scenario_config, self.trial, pose=pose, elapsed_s=elapsed)
        tof = self.scenario_config["tof_mm"]
        return self.pipeline.process(
            pixels, camera_timestamp_ns=now_ns, camera_frame_id=self.frame_id,
            tof_left_mm=tof, tof_center_mm=tof, tof_right_mm=tof,
            tof_timestamp_ns=now_ns, tof_frame_id=self.frame_id, now_ns=now_ns,
        )


def verify_protocol(root, protocol_path, protocol, args):
    if socket.gethostname().startswith("jetsonthor") is False or platform.python_version_tuple()[:2] != ("3", "12"):
        raise RuntimeError("official Thor Python 3.12 required")
    if protocol["schema_version"] != "g8-r5b-moving-neural-stop-protocol-v1":
        raise ValueError("protocol version mismatch")
    if git_head(root) != args.source_head:
        raise RuntimeError("source head mismatch")
    if subprocess.check_output(["git", "-C", str(root), "status", "--porcelain"], text=True).strip():
        raise RuntimeError("final trial requires a clean source checkout")
    committed = subprocess.check_output(["git", "-C", str(root), "show",
                                         "HEAD:config/g8_r5b_motion_stop_v1.json"])
    if protocol_path.read_bytes() != committed:
        raise RuntimeError("protocol differs from committed bytes")
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
    scenario_path = root / "config/looming_scenario_v1.json"
    if sha(scenario_path) != protocol["scenario_config_sha256"]:
        raise RuntimeError("frozen scenario hash mismatch")
    adapter = json.loads((root / "config/motion_adapter_v1.json").read_text())
    escape = json.loads((root / "config/escape_decoder_v1.json").read_text())
    envelope = json.loads((root / "config/safety_envelope_v1.json").read_text())
    if adapter["stop_transport"] != protocol["stop_transport"] or escape["threshold"] != protocol["escape_threshold"]:
        raise RuntimeError("frozen stop transport/threshold mismatch")
    pre = protocol["precondition"]
    if (abs(pre["vx_mps"]) > envelope["max_abs_vx_mps"] or pre["vy_mps"] != 0
            or abs(pre["vyaw_radps"]) > envelope["max_abs_vyaw_radps"]):
        raise RuntimeError("precondition exceeds frozen safety envelope")
    return manifest, graph_path, load_config(scenario_path)


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


def run(args):
    root = args.root.resolve()
    protocol_path = root / "config/g8_r5b_motion_stop_v1.json"
    protocol = json.loads(protocol_path.read_text())
    manifest, graph_path, scenario = verify_protocol(root, protocol_path, protocol, args)
    seed = protocol["scenario_seeds"][args.trial_index]
    trial_id = f"g8-r5b-{args.trial_index + 1:02d}-{seed}"
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
    precondition = JsonLines(args.socket)
    precondition.request("hello", {"api_version": 31})
    sampler = RobotStateSampler(args.socket)
    pose_reader = OfficialPoseReader(args.body_port)
    pose_lock = threading.Lock()
    telemetry = EndToEndTelemetry(root / "config/telemetry_v1.json", identity)
    chain = LoomingChain(root, graph, scenario, pose_reader, pose_lock,
                         protocol["scenario_elapsed_start_s"])
    watchdog = ControllerWatchdog(root / "config/watchdog_v1.json")
    health_before = robot.health()
    pose_rows = []
    events = []
    observer_errors = []
    pending = queue.Queue(maxsize=512)
    publish_time = {}
    started_ns = time.monotonic_ns()
    events.append({"timestamp_ns": started_ns, "kind": "transition", "state": "SETUP"})

    def observer_worker():
        while True:
            item = pending.get()
            try:
                if item is None:
                    return
                update, output, transport, sent_ns, ack_ns = item
                state, received_ns = sampler.after(ack_ns)
                with pose_lock:
                    pose = pose_reader.read()
                    pose_ns = time.monotonic_ns()
                pose_rows.append({"timestamp_ns": pose_ns, "x_m": pose["x_m"],
                                  "y_m": pose["y_m"], "phase": "neural"})
                events.append({"timestamp_ns": ack_ns, "kind": "control_publish",
                               "sequence": output["intent"]["sequence"],
                               "watchdog_state": output["watchdog_state"],
                               "robot_facing_stop": output["intent"]["stop"],
                               "transport_result": transport,
                               "publish_call_started_ns": sent_ns,
                               "publish_ack_returned_ns": ack_ns})
                if update is None or update.trace is None:
                    continue
                trace = copy.deepcopy(update.trace)
                trace["male_cns"].pop("scenario_fixture", None)
                telemetry.append(
                    trial_id=trial_id, scenario="stop",
                    timestamp_ns=output["intent"]["timestamp_ns"],
                    sequence=output["intent"]["sequence"], trace=trace,
                    watchdog_output=output, robotd_transport_result=transport,
                    robotd_connected=robot.status.connected,
                    robot_state=robot_state_record(state, received_ns, pose, pose_ns,
                                                   sent_ns, ack_ns),
                )
            except BaseException as error:
                observer_errors.append(f"{type(error).__name__}: {error}")
            finally:
                pending.task_done()

    observer = threading.Thread(target=observer_worker, name="g8-r5b-observer")
    observer.start()

    def publish(output):
        call_ns = time.monotonic_ns()
        result = adapter.send(output)
        ack_ns = time.monotonic_ns()
        publish_time[output["intent"]["sequence"]] = (call_ns, ack_ns)
        return result

    def observe(update, output, transport):
        if observer_errors:
            raise RuntimeError(observer_errors[0])
        sequence = output["intent"]["sequence"]
        call_ns, ack_ns = publish_time.pop(sequence)
        pending.put_nowait((update, output, transport, call_ns, ack_ns))

    scheduler = ClosedLoopScheduler(
        config=root / "config/scheduler_v1.json", watchdog=watchdog,
        perception_step=chain.perception, neural_step=chain.neural,
        publisher=publish, control_observer=observe,
    )
    scheduler_result = None
    phase_started_ns = None
    precondition_status = None
    runtime_finished_ns = None
    try:
        events.append({"timestamp_ns": time.monotonic_ns(), "kind": "transition",
                       "state": "MOTION_PRECONDITION"})
        for index in range(round(pre["duration_s"] * 1000 / pre["command_period_ms"])):
            tick_ns = time.monotonic_ns()
            precondition.notify("robot.move", {"vx": pre["vx_mps"],
                                                "vy": pre["vy_mps"],
                                                "vyaw": pre["vyaw_radps"]})
            send_done_ns = time.monotonic_ns()
            state, received_ns = sampler.after(send_done_ns)
            with pose_lock:
                pose = pose_reader.read()
                pose_ns = time.monotonic_ns()
            pose_rows.append({"timestamp_ns": pose_ns, "x_m": pose["x_m"],
                              "y_m": pose["y_m"], "phase": "precondition"})
            events.append({"timestamp_ns": pose_ns, "kind": "precondition_motion",
                           "source_label": pre["source_label"], "index": index,
                           "command_created_at_ns": tick_ns,
                           "command_socket_write_completed_at_ns": send_done_ns,
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
        events.append({"timestamp_ns": motion_confirmed_ns, "kind": "transition",
                       "state": "MOTION_CONFIRMED"})
        with pose_lock:
            initial_pose = pose_reader.read()
        chain.trial = make_trial(scenario, trial_id=trial_id, seed=seed,
                                 motion="approaching", initial_pose=initial_pose)
        phase_started_ns = time.monotonic_ns()
        events.append({"timestamp_ns": phase_started_ns, "kind": "transition",
                       "state": "NEURAL_LOOMING"})
        first_frame = chain.perception(phase_started_ns)
        first_update = chain.neural(first_frame, phase_started_ns)
        if not watchdog.observe_neural(first_update.readout) or not watchdog.observe_behavior(first_update.behavior_intent):
            raise RuntimeError("cannot prime healthy watchdog at neural phase handoff")
        scheduler_result = scheduler.run(protocol["neural_phase_duration_s"])
        pending.join()
        runtime_finished_ns = time.monotonic_ns()
        if observer_errors:
            raise RuntimeError(observer_errors[0])
    except BaseException as error:
        runtime_finished_ns = time.monotonic_ns()
        events.append({"timestamp_ns": time.monotonic_ns(), "kind": "fixture_error",
                       "error": f"{type(error).__name__}: {error}"})
    finally:
        pending.put(None)
        pending.join()
        observer.join(timeout=5)
        try:
            precondition.request("robot.stop", {})
        except BaseException as error:
            events.append({"timestamp_ns": time.monotonic_ns(), "kind": "cleanup_error",
                           "error": f"{type(error).__name__}: {error}"})
        health_after = robot.health()
        precondition.close()
        pose_reader.close()
        sampler.close()
        robot.close()

    records = telemetry.records()
    args.raw.parent.mkdir(parents=True, exist_ok=True)
    trace_artifact = telemetry.write(args.raw) if records else None
    all_speeds = pose_speeds(pose_rows, window_ms=metric["speed_window_ms"],
                             max_window_ms=metric["speed_window_max_ms"])
    neural = [record for record in records if is_healthy_neural_stop(
        record, threshold=protocol["escape_threshold"])]
    first_stop = next((record for record in records if record["robot_facing_stop"]), None)
    first_neural = neural[0] if neural else None
    first_stop_is_neural = bool(first_neural and first_stop
                                and first_stop["sequence"] == first_neural["sequence"])
    stop_created_ns = first_neural["pre_safety_intent"]["timestamp_ns"] if first_neural else None
    stop_ack_ns = first_neural["robot_state"]["publish_ack_returned_ns"] if first_neural else None
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
    shutdown_ns = next((record["timestamp_ns"] for record in records
                        if record["watchdog_state"] != "healthy"), None)
    stopped_confirmed_ns = (first_sustained(
        all_speeds, threshold_mps=stopped_rule["stopped_threshold_mps"],
        duration_ms=stopped_rule["stop_confirmation_ms"], at_or_above=False,
        after_ns=stop_ack_ns, before_ns=shutdown_ns)
        if stop_ack_ns is not None else None)
    post_stop_speeds = [row for row in all_speeds if stop_ack_ns is not None
                        and row["timestamp_ns"] >= stop_ack_ns]
    confirmed_sample = next((row for row in post_stop_speeds
                             if row["timestamp_ns"] == stopped_confirmed_ns), None)
    first_stopped_ns = next((row["timestamp_ns"] for row in post_stop_speeds
                             if row["pose_speed_mps"] is not None
                             and row["pose_speed_mps"] <= stopped_rule["stopped_threshold_mps"]), None)
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
    lplc2_peak = max((max(row["stimulus_channels"]["lplc2_left"],
                          row["stimulus_channels"]["lplc2_right"]) for row in records), default=0)
    looming_peak = max((row["perception"]["looming"] for row in records), default=0)
    escape_peak = max((row["dn_activity"]["escape"] for row in records), default=0)
    first_looming_ns = next((r["perception"]["timestamp_ns"] for r in records
                             if r["perception"]["looming"] > 0), None)
    first_escape_ns = next((r["dn_activity"]["timestamp_ns"] for r in records
                            if r["dn_activity"]["escape"] >= protocol["escape_threshold"]), None)
    scheduler_exceptions = scheduler_result["scheduler_exceptions"] if scheduler_result else None
    checks = {
        "precondition_motion_confirmed": bool(precondition_status and precondition_status["motion_confirmed_at_ns"]),
        "pre_stop_body_still_moving": pre_stop_moving,
        "healthy_neural_stop_first": first_stop_is_neural,
        "looming_lplc2_escape_present": looming_peak > 0 and lplc2_peak > 0 and escape_peak >= protocol["escape_threshold"],
        "robot_stop_ack": stop_ack_ns is not None,
        "actual_stopped_before_shutdown": stopped_confirmed_ns is not None,
        "safety_bounds": violation_count == protocol["safety_limit_violations_max"],
        "scheduler_healthy": scheduler_exceptions == protocol["scheduler_exceptions_max"],
        "robotd_healthy": bool(health_before["healthy"] and health_after["healthy"]),
        "timing_reconstructible": causal_timeline_ok(
            precondition_status["motion_confirmed_at_ns"] if precondition_status else None,
            phase_started_ns, first_looming_ns, first_escape_ns, stop_created_ns,
            first_neural["timestamp_ns"] if first_neural else None,
            first_neural["robot_state"]["publish_call_started_ns"] if first_neural else None,
            stop_ack_ns, stopped_confirmed_ns),
        "within_frozen_trial_duration": (runtime_finished_ns - started_ns) / 1e9
                                         <= protocol["maximum_total_trial_duration_s"],
    }
    if first_neural:
        events.extend([
            {"timestamp_ns": stop_created_ns, "kind": "transition", "state": "NEURAL_STOP_DETECTED"},
            {"timestamp_ns": stop_ack_ns, "kind": "transition", "state": "STOP_TRANSPORT_ACK"},
        ])
    if stopped_confirmed_ns:
        events.append({"timestamp_ns": stopped_confirmed_ns, "kind": "transition",
                       "state": "MOTION_STOPPED"})
    transition_states = [e["state"] for e in events if e["kind"] == "transition"]
    checks["state_machine_complete"] = valid_state_path(
        transition_states + ["COMPLETE"], complete=True)
    result = "PASS" if all(checks.values()) and not observer_errors else "FAIL"
    if result == "PASS":
        events.append({"timestamp_ns": time.monotonic_ns(), "kind": "transition",
                       "state": "COMPLETE"})
    events.sort(key=lambda item: item["timestamp_ns"])
    args.events.parent.mkdir(parents=True, exist_ok=True)
    args.events.write_text("".join(json.dumps(row, sort_keys=True, separators=(",", ":"),
                                        allow_nan=False) + "\n" for row in events), encoding="ascii")
    summary = {
        "schema_version": "g8-r5b-moving-neural-stop-trial-v1", "result": result,
        "trial_id": trial_id, "seed": seed, "execution_target": "Thor",
        "project_commit": args.source_head, "protocol_sha256": sha(protocol_path),
        "graph_sha256": protocol["graph_sha256"],
        "graph_manifest_sha256": protocol["graph_manifest_sha256"],
        "microduck_commit": protocol["microduck_commit"],
        "microduck_rl_commit": protocol["microduck_rl_commit"],
        "walking_policy_sha256": protocol["walking_policy_sha256"],
        "walking_policy_readback_sha256": sha(args.policy_readback),
        "identity": identity, "precondition": precondition_status,
        "motion_confirmed_at_ns": precondition_status["motion_confirmed_at_ns"] if precondition_status else None,
        "motion_first_observed_at_ns": precondition_status["motion_first_observed_at_ns"] if precondition_status else None,
        "looming_phase_started_at_ns": phase_started_ns,
        "looming_first_nonzero_at_ns": first_looming_ns,
        "dn_escape_threshold_crossed_at_ns": first_escape_ns,
        "decoder_stop_created_at_ns": stop_created_ns,
        "watchdog_stop_created_at_ns": first_neural["timestamp_ns"] if first_neural else None,
        "robot_stop_rpc_call_started_ns": first_neural["robot_state"]["publish_call_started_ns"] if first_neural else None,
        "robot_stop_rpc_ack_returned_ns": stop_ack_ns,
        "robot_stop_rpc_exact_socket_write_ns": None,
        "first_stopped_state_at_ns": first_stopped_ns,
        "last_nonzero_velocity_at_ns": last_nonzero_ns,
        "stopped_confirmed_at_ns": stopped_confirmed_ns,
        "motion_stop_latency_ms": (stopped_confirmed_ns - stop_ack_ns) / 1e6
                                  if stopped_confirmed_ns and stop_ack_ns else None,
        "pre_stop_pose_speed_mps": latest_pre_stop["pose_speed_mps"] if latest_pre_stop else None,
        "pre_stop_displacement_m": pre_stop_displacement,
        "pre_stop_speed_sample_at_ns": latest_pre_stop["timestamp_ns"] if latest_pre_stop else None,
        "post_stop_confirmed_pose_speed_mps": confirmed_sample["pose_speed_mps"] if confirmed_sample else None,
        "peak_looming": looming_peak, "peak_lplc2_stimulus": lplc2_peak,
        "peak_dn_escape": escape_peak, "neural_stop_count": len(neural),
        "first_stop_source": "healthy_neural_escape" if first_stop_is_neural else
                             (first_stop["watchdog_state"] if first_stop else None),
        "safety_limit_violations": violation_count, "scheduler_exceptions": scheduler_exceptions,
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
        "timing_limits": ["precondition robot.move is a notification with no RPC ACK",
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
    ap.add_argument("--trial-index", type=int, choices=(0, 1, 2), required=True)
    ap.add_argument("--socket", required=True)
    ap.add_argument("--body-port", type=int, required=True)
    ap.add_argument("--microduck", type=Path, required=True)
    ap.add_argument("--microduck-rl", type=Path, required=True)
    ap.add_argument("--source-head", required=True)
    ap.add_argument("--policy-readback", type=Path, required=True)
    ap.add_argument("--raw", type=Path, required=True)
    ap.add_argument("--events", type=Path, required=True)
    ap.add_argument("--summary", type=Path, required=True)
    args = ap.parse_args()
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
