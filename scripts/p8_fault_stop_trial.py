"""Development-only moving-body fault-stop probe on official Thor robotd/MuJoCo."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import socket
import threading
import time

from microduck_connectome.fault_stop import FaultAwareInputs, FaultStopLatch, FaultStopRefreshScheduler
from microduck_connectome.g8_r5d_fixture import IsolatedStopPublisher, SUPPRESSED_NEUTRAL
from microduck_connectome.g8_r5d_metrics import first_sustained, pose_speeds
from microduck_connectome.graph import ConnectomeGraph
from microduck_connectome.motion_adapter import RobotMotionAdapter
from microduck_connectome.robotd_client import RobotdClient
from microduck_connectome.watchdog import ControllerWatchdog
from scripts.g8_r5d_trial import acknowledged_precondition_move, robot_state_record, sha, verify_protocol
from scripts.p6_motion_fixture import JsonLines
from scripts.p6_telemetry_runtime_fixture import FullChain, RobotStateSampler, git_head
from scripts.p8_looming_scenario_smoke import OfficialPoseReader


FAULTS = (
    "camera_loss", "tof_loss", "camera_and_tof_loss", "camera_stale",
    "malformed_perception", "nan_feature", "inf_feature",
    "neural_freeze", "unexpected_worker_exception",
)


class FaultChain(FullChain):
    def __init__(self, root, graph, fault):
        super().__init__(root, graph)
        self.fault = fault
        self.fault_armed = False
        self.fault_injected_ns = None
        self.last_compositor_reasons = ()
        self.neural_calls = 0
        self.frames = []
        self.neural_rows = []

    def perception(self, now_ns):
        self.frame_id += 1
        armed = self.frame_id >= 3
        self.fault_armed = armed
        if armed and self.fault_injected_ns is None:
            self.fault_injected_ns = now_ns
        if armed and self.fault == "unexpected_worker_exception":
            raise RuntimeError("development injected unexpected perception worker exception")
        camera_valid = not (armed and self.fault in ("camera_loss", "camera_and_tof_loss"))
        tof_valid = not (armed and self.fault in ("tof_loss", "camera_and_tof_loss"))
        camera_ns = now_ns - 100_000_001 if armed and self.fault == "camera_stale" else now_ns
        # One small static target keeps the camera/looming join valid without
        # presenting an approaching obstacle or inducing a neural escape.
        pixels = (tuple((255, 0, 0) if x == 50 else (0, 0, 0)
                        for x in range(101)),)
        frame = self.pipeline.process(
            pixels,
            camera_timestamp_ns=camera_ns, camera_frame_id=self.frame_id,
            tof_left_mm=2000, tof_center_mm=2000, tof_right_mm=2000,
            tof_timestamp_ns=now_ns, tof_frame_id=self.frame_id,
            now_ns=now_ns, camera_source_valid=camera_valid,
            tof_source_valid=tof_valid,
        )
        self.last_compositor_reasons = self.pipeline.compositor.last_reasons
        if armed and self.fault == "malformed_perception":
            frame = {**frame, "target_x": 2.0}
        if armed and self.fault == "nan_feature":
            frame = {**frame, "looming": float("nan")}
        if armed and self.fault == "inf_feature":
            frame = {**frame, "looming": float("inf")}
        self.frames.append({"timestamp_ns": now_ns, "frame_id": self.frame_id,
                            "source_valid_camera": camera_valid,
                            "source_valid_tof": tof_valid,
                            "compositor_reasons": list(self.last_compositor_reasons),
                            "frame_valid": frame["valid"]})
        return frame

    def neural(self, frame, now_ns):
        self.neural_calls += 1
        if self.fault_armed and self.fault == "neural_freeze":
            self.neural_rows.append({"timestamp_ns": now_ns, "kind": "injected_neural_dropout"})
            return None
        update = super().neural(frame, now_ns)
        self.neural_rows.append({"timestamp_ns": now_ns, "kind": "neural_update",
                                 "readout": dict(update.readout) if update else None,
                                 "trace": dict(update.trace) if update and update.trace else None})
        return update

    def classify(self, frame):
        if not self.fault_armed:
            return None
        if self.fault in ("camera_loss", "tof_loss", "camera_and_tof_loss", "camera_stale"):
            return self.fault
        return None


def write_jsonl(path, rows):
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in sorted(rows, key=lambda item: item["timestamp_ns"]):
            stream.write(json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n")
    return {"path": str(path), "bytes": path.stat().st_size,
            "record_count": len(rows), "sha256": sha(path)}


def run(args):
    if not socket.gethostname().startswith("jetsonthor") or platform.python_version_tuple()[:2] != ("3", "12"):
        raise RuntimeError("official Thor Python 3.12 required")
    root = args.root.resolve()
    if git_head(root) != args.source_head:
        raise RuntimeError("source identity mismatch")
    protocol = json.loads((root / "config/g8_r5d_stop_refresh_v1.json").read_text())
    check_args = argparse.Namespace(source_head=args.source_head, development_probe=True,
                                    microduck=args.microduck, microduck_rl=args.microduck_rl,
                                    socket=args.socket, policy_readback=args.policy_readback)
    _, graph_path, _ = verify_protocol(root, root / "config/g8_r5d_stop_refresh_v1.json",
                                       protocol, check_args)
    graph = ConnectomeGraph.from_cache(graph_path.parent, protocol["graph_sha256"])
    chain = FaultChain(root, graph, args.fault)
    pre = protocol["precondition"]
    metric = protocol["motion_metric"]
    stopped = protocol["stopped_metric"]
    robot = RobotdClient(args.socket, timeout_s=2.0)
    precondition = JsonLines(args.socket)
    sampler = RobotStateSampler(args.socket)
    pose_reader = OfficialPoseReader(args.body_port)
    latch = FaultStopLatch()
    events = []
    pose_rows = []
    stop_acks = []
    scheduler_errors = []
    scheduler = None
    scheduler_thread = None
    result = "FAIL"
    failure = None
    last_move_ack_ns = None
    stop_confirmed_ns = None
    try:
        robot.connect()
        robot.enable(True)
        precondition.request("hello", {"api_version": 31})
        adapter = RobotMotionAdapter(robot, root / "config/motion_adapter_v1.json")
        isolated = IsolatedStopPublisher(adapter)
        for index in range(round(pre["duration_s"] * 1000 / pre["command_period_ms"])):
            tick_ns = time.monotonic_ns()
            _, call_ns, write_ns, ack_ns = acknowledged_precondition_move(
                precondition, vx=pre["vx_mps"], vy=0.0, vyaw=0.0)
            state, state_ns = sampler.after(ack_ns)
            pose = pose_reader.read()
            pose_ns = time.monotonic_ns()
            last_move_ack_ns = ack_ns
            pose_rows.append({"timestamp_ns": pose_ns, "x_m": pose["x_m"], "y_m": pose["y_m"]})
            events.append({"kind": "precondition_move", "timestamp_ns": pose_ns, "index": index,
                           "request_ns": call_ns, "write_ns": write_ns, "ack_ns": ack_ns,
                           "robot_state": robot_state_record(state, state_ns, pose, pose_ns)})
            time.sleep(max(0, pre["command_period_ms"] / 1000 -
                           (time.monotonic_ns() - tick_ns) / 1e9))
        speeds = pose_speeds(pose_rows, window_ms=metric["speed_window_ms"],
                             max_window_ms=metric["speed_window_max_ms"])
        moving_ns = first_sustained(speeds, threshold_mps=metric["moving_threshold_mps"],
                                    duration_ms=metric["moving_confirmation_ms"], at_or_above=True)
        if moving_ns is None or (speeds[-1]["pose_speed_mps"] or 0) < metric["moving_threshold_mps"]:
            raise RuntimeError("moving-body precondition not established")
        state_before, state_before_ns = sampler.after(last_move_ack_ns)
        if state_before["move"]["applied"][0] < protocol["minimum_fresh_pre_stop_applied_vx_mps"]:
            raise RuntimeError("fresh applied vx below frozen moving threshold")
        phase_ns = time.monotonic_ns()
        first_frame = chain.perception(phase_ns)
        first_update = chain.neural(first_frame, phase_ns)
        watchdog = ControllerWatchdog(root / "config/watchdog_v1.json")
        if not watchdog.observe_neural(first_update.readout) or not watchdog.observe_behavior(first_update.behavior_intent):
            raise RuntimeError("healthy watchdog priming failed")
        inputs = FaultAwareInputs(
            fault_latch=latch, started_ns=phase_ns,
            perception_step=chain.perception, neural_step=chain.neural,
            source_fault_reason=chain.classify,
        )

        def publish(output):
            call_ns = time.monotonic_ns()
            transport = isolated.send(output)
            ack_ns = time.monotonic_ns()
            if transport == "robot_stop_refreshed":
                stop_acks.append({"request_ns": call_ns, "ack_ns": ack_ns,
                                  "sequence": output["intent"]["sequence"],
                                  "watchdog_state": output["watchdog_state"],
                                  "stale_reason": output["stale_reason"]})
            events.append({"kind": "watchdog_publish", "timestamp_ns": ack_ns,
                           "request_ns": call_ns, "transport": transport,
                           "intent": dict(output["intent"]),
                           "watchdog_state": output["watchdog_state"],
                           "stale_reason": output["stale_reason"]})
            return transport

        scheduler = FaultStopRefreshScheduler(
            fault_latch=latch, config=root / "config/scheduler_v1.json",
            watchdog=watchdog, perception_step=inputs.perception,
            neural_step=inputs.neural, publisher=publish,
        )

        def run_scheduler():
            try:
                scheduler.run(1.4)
            except BaseException as error:
                scheduler_errors.append(f"{type(error).__name__}: {error}")

        scheduler_thread = threading.Thread(target=run_scheduler, name="p8-fault-stop-scheduler")
        scheduler_thread.start()
        deadline_ns = phase_ns + 1_400_000_000
        while time.monotonic_ns() < deadline_ns:
            sample_start_ns = time.monotonic_ns()
            state, state_ns = sampler.after(sample_start_ns)
            pose = pose_reader.read()
            pose_ns = time.monotonic_ns()
            pose_rows.append({"timestamp_ns": pose_ns, "x_m": pose["x_m"], "y_m": pose["y_m"]})
            events.append({"kind": "robot_observation", "timestamp_ns": pose_ns,
                           "robot_state": robot_state_record(state, state_ns, pose, pose_ns)})
            if stop_acks:
                speeds = pose_speeds(pose_rows, window_ms=metric["speed_window_ms"],
                                     max_window_ms=metric["speed_window_max_ms"])
                stop_confirmed_ns = first_sustained(
                    speeds, threshold_mps=stopped["stopped_threshold_mps"],
                    duration_ms=stopped["stop_confirmation_ms"], at_or_above=False,
                    after_ns=stop_acks[0]["ack_ns"])
                if stop_confirmed_ns is not None:
                    scheduler.request_complete()
                    break
            time.sleep(0.02)
        if stop_confirmed_ns is None:
            raise RuntimeError("pose-derived stop not confirmed before development deadline")
        scheduler_thread.join(timeout=3)
        if scheduler_thread.is_alive():
            raise RuntimeError("scheduler did not finish")
        if not stop_acks:
            raise RuntimeError("no robot.stop ACK")
        fault = latch.snapshot()
        if fault is None:
            raise RuntimeError("no fault latch")
        if stop_acks[0]["stale_reason"] != "fault_" + fault.reason:
            raise RuntimeError("first robot.stop was not attributed to the latched fault")
        if args.fault == "unexpected_worker_exception":
            if not scheduler_errors or scheduler._metrics.scheduler_exceptions != 1:
                raise RuntimeError("unexpected worker error was hidden")
        elif scheduler_errors or scheduler._metrics.scheduler_exceptions:
            raise RuntimeError("planned fault created scheduler exception")
        gaps_ms = [(b["ack_ns"] - a["ack_ns"]) / 1e6 for a, b in zip(stop_acks, stop_acks[1:])]
        if len(stop_acks) < 2 or max(gaps_ms) > 100:
            raise RuntimeError("stop ACK refresh cadence failed")
        if last_move_ack_ns is None or stop_acks[0]["ack_ns"] - last_move_ack_ns >= 400_000_000:
            raise RuntimeError("deadman attribution confound")
        post_applied = [row["robot_state"]["applied_velocity"][0] for row in events
                        if row["kind"] == "robot_observation"
                        and row["timestamp_ns"] >= stop_acks[0]["ack_ns"]]
        if not post_applied or min(abs(value) for value in post_applied) > protocol["applied_stop_threshold_mps"]:
            raise RuntimeError("applied vx decline/near-zero was not observed")
        if any("deadman" in str(reason).lower() for row in events
               if row["kind"] == "robot_observation"
               for reason in row["robot_state"]["limited_by"]
               if row["timestamp_ns"] <= stop_confirmed_ns):
            raise RuntimeError("deadman limiter before confirmed stop")
        if isolated.post_stop_move_count or isolated.nonzero_count:
            raise RuntimeError("unexpected post-stop or nonzero neural move")
        result = ("DEVELOPMENT_PROBE_EXPECTED_EXCEPTION_SAFE"
                  if args.fault == "unexpected_worker_exception"
                  else "DEVELOPMENT_PROBE_PASS")
    except BaseException as error:
        failure = f"{type(error).__name__}: {error}"
    finally:
        if scheduler is not None and scheduler_thread is not None and scheduler_thread.is_alive():
            scheduler._stop.set()
            scheduler._fixture_wake.set()
            scheduler_thread.join(timeout=3)
        try:
            cleanup = precondition.request("robot.stop", {})
            events.append({"kind": "cleanup_stop_not_credited", "timestamp_ns": time.monotonic_ns(),
                           "result": cleanup})
        except BaseException as error:
            events.append({"kind": "cleanup_error", "timestamp_ns": time.monotonic_ns(),
                           "error": f"{type(error).__name__}: {error}"})
        robot.close()
        precondition.close()
        sampler.close()
        pose_reader.close()
    args.output.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "events": write_jsonl(args.output / "events.jsonl", events),
        "frames": write_jsonl(args.output / "frames.jsonl", chain.frames),
        "neural": write_jsonl(args.output / "neural.jsonl", chain.neural_rows),
    }
    fault = latch.snapshot()
    summary = {
        "schema_version": "p8-v2-fault-stop-development-v1",
        "evidence_role": "development_only_not_final_p8_04",
        "result": result, "failure": failure, "fault_mode": args.fault,
        "source_head": args.source_head, "graph_sha256": protocol["graph_sha256"],
        "microduck_commit": git_head(args.microduck),
        "microduck_rl_commit": git_head(args.microduck_rl),
        "fault_record": vars(fault) if fault else None,
        "fault_injected_ns": chain.fault_injected_ns,
        "last_motion_ack_ns": last_move_ack_ns,
        "first_stop_ack_ns": stop_acks[0]["ack_ns"] if stop_acks else None,
        "stop_ack_count": len(stop_acks),
        "stop_ack_gap_max_ms": max(((b["ack_ns"] - a["ack_ns"]) / 1e6
                                    for a, b in zip(stop_acks, stop_acks[1:])), default=None),
        "fault_to_first_stop_request_ms": (
            (stop_acks[0]["request_ns"] - fault.detected_ns) / 1e6
            if fault and stop_acks else None),
        "fault_to_first_stop_ack_ms": (
            (stop_acks[0]["ack_ns"] - fault.detected_ns) / 1e6
            if fault and stop_acks else None),
        "first_stop_ack_to_pose_stop_ms": (
            (stop_confirmed_ns - stop_acks[0]["ack_ns"]) / 1e6
            if stop_confirmed_ns and stop_acks else None),
        "stopped_confirmed_ns": stop_confirmed_ns,
        "scheduler_errors": scheduler_errors,
        "scheduler_exceptions": scheduler._metrics.scheduler_exceptions if scheduler else None,
        "artifacts": artifacts,
    }
    summary_path = args.output / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--body-port", type=int, required=True)
    parser.add_argument("--microduck", type=Path, required=True)
    parser.add_argument("--microduck-rl", type=Path, required=True)
    parser.add_argument("--source-head", required=True)
    parser.add_argument("--policy-readback", type=Path, required=True)
    parser.add_argument("--fault", choices=FAULTS, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = run(args)
    print(json.dumps({"result": summary["result"], "failure": summary["failure"],
                      "fault_mode": args.fault, "summary": str(args.output / "summary.json")}))
    if summary["result"] not in ("DEVELOPMENT_PROBE_PASS", "DEVELOPMENT_PROBE_EXPECTED_EXCEPTION_SAFE"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
