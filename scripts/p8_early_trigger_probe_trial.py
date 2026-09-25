"""Official Thor development probe for pre-boundary looming neural stop."""
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
import tomllib

from microduck_connectome.g8_r5d_metrics import (
    bounded_neural_lineage, causal_timeline_ok, deadman_limiter_seen_before_stopped,
    deadman_timing, first_sustained, is_healthy_neural_stop,
    material_pre_stop_applied, neural_input_ended_by_ack, pose_speeds,
    safe_observation_horizon, stop_refresh_cadence, valid_state_path,
)
from microduck_connectome.g8_r5d_fixture import (
    ProductionStopRefreshScheduler, IsolatedStopPublisher, SUPPRESSED_NEUTRAL,
)
from microduck_connectome.p8_probe_motion_arbiter import ProbeMotionArbiter, MotionLatched
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


class LoomingChain(FullChain):
    def __init__(self, root, graph, scenario, pose_reader, pose_lock, elapsed_start_s, arbiter):
        super().__init__(root, graph)
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
        frame = self.pipeline.process(
            pixels, camera_timestamp_ns=now_ns, camera_frame_id=self.frame_id,
            tof_left_mm=tof, tof_center_mm=tof, tof_right_mm=tof,
            tof_timestamp_ns=now_ns, tof_frame_id=self.frame_id, now_ns=now_ns,
        )
        self.visual_frames.append({"frame_id": self.frame_id, "timestamp_ns": now_ns,
                                   "pixel_area": sum(pixel != (0, 0, 0)
                                                     for row in pixels for pixel in row),
                                   "pixels_sha256": pixels_sha256(pixels),
                                   "perception_target_area": frame["target_area"],
                                   "perception_looming": frame["looming"]})
        return frame

    def neural(self, frame, now_ns):
        call_started_ns = time.monotonic_ns()
        update = self.arbiter.neural_step(lambda: super(LoomingChain, self).neural(frame, now_ns))
        call_returned_ns = time.monotonic_ns()
        if update is None or update.trace is None:
            self.neural_ledger.append({"neural_call_timestamp_ns": now_ns,
                                       "neural_call_started_ns": call_started_ns,
                                       "neural_call_returned_ns": call_returned_ns,
                                       "result_none": True, "input_none": frame is None})
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
            "looming": perception["looming"],
            "proximity_left": perception["proximity_left"],
            "proximity_center": perception["proximity_center"],
            "proximity_right": perception["proximity_right"],
            "stimulus_channels": copy.deepcopy(stimulus),
            "external_input_count": trace["male_cns"]["external_input_count"],
        })
        return update


