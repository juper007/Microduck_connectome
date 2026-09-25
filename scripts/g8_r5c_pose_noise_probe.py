"""Development-only official Thor pose noise probe; never G8-R5c final evidence.

Requires an already running official duck-sim robotd/MuJoCo and loaded walking
policy. Publishes only bounded high-level robot.move and robot.stop intents.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import socket
import statistics
import time

from microduck_connectome.g8_r5c_metrics import pose_speeds
from scripts.g8_r5c_trial import acknowledged_precondition_move
from scripts.p6_motion_fixture import JsonLines
from scripts.p6_telemetry_runtime_fixture import RobotStateSampler
from scripts.p8_looming_scenario_smoke import OfficialPoseReader


def write(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--body-port", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not socket.gethostname().startswith("jetsonthor") or platform.python_version_tuple()[:2] != ("3", "12"):
        raise RuntimeError("development probe requires official Thor Python 3.12")
    args.output.mkdir(parents=True, exist_ok=False)
    command = JsonLines(args.socket)
    command.request("hello", {"api_version": 31})
    sampler = RobotStateSampler(args.socket)
    pose_reader = OfficialPoseReader(args.body_port)
    rows = []
    stop_ack_ns = None
    try:
        for index in range(75):
            tick_ns = time.monotonic_ns()
            result, call_ns, write_ns, ack_ns = acknowledged_precondition_move(
                command, vx=.07, vy=0.0, vyaw=0.0)
            if result.get("accepted") is not True:
                raise RuntimeError("precondition robot.move rejected")
            state, received_ns = sampler.after(ack_ns)
            pose = pose_reader.read()
            sample_ns = time.monotonic_ns()
            rows.append({"timestamp_ns": sample_ns, "phase": "moving", "index": index,
                         "x_m": pose["x_m"], "y_m": pose["y_m"],
                         "heading_rad": pose["heading_rad"],
                         "applied_vx_mps": state["move"]["applied"][0],
                         "requested_vx_mps": state["move"]["requested"][0],
                         "limited_by": list(state["move"].get("limited_by", [])),
                         "robot_state_received_ns": received_ns,
                         "move_call_ns": call_ns, "move_write_completed_ns": write_ns,
                         "move_ack_ns": ack_ns})
            time.sleep(max(0, .02 - (time.monotonic_ns() - tick_ns) / 1e9))
        stop_call_ns = time.monotonic_ns()
        stop_result = command.request("robot.stop", {})
        stop_ack_ns = time.monotonic_ns()
        end_ns = stop_ack_ns + 1_100_000_000
        while time.monotonic_ns() < end_ns:
            tick_ns = time.monotonic_ns()
            state, received_ns = sampler.after(tick_ns)
            pose = pose_reader.read()
            sample_ns = time.monotonic_ns()
            rows.append({"timestamp_ns": sample_ns, "phase": "after_stop",
                         "x_m": pose["x_m"], "y_m": pose["y_m"],
                         "heading_rad": pose["heading_rad"],
                         "applied_vx_mps": state["move"]["applied"][0],
                         "requested_vx_mps": state["move"]["requested"][0],
                         "limited_by": list(state["move"].get("limited_by", [])),
                         "robot_state_received_ns": received_ns})
            time.sleep(max(0, .02 - (time.monotonic_ns() - tick_ns) / 1e9))
    finally:
        try:
            command.request("robot.stop", {})
        finally:
            pose_reader.close()
            sampler.close()
            command.close()
    raw = args.output / "pose-raw.jsonl"
    raw.write_text("".join(json.dumps(row, sort_keys=True, separators=(",", ":"),
                                  allow_nan=False) + "\n" for row in rows))
    windows = {}
    for width in (100, 200, 300, 400):
        measured = pose_speeds(rows, window_ms=width, max_window_ms=width + 40)
        after = [row for row in measured if stop_ack_ns is not None
                 and row["timestamp_ns"] >= stop_ack_ns + width * 1_000_000
                 and row["pose_speed_mps"] is not None]
        speeds = [row["pose_speed_mps"] for row in after]
        windows[str(width)] = {
            "count": len(speeds), "median_mps": statistics.median(speeds) if speeds else None,
            "maximum_mps": max(speeds) if speeds else None,
            "minimum_mps": min(speeds) if speeds else None,
            "last_mps": speeds[-1] if speeds else None,
        }
    post = [row for row in rows if row["phase"] == "after_stop"]
    axis = (math.cos(rows[0]["heading_rad"]), math.sin(rows[0]["heading_rad"]))
    origin = post[0]
    forward = [((r["x_m"] - origin["x_m"]) * axis[0]
                + (r["y_m"] - origin["y_m"]) * axis[1]) for r in post]
    report = {
        "schema_version": "g8-r5c-development-pose-noise-v1",
        "evidence_role": "development_probe_only; never final behavior evidence",
        "execution_target": "Thor official robotd and MuJoCo",
        "precondition_vx_mps": .07, "precondition_ticks": 75,
        "stop_call_ns": stop_call_ns, "stop_ack_ns": stop_ack_ns,
        "stop_result": stop_result,
        "raw": {"path": str(raw), "sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
                "bytes": raw.stat().st_size, "record_count": len(rows)},
        "pose_speed_windows_ms": windows,
        "post_stop_max_forward_displacement_m": max(forward),
        "post_stop_min_forward_displacement_m": min(forward),
        "last_applied_vx_mps": post[-1]["applied_vx_mps"],
    }
    write(args.output / "pose-noise-summary.json", report)
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
