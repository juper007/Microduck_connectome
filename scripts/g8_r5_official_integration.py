"""One frozen-scenario graph-v2 neural-stop integration check on official Thor.

This is a recertification smoke, not a P8 final trial. A failed neural stop is
reported as FAIL; the scheduler's shutdown stop never counts as neural stop.
"""
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
from microduck_connectome.looming_scenario import load_config, make_trial, render_pixels
from microduck_connectome.motion_adapter import RobotMotionAdapter
from microduck_connectome.robotd_client import RobotdClient
from microduck_connectome.scheduler import ClosedLoopScheduler
from microduck_connectome.telemetry import EndToEndTelemetry, build_run_identity
from microduck_connectome.watchdog import ControllerWatchdog
from scripts.p6_telemetry_runtime_fixture import (
    FullChain, RobotStateSampler, git_head,
)
from scripts.p8_looming_scenario_smoke import OfficialPoseReader


class LoomingChain(FullChain):
    def __init__(self, root, graph, scenario, trial, pose_reader, pose_lock):
        super().__init__(root, graph)
        self.scenario_config = scenario
        self.trial = trial
        self.pose_reader = pose_reader
        self.pose_lock = pose_lock
        self.started_ns = None
        self.scenario = "stop"

    def perception(self, now_ns):
        if self.started_ns is None:
            self.started_ns = now_ns
        self.frame_id += 1
        elapsed = (now_ns - self.started_ns) / 1e9
        with self.pose_lock:
            pose = self.pose_reader.read()
        pixels = render_pixels(self.scenario_config, self.trial, pose=pose, elapsed_s=elapsed)
        tof = self.scenario_config["tof_mm"]
        return self.pipeline.process(
            pixels, camera_timestamp_ns=now_ns, camera_frame_id=self.frame_id,
            tof_left_mm=tof, tof_center_mm=tof, tof_right_mm=tof,
            tof_timestamp_ns=now_ns, tof_frame_id=self.frame_id, now_ns=now_ns,
        )


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--socket", required=True)
    ap.add_argument("--body-port", type=int, required=True)
    ap.add_argument("--microduck", type=Path, required=True)
    ap.add_argument("--microduck-rl", type=Path, required=True)
    ap.add_argument("--source-head", required=True)
    ap.add_argument("--raw", type=Path, required=True)
    ap.add_argument("--summary", type=Path, required=True)
    a = ap.parse_args()
    if not socket.gethostname().startswith("jetsonthor") or platform.python_version_tuple()[:2] != ("3", "12"):
        raise RuntimeError("official Thor Python 3.12 required")
    root = a.root.resolve()
    if git_head(root) != a.source_head:
        raise RuntimeError("source head mismatch")
    manifest = json.loads((root / "data/manifests/controller-graph-v2.json").read_text())
    graph_path = Path(manifest["thor_artifact"])
    if sha(graph_path) != manifest["graph_sha256"]:
        raise RuntimeError("graph v2 hash mismatch")
    graph = ConnectomeGraph.from_cache(graph_path.parent, manifest["graph_sha256"])
    scenario_path = root / "config/looming_scenario_v1.json"
    scenario = load_config(scenario_path)
    identity = build_run_identity(
        root, run_id="g8-r5-official-integration", project_commit=a.source_head,
        microduck_commit=git_head(a.microduck), microduck_rl_commit=git_head(a.microduck_rl),
        graph_identity=graph.root_key,
    )
    robot = RobotdClient(a.socket, timeout_s=2.0)
    robot.connect()
    robot.enable(True)
    adapter = RobotMotionAdapter(robot, root / "config/motion_adapter_v1.json")
    sampler = RobotStateSampler(a.socket)
    pose_reader = OfficialPoseReader(a.body_port)
    pose_lock = threading.Lock()
    with pose_lock:
        initial_pose = pose_reader.read()
    trial = make_trial(scenario, trial_id="g8-r5-approach-80101", seed=80101,
                       motion="approaching", initial_pose=initial_pose)
    chain = LoomingChain(root, graph, scenario, trial, pose_reader, pose_lock)
    telemetry = EndToEndTelemetry(root / "config/telemetry_v1.json", identity)
    pending = queue.Queue(maxsize=512)
    errors = []

    def worker():
        while True:
            item = pending.get()
            try:
                if item is None:
                    return
                update, output, result = item
                if update is None or update.trace is None:
                    continue
                command_ns = output["intent"]["timestamp_ns"]
                state, received_ns = sampler.after(command_ns)
                with pose_lock:
                    pose = pose_reader.read()
                move = state["move"]
                applied = list(move["applied"])
                odom = state.get("odom") or {}
                robot_state = {
                    "sample_timestamp_ns": received_ns,
                    "robot_t_ns": state.get("t_ns"),
                    "policy": state["policy"],
                    "requested_velocity": list(move["requested"]),
                    "applied_velocity": applied,
                    "velocity": [odom.get("vx", applied[0]), odom.get("vy", applied[1]),
                                 odom.get("vyaw", applied[2])],
                    "heading_rad": pose["heading_rad"],
                    "trunk_x_m": pose["x_m"], "trunk_y_m": pose["y_m"],
                    "trunk_z": pose["trunk_z_m"],
                    "limited_by": list(move.get("limited_by", [])),
                }
                trace = copy.deepcopy(update.trace)
                trace["male_cns"].pop("scenario_fixture", None)
                telemetry.append(
                    trial_id=trial.trial_id, scenario="stop", timestamp_ns=command_ns,
                    sequence=output["intent"]["sequence"], trace=trace,
                    watchdog_output=output, robotd_transport_result=result,
                    robotd_connected=robot.status.connected,
                    robot_state=robot_state,
                )
            except BaseException as error:
                errors.append(repr(error))
            finally:
                pending.task_done()

    observer = threading.Thread(target=worker, name="g8-r5-observer")
    observer.start()

    def observe(update, output, result):
        if errors:
            raise RuntimeError(errors[0])
        pending.put_nowait((update, output, result))

    scheduler = ClosedLoopScheduler(
        config=root / "config/scheduler_v1.json",
        watchdog=ControllerWatchdog(root / "config/watchdog_v1.json"),
        perception_step=chain.perception, neural_step=chain.neural,
        publisher=adapter.send, control_observer=observe,
    )
    health_before = robot.health()
    try:
        scheduler_result = scheduler.run(scenario["trial_duration_s"])
        pending.join()
        health_after = robot.health()
        a.raw.parent.mkdir(parents=True, exist_ok=True)
        artifact = telemetry.write(a.raw)
    finally:
        pending.put(None)
        pending.join()
        observer.join(timeout=5)
        pose_reader.close()
        sampler.close()
        robot.close()
    records = telemetry.records()
    neural = [r for r in records if r["male_cns"]["healthy"]
              and r["dn_activity"]["escape"] >= 0.5
              and r["pre_safety_intent"]["stop"]
              and r["watchdog_state"] == "healthy"
              and r["robot_facing_command_type"] == "robot.stop"]
    bounded = all(math.isfinite(r["robot_facing_vx"]) and math.isfinite(r["robot_facing_vyaw"])
                  and abs(r["robot_facing_vx"]) <= 0.08 and r["robot_facing_vy"] == 0
                  and abs(r["robot_facing_vyaw"]) <= 0.5 for r in records)
    pre_stop = [r for r in records if neural and r["timestamp_ns"] < neural[0]["timestamp_ns"]]
    post_stop = [r for r in records if neural and r["timestamp_ns"] >= neural[0]["timestamp_ns"]]
    motion_before_stop = any(abs(v) > 0.02 for row in pre_stop
                             for v in row["robot_state"]["velocity"])
    motion_stopped = bool(post_stop and all(abs(v) <= 0.02 for row in post_stop[-5:]
                                           for v in row["robot_state"]["velocity"]))
    result = "PASS" if (records and neural and bounded and motion_before_stop and motion_stopped and not errors
                        and health_before["healthy"] and health_after["healthy"]
                        and scheduler_result["scheduler_exceptions"] == 0) else "FAIL"
    report = {
        "schema_version": "g8-r5-official-integration-v1", "result": result,
        "scope": "one graph-v2 official Thor virtual-visual looming integration smoke; not P8 final batch",
        "source_head": a.source_head, "execution_target": "Thor", "graph_sha256": manifest["graph_sha256"],
        "scenario_sha256": sha(scenario_path), "seed": 80101,
        "identities": identity, "record_count": len(records),
        "neural_stop_count": len(neural), "first_neural_stop_sequence": neural[0]["sequence"] if neural else None,
        "robot_stop_count": sum(r["robot_facing_command_type"] == "robot.stop" for r in records),
        "max_looming": max((r["perception"]["looming"] for r in records), default=0),
        "max_escape": max((r["dn_activity"]["escape"] for r in records), default=0),
        "motion_before_neural_stop": motion_before_stop,
        "motion_stopped_after_neural_stop": motion_stopped,
        "command_bounds_pass": bounded, "observer_errors": errors,
        "scheduler": scheduler_result, "robotd_healthy_before": health_before["healthy"],
        "robotd_healthy_after": health_after["healthy"],
        "raw_artifact": str(a.raw), "raw_sha256": artifact["sha256"],
        "raw_record_count": artifact["record_count"],
    }
    a.summary.parent.mkdir(parents=True, exist_ok=True)
    a.summary.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({k: report[k] for k in ("result", "record_count", "neural_stop_count", "robot_stop_count", "max_looming", "max_escape", "motion_stopped_after_neural_stop")}, sort_keys=True))
    if result != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