def verify_protocol(root, protocol_path, protocol, args):
    if socket.gethostname().startswith("jetsonthor") is False or platform.python_version_tuple()[:2] != ("3", "12"):
        raise RuntimeError("official Thor Python 3.12 required")
    if protocol["schema_version"] not in ("p8-v2-early-trigger-development-v1",
                                          "p8-v2-early-trigger-development-v2"):
        raise ValueError("protocol version mismatch")
    if not 0 < protocol["maximum_stop_refresh_gap_ms"] < protocol["deadman_timeout_ms"]:
        raise ValueError("stop refresh gap must be below frozen deadman timeout")
    if git_head(root) != args.source_head:
        raise RuntimeError("source head mismatch")
    if not args.development_probe and subprocess.check_output(
            ["git", "-C", str(root), "status", "--porcelain"], text=True).strip():
        raise RuntimeError("final trial requires a clean source checkout")
    if not args.development_probe:
        committed = subprocess.check_output(["git", "-C", str(root), "show",
                                             f"HEAD:config/p8_early_trigger_probe_v{args.protocol_version}.json"])
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
    params_source = (args.microduck / "robotd-params/src/lib.rs").read_text()
    if f"deadman_ms: {protocol['deadman_timeout_ms']}" not in params_source:
        raise RuntimeError("pinned official deadman default differs from frozen protocol")
    effective = tomllib.loads((Path(args.socket).parent / "robotd.toml").read_text())
    active_deadman = effective.get("safety", {}).get("deadman_ms", protocol["deadman_timeout_ms"])
    if active_deadman != protocol["deadman_timeout_ms"]:
        raise RuntimeError("active robotd deadman differs from frozen protocol")
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
    protocol_path = root / f"config/p8_early_trigger_probe_v{args.protocol_version}.json"
    protocol = json.loads(protocol_path.read_text())
    manifest, graph_path, scenario = verify_protocol(root, protocol_path, protocol, args)
    seed = protocol["scenario_seeds"][args.trial_index]
    trial_id = f"p8-early-probe-{args.trial_index + 1:02d}-{seed}"
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
    arbiter = ProbeMotionArbiter()
    arm_elapsed_s = protocol["arm_elapsed_s"][args.trial_index]
    chain = LoomingChain(root, graph, scenario, pose_reader, pose_lock,
                         arm_elapsed_s, arbiter)
    watchdog = ControllerWatchdog(root / "config/watchdog_v1.json")
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
                if trace["perception_frame"]["looming"] > 0 and "NEURAL_LOOMING" not in state_path:
                    transition("NEURAL_LOOMING", trace["perception_frame"]["timestamp_ns"])
                if transport == SUPPRESSED_NEUTRAL:
                    last_motion.update({"state": state, "pose": pose,
                                        "state_received_ns": received_ns,
                                        "pose_sample_ns": pose_ns})
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
                    first_stop.update({"record": record, "state_before": last_motion.get("state"),
                                       "state_before_received_ns": last_motion.get("state_received_ns"),
                                       "pose_before": last_motion.get("pose")})
                    if is_healthy_neural_stop(record, threshold=protocol["escape_threshold"]):
                        transition("NEURAL_STOP_DETECTED", record["pre_safety_intent"]["timestamp_ns"])
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
        result = arbiter.publish(output, isolated_publisher.send)
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

    class ProbeScheduler(ProductionStopRefreshScheduler):
        def _fail(self, worker, error):
            arbiter.latch(f"scheduler_{worker}_fault")
            super()._fail(worker, error)

    scheduler = ProbeScheduler(
        config=root / "config/scheduler_v1.json", watchdog=watchdog,
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
            observation_ms=protocol["max_neural_observation_duration_ms"],
            margin_ms=protocol["sphere_entry_safety_margin_ms"])
        if not sphere_bound["safe"]:
            raise RuntimeError("frozen neural observation horizon can enter virtual sphere")
        phase_started_ns = time.monotonic_ns()
        transition("NEURAL_OBSERVATION_ARMED", phase_started_ns)
        first_frame = chain.perception(phase_started_ns)
        first_update = chain.neural(first_frame, phase_started_ns)
        if not watchdog.observe_neural(first_update.readout) or not watchdog.observe_behavior(first_update.behavior_intent):
            raise RuntimeError("cannot prime healthy watchdog at neural phase handoff")

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
        remaining_neural_s = (protocol["max_neural_observation_duration_ms"]
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
        if first_record is None or not is_healthy_neural_stop(
                first_record, threshold=protocol["escape_threshold"]):
            raise RuntimeError("first robot-facing stop was not healthy neural escape")
        lineage_now = bounded_neural_lineage(
            chain.neural_ledger, first_record,
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
            if row["timestamp_ns"] < first_record["pre_safety_intent"]["timestamp_ns"]
            and row["pose_speed_mps"] is not None]
        if (not before_decoder
                or first_record["pre_safety_intent"]["timestamp_ns"]
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
    neural = [record for record in records if is_healthy_neural_stop(
        record, threshold=protocol["escape_threshold"])]
    first_stop_state_before = first_stop.get("state_before")
    first_stop_state_before_ns = first_stop.get("state_before_received_ns")
    first_stop = next((record for record in records if record["robot_facing_stop"]), None)
    first_actual_stop_event = next((e for e in events if e["kind"] == "control_publish"
                                    and e["robot_facing_stop"]
                                    and e["transport_action"] == "robot_stop_refreshed"), None)
    first_neural = neural[0] if neural else None
    first_stop_is_neural = bool(first_neural and first_stop and first_actual_stop_event
                                and first_stop["sequence"] == first_neural["sequence"]
                                and first_actual_stop_event["sequence"] == first_neural["sequence"])
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
    first_escape_ns = next((r["dn_activity"]["timestamp_ns"] for r in records
                            if r["dn_activity"]["escape"] >= protocol["escape_threshold"]), None)
    scheduler_exceptions = scheduler_result["scheduler_exceptions"] if scheduler_result else None
    precondition_rows = [e for e in events if e["kind"] == "precondition_motion"]
    precondition_call_gaps_ms = [
        (b["request_call_started_at_ns"] - a["request_call_started_at_ns"]) / 1e6
        for a, b in zip(precondition_rows, precondition_rows[1:])]
    max_precondition_call_gap_ms = max(precondition_call_gaps_ms, default=None)
    precondition_deadman_limited = any(
        "deadman" in str(reason).lower()
        for row in precondition_rows for reason in row["robot_state"]["limited_by"])
    deadman = deadman_timing(
        last_motion.get("request_call_ns"), last_motion.get("ack_ns"), stop_ack_ns,
        timeout_ms=protocol["deadman_timeout_ms"],
        minimum_margin_ms=protocol["minimum_deadman_margin_ms"])
    lineage = (bounded_neural_lineage(
        chain.neural_ledger, first_stop,
        max_age_ms=protocol["maximum_visual_lineage_age_ms"],
        max_runtime_step_gap=protocol["maximum_visual_lineage_runtime_step_gap"])
        if first_stop is not None else {"valid": False, "reason": "missing_first_stop"})
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
    visual_frame_gaps_ms = [
        (b["timestamp_ns"] - a["timestamp_ns"]) / 1e6
        for a, b in zip(chain.visual_frames, chain.visual_frames[1:])]
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
        "healthy_neural_stop_first": first_stop_is_neural,
        "bounded_temporal_neural_lineage": first_stop_is_neural and lineage["valid"],
        "robot_stop_ack": stop_ack_ns is not None,
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
    result = "PASS" if all(checks.values()) and not observer_errors else "FAIL"
    events.sort(key=lambda item: item["timestamp_ns"])
    args.events.parent.mkdir(parents=True, exist_ok=True)
    args.events.write_text("".join(json.dumps(row, sort_keys=True, separators=(",", ":"),
                                        allow_nan=False) + "\n" for row in events), encoding="ascii")
    summary = {
        "schema_version": "p8-v2-early-trigger-development-trial-v1", "result": result,
        "evidence_role": "development_probe" if args.development_probe else "final_trial",
        "source_checkout_uncommitted": bool(args.development_probe),
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
        "motion_confirmed_at_ns": precondition_status["motion_confirmed_at_ns"] if precondition_status else None,
        "motion_first_observed_at_ns": precondition_status["motion_first_observed_at_ns"] if precondition_status else None,
        "last_precondition_move_request_call_started_at_ns": last_motion.get("request_call_ns"),
        "last_precondition_move_ack_at_ns": last_motion.get("ack_ns"),
        "last_precondition_move_result": last_motion.get("result"),
        "motion_arbiter_latch_reason": arbiter.latch_reason,
        "motion_arbiter_latch_at_ns": arbiter.latch_at_ns,
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
    ap.add_argument("--trial-index", type=int, choices=(0, 1, 2), required=True)
    ap.add_argument("--protocol-version", type=int, choices=(1, 2, 3), default=1)
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
    ap.add_argument("--development-probe", action="store_true",
                    help="uncommitted fixture/protocol probe; never final evidence")
    args = ap.parse_args()
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
