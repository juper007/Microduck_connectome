"""Deterministic raw P8-03 static/receding scorer and full manifest verifier."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def wilson_95(count: int, total: int) -> list[float]:
    if total < 1:
        raise ValueError("empty planned denominator")
    z = 1.959963984540054
    p = count / total
    d = 1 + z * z / total
    center = (p + z * z / (2 * total)) / d
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / d
    return [max(0.0, center - half), min(1.0, center + half)]


def manifest_check(root: Path) -> dict:
    """Open and check every file, including files not listed in the manifest."""
    manifest = json.loads((root / "raw-manifest.json").read_text(encoding="utf-8"))
    files = manifest["files"]
    listed = {row["path"] for row in files}
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()
              and p.name != "raw-manifest.json"}
    errors = []
    if len(listed) != len(files):
        errors.append("duplicate manifest path")
    for rel in sorted(listed ^ actual):
        errors.append(f"missing_or_extra:{rel}")
    for row in files:
        rel = row["path"]
        path = (root / rel).resolve()
        if not path.is_relative_to(root.resolve()) or rel not in actual:
            errors.append(f"invalid_path:{rel}")
            continue
        data = path.read_bytes()
        if (hashlib.sha256(data).hexdigest() != row["sha256"]
                or len(data) != row["bytes"]
                or len(data.splitlines()) != row["record_count"]):
            errors.append(f"content_mismatch:{rel}")
    return {"result": "PASS" if not errors else "FAIL", "entries": len(files),
            "errors": errors}


def planned(master: dict, stage: str) -> list[dict]:
    if stage not in ("S", "R"):
        raise ValueError("stage must be S or R")
    key = "P8-03-static" if stage == "S" else "P8-03-receding"
    rows = master["batches"][key]["runs"]
    start = 881000 if stage == "S" else 882000
    motion = "constant_relative_range" if stage == "S" else "increasing_relative_range"
    if len(rows) != 20 or [(r["trial_id"], r["seed"], r["motion"])
                           for r in rows] != [(f"{stage}{i:02d}", start + i, motion)
                                             for i in range(20)]:
        raise ValueError("master P8-03 matrix mismatch")
    return rows


def score_raw(rows: list[dict], *, trial_id: str, seed: int, stage: str,
              scored_window_ms: int = 1000) -> dict:
    """Classify from raw events only; a summary cannot turn a fault into a TN."""
    causes = []
    arm = [r for r in rows if r.get("kind") == "arm"]
    if len(arm) != 1 or arm[0].get("trial_id") != trial_id or arm[0].get("seed") != seed:
        causes.append("arm_identity")
    start = arm[0].get("timestamp_ns") if len(arm) == 1 else None
    end = start + scored_window_ms * 1_000_000 if type(start) is int else None
    if start is None:
        return {"trial_id": trial_id, "seed": seed, "false_neural_stop": False,
                "clean_true_negative": False, "safety_limit_violations": None,
                "failure_causes": causes}
    window = [r for r in rows if type(r.get("timestamp_ns")) is int
              and start <= r["timestamp_ns"] <= end and r.get("kind") != "cleanup"]
    visual = [r for r in window if r.get("kind") == "visual_frame"]
    neural = [r for r in window if r.get("kind") == "neural_step"]
    publish = [r for r in window if r.get("kind") == "control_publish"]
    motion = [r for r in window if r.get("kind") == "motion_refresh"]
    state = [r for r in window if r.get("kind") == "robot_state"]
    finish = [r for r in rows if r.get("kind") == "window_complete"]
    if len(finish) != 1 or finish[0].get("timestamp_ns", 0) < end:
        causes.append("incomplete_window")
    if len(visual) < 20 or any(r.get("source_valid") is not True for r in visual):
        causes.append("visual_missing_or_invalid")
    if len(neural) < 50 or any(r.get("runtime_healthy") is not True for r in neural):
        causes.append("neural_missing_or_unhealthy")
    if any(type(r.get("source_age_ms")) not in (int, float)
           or r["source_age_ms"] > 100 or r["source_age_ms"] < 0
           for r in neural):
        causes.append("stale_neural_visual_input")
    if len(visual) > 1 and max((b["timestamp_ns"] - a["timestamp_ns"]) / 1e6
                                for a, b in zip(visual, visual[1:])) > 100:
        causes.append("visual_gap")
    if len(neural) > 1 and max((b["timestamp_ns"] - a["timestamp_ns"]) / 1e6
                                for a, b in zip(neural, neural[1:])) > 40:
        causes.append("neural_gap")
    if any(r.get("positive_ack") is not True for r in motion):
        causes.append("motion_refresh_invalid")
    if len(motion) > 1 and max((b["timestamp_ns"] - a["timestamp_ns"]) / 1e6
                                for a, b in zip(motion, motion[1:])) > 100:
        causes.append("motion_refresh_gap")
    if not state or any(r.get("deadman_limited") is True for r in state):
        causes.append("deadman_or_missing_state")
    if (arm[0].get("moving_confirmed_ns") is None
            or arm[0].get("precondition_displacement_m", 0) < .01
            or arm[0].get("precondition_applied_vx_mps", 0) < .04):
        causes.append("moving_precondition_invalid")
    if any(r.get("kind") in ("fault", "scheduler_exception", "fixture_error")
           for r in rows if type(r.get("timestamp_ns")) is int
           and r["timestamp_ns"] >= start):
        causes.append("fault_or_exception")
    if any(r.get("watchdog_state") != "healthy" for r in publish):
        causes.append("fault_stop")
    if not visual or any(type(r.get("distance_m")) not in (int, float)
                         or not math.isfinite(r["distance_m"]) for r in visual):
        causes.append("geometry_missing")
    else:
        anchors = [r for r in rows if r.get("kind") == "prearm_visual_anchor"
                   and r.get("timestamp_ns", start) < start]
        if (len(anchors) != 1 or abs(anchors[0].get("distance_m", 0) - .85) > .005
                or abs(anchors[0].get("image_area", -1) - visual[0].get("image_area", 1)) > 1e-12):
            causes.append("prearm_baseline_jump")
        if stage == "S" and any(abs(r["distance_m"] - 0.85) > 0.005 for r in visual):
            causes.append("static_geometry")
        if stage == "R" and any(b["distance_m"] - a["distance_m"] < -0.005
                                for a, b in zip(visual, visual[1:])):
            causes.append("receding_geometry")
        if stage == "R" and any(abs(r["distance_m"] -
                                    (.85 + .20 * (r["timestamp_ns"] - start) / 1e9)) > .005
                                for r in visual):
            causes.append("receding_trajectory")
        if any(type(r.get("image_area")) not in (int, float)
               or type(r.get("bearing_rad")) not in (int, float)
               or type(r.get("pose")) is not dict for r in visual):
            causes.append("visual_geometry_lineage")
        for r in visual:
            try:
                pose = r["pose"]
                dx = r["virtual_center_x_m"] - pose["x_m"]
                dy = r["virtual_center_y_m"] - pose["y_m"]
                bearing = (math.atan2(dy, dx) - pose["heading_rad"] + math.pi) % (
                    2 * math.pi) - math.pi
                if (abs(math.hypot(dx, dy) - r["distance_m"]) > 1e-6
                        or abs(bearing - r["bearing_rad"]) > 1e-6):
                    causes.append("evaluator_geometry_mismatch")
                    break
            except (KeyError, TypeError, ValueError):
                causes.append("evaluator_geometry_missing")
                break
    false_neural_stop = any(r.get("runtime_healthy") is True
                            and r.get("decoder_stop") is True for r in neural) or any(
        r.get("neural_origin") is True and r.get("transport") == "robot.stop"
        for r in publish)
    if not false_neural_stop and len(motion) < 40:
        causes.append("motion_refresh_missing")
    if false_neural_stop:
        causes.append("false_neural_stop")
    safety = [r for r in rows if r.get("kind") == "safety_snapshot"]
    violations = (safety[0].get("violations") if len(safety) == 1 else None)
    if (len(safety) != 1 or not isinstance(safety[0].get("scheduler_result"), dict)
            or safety[0]["scheduler_result"].get("scheduler_exceptions") != 0):
        causes.append("scheduler_exception_or_missing_result")
    if type(violations) is not int or violations < 0:
        causes.append("safety_count_missing")
    elif violations:
        causes.append("safety_limit_violation")
    return {"trial_id": trial_id, "seed": seed, "false_neural_stop": false_neural_stop,
            "clean_true_negative": not causes, "safety_limit_violations": violations,
            "failure_causes": sorted(set(causes)), "visual_frames": len(visual),
            "neural_steps": len(neural), "geometry_min_m": min((r["distance_m"] for r in visual), default=None),
            "geometry_max_m": max((r["distance_m"] for r in visual), default=None)}


def score_batch(root: Path, master: dict, stage: str) -> dict:
    expected = planned(master, stage)
    journal = json.loads((root / "batch-journal.json").read_text(encoding="utf-8"))
    by_id = {r["trial_id"]: r for r in journal["ids"]}
    trials = []
    for row in expected:
        item = by_id.get(row["trial_id"])
        if not item or item.get("seed") != row["seed"] or item.get("status") != "ARMED_COMPLETE":
            trials.append({"trial_id": row["trial_id"], "seed": row["seed"],
                           "false_neural_stop": False, "clean_true_negative": False,
                           "failure_causes": ["missing_or_incomplete_id"],
                           "safety_limit_violations": None})
            continue
        attempts = item.get("attempts", [])
        if (not 1 <= len(attempts) <= 3 or attempts[-1].get("armed") is not True
                or attempts[-1].get("status") != "TRIAL_EXITED"
                or attempts[-1].get("trial_exit") != 0):
            trials.append({"trial_id": row["trial_id"], "seed": row["seed"],
                           "false_neural_stop": False, "clean_true_negative": False,
                           "failure_causes": ["attempt_accounting"],
                           "safety_limit_violations": None})
            continue
        raw = root / row["trial_id"] / attempts[-1]["name"] / "events.jsonl"
        result = score_raw(read_jsonl(raw), trial_id=row["trial_id"], seed=row["seed"], stage=stage)
        summary = root / row["trial_id"] / attempts[-1]["name"] / "summary.json"
        if (not summary.is_file() or hashlib.sha256(summary.read_bytes()).hexdigest()
                != attempts[-1].get("summary_sha256")):
            result["failure_causes"].append("summary_journal_hash")
            result["clean_true_negative"] = False
        trials.append(result)
    count = sum(t["false_neural_stop"] for t in trials)
    contaminated = sum(any(c != "false_neural_stop" for c in t["failure_causes"])
                       for t in trials)
    safety = sum(t["safety_limit_violations"] or 0 for t in trials)
    return {"schema_version": "p8-03-score-v1", "stage": stage,
            "result": "PASS" if (len(by_id) == 20 and count <= 1 and contaminated == 0
                                  and safety == 0 and all(t["safety_limit_violations"] is not None
                                                      for t in trials)) else "FAIL",
            "planned": 20, "false_neural_stops": count,
            "false_positive_rate": count / 20, "wilson_95": wilson_95(count, 20),
            "contaminated": contaminated, "safety_limit_violations": safety,
            "trials": trials}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw-root", type=Path, required=True)
    ap.add_argument("--master", type=Path, default=Path("config/p8_v2_final_protocol_v1.json"))
    ap.add_argument("--stage", choices=("S", "R"), required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    master = json.loads(args.master.read_text(encoding="utf-8"))
    score = score_batch(args.raw_root, master, args.stage)
    score["manifest"] = manifest_check(args.raw_root)
    if score["manifest"]["result"] != "PASS":
        score["result"] = "FAIL"
    args.output.write_text(json.dumps(score, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": score["result"], "stage": args.stage,
                      "false_neural_stops": score["false_neural_stops"]}))


if __name__ == "__main__":
    main()
