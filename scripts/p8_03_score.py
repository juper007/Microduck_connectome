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


def velocity_out_of_bounds(value: object) -> bool:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return True
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in value):
        return True
    return (abs(value[0]) > .08 or value[1] != 0 or abs(value[2]) > .5)


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
    before_health = [r for r in rows if r.get("kind") == "robotd_health_before"
                     and type(r.get("timestamp_ns")) is int and r["timestamp_ns"] < start]
    after_health = [r for r in rows if r.get("kind") == "robotd_health_after"]
    if (len(before_health) != 1 or before_health[0].get("healthy") is not True
            or len(after_health) != 1 or after_health[0].get("healthy") is not True):
        causes.append("robotd_health")
    window = [r for r in rows if type(r.get("timestamp_ns")) is int
              and start <= r["timestamp_ns"] <= end and r.get("kind") != "cleanup"]
    visual = [r for r in window if r.get("kind") == "visual_frame"]
    neural = [r for r in window if r.get("kind") == "neural_step"]
    publish = [r for r in window if r.get("kind") == "control_publish"]
    motion = [r for r in window if r.get("kind") == "motion_refresh"]
    state = [r for r in window if r.get("kind") == "robot_state"]
    resets = [r for r in rows if r.get("kind") == "pose_reset"
              and type(r.get("timestamp_ns")) is int and r["timestamp_ns"] < start]
    if len(resets) != 1 or resets[0].get("result") != "PASS":
        causes.append("pose_reset_unverified")
    else:
        try:
            reset = resets[0]
            if any((abs((reset["pose"][key] - reset["reference"][key] + math.pi)
                         % (2 * math.pi) - math.pi) if key == "heading_rad" else
                    abs(reset["pose"][key] - reset["reference"][key])) > limit
                   for key, limit in reset["tolerance"].items()):
                causes.append("pose_reset_tolerance")
        except (KeyError, TypeError):
            causes.append("pose_reset_lineage")
    finish = [r for r in rows if r.get("kind") == "window_complete"]
    if len(finish) != 1 or finish[0].get("timestamp_ns", 0) < end:
        causes.append("incomplete_window")
    if len(visual) < 20 or any(r.get("source_valid") is not True for r in visual):
        causes.append("visual_missing_or_invalid")
    if len(neural) < 50 or any(r.get("runtime_healthy") is not True for r in neural):
        causes.append("neural_missing_or_unhealthy")
    if any(type(r.get("source_age_ms")) not in (int, float)
           or not math.isfinite(r["source_age_ms"])
           or r["source_age_ms"] > 100 or r["source_age_ms"] < 0
           for r in neural):
        causes.append("stale_neural_visual_input")
    if len(visual) > 1 and max((b["timestamp_ns"] - a["timestamp_ns"]) / 1e6
                                for a, b in zip(visual, visual[1:])) > 100:
        causes.append("visual_gap")
    if len(neural) > 1 and max((b["timestamp_ns"] - a["timestamp_ns"]) / 1e6
                                for a, b in zip(neural, neural[1:])) > 40:
        causes.append("neural_gap")
    valid_publish = (len(publish) >= 40 and all(
        type(r.get("sequence")) is int
        and type(r.get("call_ns")) is int
        and type(r.get("ack_ns")) is int
        and r["ack_ns"] == r["timestamp_ns"]
        and r["ack_ns"] >= r["call_ns"]
        and isinstance(r.get("intent"), dict)
        and r["intent"].get("stop") == r.get("stop")
        for r in publish))
    if not valid_publish:
        causes.append("control_publish_missing_or_invalid")
    if valid_publish and len(publish) > 1 and (any(b["sequence"] <= a["sequence"]
                                 for a, b in zip(publish, publish[1:]))
                             or max((b["timestamp_ns"] - a["timestamp_ns"]) / 1e6
                                    for a, b in zip(publish, publish[1:])) > 40):
        causes.append("control_publish_sequence_or_gap")
    if any(r.get("transport") not in ("robot.stop",
                                        "suppressed_neutral_for_stop_causality_fixture")
           or (r.get("stop") and r.get("transport") != "robot.stop")
           or (not r.get("stop") and r.get("transport") !=
               "suppressed_neutral_for_stop_causality_fixture") for r in publish):
        causes.append("control_transport")
    if any(r.get("positive_ack") is not True or r.get("robot_move_result") is None
           or type(r.get("call_ns")) is not int
           or type(r.get("write_ns")) is not int
           or not r["call_ns"] <= r["write_ns"] <= r["timestamp_ns"]
           for r in motion):
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
               or not math.isfinite(r["image_area"])
               or type(r.get("bearing_rad")) not in (int, float)
               or not math.isfinite(r["bearing_rad"])
               or type(r.get("pose")) is not dict for r in visual):
            causes.append("visual_geometry_lineage")
        for r in visual:
            try:
                pose = r["pose"]
                dx = r["virtual_center_x_m"] - pose["x_m"]
                dy = r["virtual_center_y_m"] - pose["y_m"]
                bearing = (math.atan2(dy, dx) - pose["heading_rad"] + math.pi) % (
                    2 * math.pi) - math.pi
                if (not all(math.isfinite(v) for v in
                            (dx, dy, pose["heading_rad"], r["bearing_rad"]))
                        or abs(math.hypot(dx, dy) - r["distance_m"]) > 1e-6
                        or abs(bearing - r["bearing_rad"]) > 1e-6):
                    causes.append("evaluator_geometry_mismatch")
                    break
            except (KeyError, TypeError, ValueError):
                causes.append("evaluator_geometry_missing")
                break
    false_neural_stop = any(r.get("runtime_healthy") is True
                            and (r.get("dn_escape", 0) >= .5
                                 or r.get("decoder_stop") is True) for r in neural) or any(
        r.get("neural_origin") is True and r.get("transport") == "robot.stop"
        for r in publish)
    if any(r.get("runtime_healthy") is True and r.get("dn_escape", 0) >= .5
           and r.get("decoder_stop") is not True for r in neural):
        causes.append("dn_decoder_mismatch")
    if not false_neural_stop and len(motion) < 40:
        causes.append("motion_refresh_missing")
    if not false_neural_stop:
        if (len(state) < 40 or any(type(r.get("applied_velocity")) not in (list, tuple)
                                  or len(r["applied_velocity"]) != 3
                                  or type(r["applied_velocity"][0]) not in (int, float)
                                  or not math.isfinite(r["applied_velocity"][0])
                                  or r["applied_velocity"][0] < .04 for r in state)):
            causes.append("applied_motion_missing")
        if len(visual) >= 2:
            first_pose, last_pose = visual[0].get("pose", {}), visual[-1].get("pose", {})
            if (math.hypot(last_pose.get("x_m", 0) - first_pose.get("x_m", 0),
                           last_pose.get("y_m", 0) - first_pose.get("y_m", 0)) < .01):
                causes.append("body_not_moving")
            try:
                speeds = [math.hypot(b["pose"]["x_m"] - a["pose"]["x_m"],
                                     b["pose"]["y_m"] - a["pose"]["y_m"]) /
                          ((b["timestamp_ns"] - a["timestamp_ns"]) / 1e9)
                          for a, b in zip(visual, visual[2:])]
                if (not speeds or sum(speed >= .015 for speed in speeds) <
                        math.ceil(.8 * len(speeds)) or
                        any(speed < .015 for speed in speeds[-2:])):
                    causes.append("pose_speed_not_sustained")
            except (KeyError, ZeroDivisionError, TypeError):
                causes.append("pose_speed_missing")
        if len(state) > 1 and max((b["timestamp_ns"] - a["timestamp_ns"]) / 1e6
                                  for a, b in zip(state, state[1:])) > 100:
            causes.append("robot_state_gap")
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
    if (any(velocity_out_of_bounds(r.get("applied_velocity")) or
            velocity_out_of_bounds(r.get("requested_velocity")) for r in state)
            or any(velocity_out_of_bounds([
                r.get("intent", {}).get("vx"), r.get("intent", {}).get("vy"),
                r.get("intent", {}).get("vyaw")]) for r in publish)):
        causes.append("raw_safety_limit_violation")
    return {"trial_id": trial_id, "seed": seed, "false_neural_stop": false_neural_stop,
            "clean_true_negative": not causes, "safety_limit_violations": violations,
            "failure_causes": sorted(set(causes)), "visual_frames": len(visual),
            "neural_steps": len(neural), "geometry_min_m": min((r["distance_m"] for r in visual), default=None),
            "geometry_max_m": max((r["distance_m"] for r in visual), default=None)}


