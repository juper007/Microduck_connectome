"""P8-01 read-only official robotd/MuJoCo visual-scenario smoke."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import socket
import time

from microduck_connectome.looming_scenario import (
    evaluator_truth, load_config, make_trial, pixels_sha256, render_pixels,
)
from microduck_connectome.perception_compositor import PerceptionPipeline
from microduck_connectome.robotd_client import RobotdClient
from scripts.p6_telemetry_runtime_fixture import git_head, quaternion_yaw


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class OfficialPoseReader:
    def __init__(self, port):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=2)
        self.stream = self.sock.makefile("rwb")
        self.stream.write(b'{"op":"hello","protocol":1,"joints":15}\n')
        self.stream.flush()
        if json.loads(self.stream.readline()) != {"protocol": 1}:
            raise RuntimeError("official body protocol mismatch")

    def read(self):
        self.stream.write(b'{"op":"read"}\n')
        self.stream.flush()
        packet = json.loads(self.stream.readline())
        trunk = packet.get("trunk")
        quat = packet.get("imu", {}).get("quat")
        if not isinstance(trunk, list) or len(trunk) != 3 or not isinstance(quat, list) or len(quat) != 4:
            raise RuntimeError("official trunk x/y/heading unavailable")
        pose = {"x_m": trunk[0], "y_m": trunk[1],
                "heading_rad": quaternion_yaw(quat), "trunk_z_m": trunk[2]}
        from microduck_connectome.looming_scenario import validate_pose
        return validate_pose(pose)

    def close(self):
        self.stream.close()
        self.sock.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for item in ("root", "config", "manifest", "microduck", "microduck-rl", "raw", "summary"):
        ap.add_argument("--" + item, type=Path, required=True)
    ap.add_argument("--socket", required=True)
    ap.add_argument("--body-port", type=int, required=True)
    ap.add_argument("--source-head", required=True)
    ap.add_argument("--reset-index", type=int, required=True)
    a = ap.parse_args()
    if not socket.gethostname().startswith("jetsonthor") or platform.python_version_tuple()[:2] != ("3", "12"):
        raise RuntimeError("Thor Python 3.12 required")
    if git_head(a.root) != a.source_head:
        raise RuntimeError("source HEAD mismatch")
    if git_head(a.microduck) != "344925c9f8fa031f85428a305b1e8ec2eaae29c1":
        raise RuntimeError("official MicroDuck SHA mismatch")
    if git_head(a.microduck_rl) != "cb70b792312d559a4da09064d92009079671815f":
        raise RuntimeError("official RL SHA mismatch")
    config = load_config(a.config)
    manifest = json.loads(a.manifest.read_text())
    specs = manifest["trials"]
    if manifest["schema_version"] != "p8-01-smoke-manifest-v1" or len(specs) != 3 or {s["motion"] for s in specs} != {"approaching", "static", "receding"}:
        raise RuntimeError("manifest mismatch")
    robotd = RobotdClient(a.socket, timeout_s=2)
    robotd.connect()
    body = OfficialPoseReader(a.body_port)
    a.raw.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    checks = {}
    initial = []
    try:
        before = robotd.health()
        with a.raw.open("w", encoding="utf-8") as output:
            for spec in specs:
                start_pose = body.read()
                initial.append(start_pose)
                trial = make_trial(config, **spec, initial_pose=start_pose)
                pipe = PerceptionPipeline()
                trial_rows = []
                start = time.monotonic()
                frames = int(config["trial_duration_s"] / config["frame_period_s"]) + 1
                for index in range(frames):
                    elapsed = index * config["frame_period_s"]
                    time.sleep(max(0, start + elapsed - time.monotonic()))
                    pose = body.read()
                    pixels = render_pixels(config, trial, pose=pose, elapsed_s=elapsed)
                    pixel_hash = pixels_sha256(pixels)
                    if pixel_hash != pixels_sha256(render_pixels(config, trial, pose=pose, elapsed_s=elapsed)):
                        raise RuntimeError("pixel replay mismatch")
                    now = time.monotonic_ns()
                    frame = pipe.process(
                        pixels, camera_timestamp_ns=now, camera_frame_id=index + 1,
                        tof_left_mm=config["tof_mm"], tof_center_mm=config["tof_mm"],
                        tof_right_mm=config["tof_mm"], tof_timestamp_ns=now,
                        tof_frame_id=index + 1, now_ns=now)
                    # Evaluation is performed after perception receives only RGB + far ToF.
                    truth = evaluator_truth(config, trial, pose=pose, elapsed_s=elapsed)
                    row = {"reset_index": a.reset_index, "trial_id": trial.trial_id,
                           "motion": trial.motion, "seed": trial.seed,
                           "frame_index": index, "elapsed_s": elapsed,
                           "official_robot_pose": pose, "pixels_sha256": pixel_hash,
                           "controller_perception": frame, "evaluator_truth": truth}
                    output.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
                    trial_rows.append(row)
                    rows.append(row)
                margin = [r["evaluator_truth"]["distance_to_boundary_m"] for r in trial_rows]
                sign = {"approaching": -1, "static": 0, "receding": 1}[trial.motion]
                # Pose may drift. Compare recorded world obstacle displacement independently.
                origin = trial_rows[5]["evaluator_truth"]
                end = trial_rows[-1]["evaluator_truth"]
                dx = end["virtual_sphere_world_x_m"] - origin["virtual_sphere_world_x_m"]
                dy = end["virtual_sphere_world_y_m"] - origin["virtual_sphere_world_y_m"]
                projection = dx * trial.axis_x + dy * trial.axis_y
                direction_ok = ((projection > 0) - (projection < 0)) == sign
                checks[trial.trial_id] = {
                    "official_pose_all_finite": all(all(math.isfinite(v) for v in r["official_robot_pose"].values()) for r in trial_rows),
                    "perception_all_valid": all(r["controller_perception"]["valid"] for r in trial_rows),
                    "world_trajectory_direction": direction_ok,
                    "distance_to_boundary_initial_m": margin[0],
                    "distance_to_boundary_final_m": margin[-1],
                    "pixel_replay": True,
                }
        after = robotd.health()
    finally:
        body.close()
        robotd.close()
    tol = config["initial_pose_tolerance"]
    spread = {k: max(p[k] for p in initial) - min(p[k] for p in initial) for k in initial[0]}
    repeatable = all(spread[k] <= tol[k] for k in tol)
    result = "PASS" if before["healthy"] and after["healthy"] and repeatable and all(
        v["official_pose_all_finite"] and v["perception_all_valid"] and v["world_trajectory_direction"] and v["pixel_replay"]
        for v in checks.values()) else "FAIL"
    summary = {
        "schema_version": "p8-01-official-smoke-v1", "result": result,
        "reset_index": a.reset_index, "source_head": a.source_head,
        "upstream_microduck_head": git_head(a.microduck),
        "upstream_rl_head": git_head(a.microduck_rl),
        "config_sha256": sha(a.config), "manifest_sha256": sha(a.manifest),
        "fixture_sha256": sha(__file__), "raw": {"path": str(a.raw),
            "sha256": sha(a.raw), "record_count": len(rows)},
        "initial_poses": initial, "pose_spread": spread, "pose_repeatable": repeatable,
        "robotd_health_before": before, "robotd_health_after": after,
        "checks": checks, "scope": "virtual/synthetic RGB obstacle; official MuJoCo trunk pose and robotd; no MuJoCo obstacle contact or stop behavior",
    }
    a.summary.write_text(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({"result": result, "reset_index": a.reset_index, "frames": len(rows), "checks": checks}, sort_keys=True))
    if result != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
