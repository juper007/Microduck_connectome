"""Replay P7-01 visual scenes against the official Thor robotd/MuJoCo state."""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import platform
import socket
import time

from microduck_connectome.perception_compositor import PerceptionPipeline
from microduck_connectome.robotd_client import RobotdClient
from microduck_connectome.target_scenario import (
    evaluator_truth, load_target_scenario_config, make_target_trial,
    pixels_sha256, render_camera_pixels,
)
from scripts.p6_telemetry_runtime_fixture import BodyReader, git_head


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--body-port", type=int, required=True)
    parser.add_argument("--microduck", type=Path, required=True)
    parser.add_argument("--microduck-rl", type=Path, required=True)
    parser.add_argument("--source-head", required=True)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()
    hostname = socket.gethostname()
    if not hostname.startswith("jetsonthor") or platform.python_version_tuple()[:2] != ("3", "12"):
        raise RuntimeError("P7-01 runtime authority requires Thor Python 3.12")
    config = load_target_scenario_config(args.config)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest["schema_version"] != "p7-01-scenario-manifest-v1" or len(manifest["smoke_trials"]) < 5:
        raise ValueError("scenario manifest is incomplete")
    robotd = RobotdClient(args.socket, timeout_s=2.0)
    robotd.connect()
    body = BodyReader(args.body_port)
    args.raw.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    records = 0
    by_trial = defaultdict(list)
    initial_poses = []
    health_before = robotd.health()
    started_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        with args.raw.open("wb") as output:
            for trial_spec in manifest["smoke_trials"]:
                initial_body = body.read()
                initial_poses.append(initial_body)
                trial = make_target_trial(
                    config, **trial_spec,
                    initial_robot_heading_rad=initial_body["heading_rad"],
                )
                pipeline = PerceptionPipeline()
                start = time.monotonic()
                for frame_index in range(30):
                    elapsed_s = frame_index * 0.1
                    time.sleep(max(0.0, start + elapsed_s - time.monotonic()))
                    now_ns = time.monotonic_ns()
                    current_body = body.read()
                    pixels = render_camera_pixels(
                        config, trial, heading_rad=current_body["heading_rad"],
                        elapsed_s=elapsed_s, frame_index=frame_index,
                    )
                    pixel_hash = pixels_sha256(pixels)
                    replay = render_camera_pixels(
                        config, trial, heading_rad=current_body["heading_rad"],
                        elapsed_s=elapsed_s, frame_index=frame_index,
                    )
                    if pixels_sha256(replay) != pixel_hash:
                        raise AssertionError("same seed/config/pose/time failed pixel replay")
                    frame = pipeline.process(
                        pixels, camera_timestamp_ns=now_ns,
                        camera_frame_id=frame_index + 1,
                        tof_left_mm=config["tof_mm"],
                        tof_center_mm=config["tof_mm"],
                        tof_right_mm=config["tof_mm"],
                        tof_timestamp_ns=now_ns, tof_frame_id=frame_index + 1,
                        now_ns=now_ns,
                    )
                    # Evaluator truth is computed only after perception has
                    # received pixels. It is never an input to the pipeline.
                    truth = evaluator_truth(config, trial, elapsed_s=elapsed_s)
                    item = {
                        "trial_id": trial.trial_id, "seed": trial.seed,
                        "frame_index": frame_index, "elapsed_s": elapsed_s,
                        "timestamp_ns": now_ns, "pixels_sha256": pixel_hash,
                        "robot_heading_rad": current_body["heading_rad"],
                        "controller_perception": frame,
                        "evaluation_truth": truth,
                    }
                    encoded = (json.dumps(item, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")
                    output.write(encoded)
                    digest.update(encoded)
                    records += 1
                    by_trial[trial.trial_id].append(item)
        health_after = robotd.health()
    finally:
        body.close()
        robotd.close()

    checks = {}
    warmup = config["warmup_duration_s"]
    for trial_spec in manifest["smoke_trials"]:
        rows = by_trial[trial_spec["trial_id"]]
        active = [row for row in rows if row["elapsed_s"] >= warmup and row["evaluation_truth"]["target_present"]]
        if trial_spec["target_present"]:
            first = active[0]["controller_perception"]
            expected_sign = -1 if trial_spec["target_side"] == "left" else 1
            checks[trial_spec["trial_id"]] = first["valid"] and first["target_x"] * expected_sign > 0
            if trial_spec["target_motion"] == "slow_crossing":
                last = active[-1]["controller_perception"]
                checks[trial_spec["trial_id"]] &= last["target_x"] * expected_sign < 0
        else:
            checks[trial_spec["trial_id"]] = all(
                row["controller_perception"]["valid"] and row["controller_perception"]["target_area"] == 0
                for row in rows
            )
    headings = [item["heading_rad"] for item in initial_poses]
    heights = [item["trunk_z"] for item in initial_poses]
    heading_spread = max(headings) - min(headings)
    trunk_spread = max(heights) - min(heights)
    checks["initial_pose_repeatability"] = (
        heading_spread <= config["initial_pose_tolerance"]["heading_rad"]
        and trunk_spread <= config["initial_pose_tolerance"]["trunk_z_m"]
    )
    checks["official_robotd_health"] = bool(health_before["healthy"] and health_after["healthy"])
    checks["all_frames_valid"] = all(row["controller_perception"]["valid"] for rows in by_trial.values() for row in rows)
    result = "PASS" if all(checks.values()) else "FAIL"
    summary = {
        "schema_version": "p7-01-scenario-smoke-v1",
        "execution_target": "Thor", "hostname": hostname,
        "source_head": args.source_head,
        "started_utc": started_utc,
        "ended_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "microduck_commit": git_head(args.microduck),
        "microduck_rl_commit": git_head(args.microduck_rl),
        "scenario_config_sha256": sha256_file(args.config),
        "scenario_manifest_sha256": sha256_file(args.manifest),
        "fixture_sha256": sha256_file(Path(__file__)),
        "trial_count": len(manifest["smoke_trials"]),
        "frame_count": records,
        "initial_poses": initial_poses,
        "initial_heading_spread_rad": heading_spread,
        "initial_trunk_z_spread_m": trunk_spread,
        "health_before": health_before,
        "health_after": health_after,
        "checks": checks,
        "raw_artifact": {"path": str(args.raw), "sha256": digest.hexdigest(), "bytes": args.raw.stat().st_size, "record_count": records},
        "result": result,
        "scope": "read-only official simulator state plus synthetic camera pixels through frozen P4 perception; not a steering behavior trial",
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"result": result, "trial_count": summary["trial_count"],
                      "frame_count": records, "checks": checks}, sort_keys=True))
    if result != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