def audit_original_ledgers(folder: Path, events: list[dict], summary: dict) -> list[str]:
    """Require condensed event rows to agree with the retained original ledgers."""
    errors = []
    visual_path = folder / "visual-frames.jsonl"
    neural_path = folder / "neural-ledger.jsonl"
    event_path = folder / "events.jsonl"
    try:
        visual = read_jsonl(visual_path)
        neural = read_jsonl(neural_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return ["original_ledger_unreadable"]
    if (summary.get("event_sha256") != hashlib.sha256(event_path.read_bytes()).hexdigest()
            or summary.get("visual_sha256") != hashlib.sha256(visual_path.read_bytes()).hexdigest()
            or summary.get("neural_ledger_sha256") !=
            hashlib.sha256(neural_path.read_bytes()).hexdigest()):
        errors.append("summary_raw_hash_mismatch")
    event_visual = [r for r in events if r.get("kind") == "visual_frame"]
    event_neural = [r for r in events if r.get("kind") == "neural_step"]
    visual_ids = {r.get("frame_id") for r in visual}
    if len(event_visual) != len(visual) or len(event_neural) != len(neural):
        errors.append("original_ledger_count_mismatch")
    for event, original in zip(event_visual, visual):
        if (event.get("timestamp_ns") != original.get("timestamp_ns")
                or event.get("source_valid") != original.get("perception_valid")
                or type(original.get("perception_target_area")) not in (int, float)
                or abs(event.get("image_area", -1) -
                       original["perception_target_area"]) > 1e-12):
            errors.append("original_visual_disagreement")
            break
    for event, original in zip(event_neural, neural):
        healthy = bool(original.get("dn_runtime_healthy") and
                       original.get("male_cns_healthy"))
        if (event.get("timestamp_ns") != original.get("neural_call_timestamp_ns")
                or event.get("runtime_healthy") != healthy
                or event.get("dn_escape") != original.get("dn_escape", 0)
                or event.get("decoder_stop") != original.get("raw_decoder_stop", False)
                or event.get("source_age_ms") != original.get("perception_age_ms")
                or event.get("source_frame_id") != original.get("perception_frame_id")):
            errors.append("original_neural_disagreement")
            break
        if (original.get("input_none") or original.get("result_none")
                or original.get("perception_valid") is not True):
            errors.append("original_neural_input_invalid")
            break
        if original.get("perception_frame_id") not in visual_ids:
            errors.append("original_neural_visual_lineage_missing")
            break
    return errors


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
        folder = root / row["trial_id"] / attempts[-1]["name"]
        raw = folder / "events.jsonl"
        events = read_jsonl(raw)
        result = score_raw(events, trial_id=row["trial_id"], seed=row["seed"], stage=stage)
        reset_path = root / row["trial_id"] / attempts[-1]["name"] / "pose-reset.json"
        try:
            reset = json.loads(reset_path.read_text(encoding="utf-8"))
            reset_agrees = (reset == attempts[-1].get("pose_reset")
                            and reset.get("result") == "PASS"
                            and reset.get("reference") == journal.get("reset_reference"))
        except (OSError, ValueError):
            reset_agrees = False
        if not reset_agrees:
            result["failure_causes"].append("pose_reset_journal_mismatch")
            result["clean_true_negative"] = False
        else:
            raw_reset = [r for r in events if r.get("kind") == "pose_reset"]
            if (len(raw_reset) != 1 or raw_reset[0].get("reference") != reset.get("reference")
                    or raw_reset[0].get("pose") != reset.get("second_pose")
                    or raw_reset[0].get("tolerance") != reset.get("tolerance")):
                result["failure_causes"].append("pose_reset_event_mismatch")
                result["clean_true_negative"] = False
        summary = folder / "summary.json"
        if (not summary.is_file() or hashlib.sha256(summary.read_bytes()).hexdigest()
                != attempts[-1].get("summary_sha256")):
            result["failure_causes"].append("summary_journal_hash")
            result["clean_true_negative"] = False
        else:
            retained_summary = json.loads(summary.read_text(encoding="utf-8"))
            if (retained_summary.get("trial_id") != row["trial_id"]
                    or retained_summary.get("seed") != row["seed"]
                    or retained_summary.get("stage") != stage
                    or retained_summary.get("armed") is not True
                    or retained_summary.get("source_head") != journal.get("source_head")):
                result["failure_causes"].append("summary_identity")
            result["failure_causes"].extend(
                audit_original_ledgers(folder, events, retained_summary))
            if result["failure_causes"]:
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
