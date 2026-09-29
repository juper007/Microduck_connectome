"""Deterministic raw P8-03 static/receding scorer and full manifest verifier."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

from scripts.p8_03_local_reference import body_pose, verify_local_reference
from microduck_connectome.fractional_rgb_v21 import render_fractional_pixels
from microduck_connectome.looming_scenario import VirtualTrial, load_config, pixels_sha256
from microduck_connectome.g8_r5d_metrics import first_sustained, pose_speeds


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
    if manifest.get("schema_version") != "p8-03-local-raw-manifest-v1":
        errors.append("manifest_schema_version")
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


def planned(config: dict, stage: str) -> list[dict]:
    """Return fresh labels only; ordinals do not seed the official simulator."""
    if stage not in ("D", "S", "R"):
        raise ValueError("stage must be D, S or R")
    if (config.get("reset_id_semantics") != "UNIQUE_LABEL_ONLY" or
            config.get("simulator_rng_seeded") is not False):
        raise ValueError("official simulator reset IDs are labels, not RNG seeds")
    key = {"D": "development_gate", "S": "final_static", "R": "final_receding"}[stage]
    rows = config[key]["ids"] if stage == "D" else config[key]
    expected_count = 10 if stage == "D" else 20
    if (len(rows) != expected_count or
            [r.get("ordinal") for r in rows] != list(range(expected_count)) or
            len({r.get("reset_id") for r in rows}) != expected_count or
            any(r.get("mode") not in ("static", "receding") or
                r.get("arm_elapsed_s") not in (2.0, 2.6, 3.0) for r in rows) or
            (stage == "S" and any(r["mode"] != "static" for r in rows)) or
            (stage == "R" and any(r["mode"] != "receding" for r in rows))):
        raise ValueError("local-reference ID matrix mismatch")
    all_ids = ([r["reset_id"] for r in config["development_gate"]["ids"]] +
               [r["reset_id"] for r in config["final_static"]] +
               [r["reset_id"] for r in config["final_receding"]])
    if len(set(all_ids)) != len(all_ids):
        raise ValueError("development/final reset IDs collide")
    return [{"reset_id": r["reset_id"], "ordinal": r["ordinal"],
             "motion": r["mode"], "arm_elapsed_s": r["arm_elapsed_s"]}
            for r in rows]


def velocity_out_of_bounds(value: object) -> bool:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return True
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in value):
        return True
    return (abs(value[0]) > .08 or value[1] != 0 or abs(value[2]) > .5)


def score_raw(rows: list[dict], *, trial_id: str, ordinal: int, stage: str,
              scored_window_ms: int = 1000, scenario: dict | None = None,
              local_gate: dict | None = None,
              moving_gate: dict | None = None) -> dict:
    """Classify from raw events only; a summary cannot turn a fault into a TN."""
    causes = []
    arm = [r for r in rows if r.get("kind") == "arm"]
    if len(arm) != 1 or arm[0].get("reset_id") != trial_id or arm[0].get("ordinal") != ordinal:
        causes.append("arm_identity")
    start = arm[0].get("timestamp_ns") if len(arm) == 1 else None
    end = start + scored_window_ms * 1_000_000 if type(start) is int else None
    if start is None:
        return {"reset_id": trial_id, "ordinal": ordinal, "false_neural_stop": False,
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
    resets = [r for r in rows if r.get("kind") == "local_reference"
              and type(r.get("timestamp_ns")) is int and r["timestamp_ns"] < start]
    if (len(resets) != 1 or resets[0].get("result") != "PASS" or
            resets[0].get("reset_id") != trial_id or
            not isinstance(resets[0].get("reference"), dict) or
            type(resets[0].get("capture_ns")) is not int or
            resets[0]["capture_ns"] >= start):
        causes.append("local_reference_unverified")
    else:
        if not all(type(resets[0]["reference"].get(k)) in (int, float)
                   and math.isfinite(resets[0]["reference"][k])
                   for k in ("x_m", "y_m", "trunk_z_m", "heading_rad")):
            causes.append("local_reference_invalid")
    if local_gate is not None:
        transition = [r for r in rows if r.get("kind") == "reference_transition"
                      and type(r.get("timestamp_ns")) is int and r["timestamp_ns"] < start]
        try:
            if (len(transition) < local_gate["minimum_distinct_pose_samples"] or
                    transition[-1]["timestamp_ns"] - transition[0]["timestamp_ns"] <
                    int((local_gate["settle_window_s"] - .06) * 1e9)):
                raise ValueError("transition window incomplete")
            for r in transition:
                truth = body_pose(json.loads(r["raw_body_packet"]))
                reference = resets[0]["reference"]
                actual_planar = math.hypot(r["pose"]["x_m"] - reference["x_m"],
                                           r["pose"]["y_m"] - reference["y_m"])
                actual_z = abs(r["pose"]["trunk_z_m"] - reference["trunk_z_m"])
                actual_heading = abs((r["pose"]["heading_rad"] -
                                      reference["heading_rad"] + math.pi) %
                                     (2 * math.pi) - math.pi)
                if (any(abs(truth[k] - r["pose"][k]) > 1e-10 for k in r["pose"]) or
                        abs(actual_planar - r["planar_drift_m"]) > 1e-10 or
                        abs(actual_z - r["z_drift_m"]) > 1e-10 or
                        abs(actual_heading - r["heading_drift_rad"]) > 1e-10 or
                        actual_planar > local_gate["max_planar_drift_m"] or
                        actual_z > local_gate["max_z_drift_m"] or
                        actual_heading > local_gate["max_heading_drift_rad"] or
                        r["timestamp_ns"] - r["pose_request_ns"] >
                        local_gate["max_pose_response_age_ms"] * 1e6 or
                        abs(r["timestamp_ns"] - r["state_ns"]) >
                        local_gate["max_robotd_state_age_ms"] * 1e6 or
                        abs(r["timestamp_ns"] - r["health_ns"]) >
                        local_gate["max_health_age_ms"] * 1e6 or
                        r["health"].get("healthy") is not True or
                        r["health"].get("degraded") not in (None, False) or
                        r["health"].get("control_loop", {}).get("ticks", 0) <= 0 or
                        r["policy"] not in local_gate["allowed_observed_policy_states"] or
                        r["safety"].get("fallen") or r["safety"].get("limp") or
                        any(abs(v) > local_gate[k] for v, k in zip(
                            r["applied_velocity"], ("max_abs_applied_vx_mps",
                                                    "max_abs_applied_vy_mps",
                                                    "max_abs_applied_vyaw_radps")))):
                    raise ValueError("transition source or bounds invalid")
        except (KeyError, TypeError, ValueError, IndexError):
            causes.append("local_reference_transition_invalid")
        prearm_health = [r for r in rows if r.get("kind") == "prearm_health"
                         and type(r.get("timestamp_ns")) is int and r["timestamp_ns"] < start]
        if (len(prearm_health) != 1 or
                start - prearm_health[0]["timestamp_ns"] >
                local_gate["max_prearm_health_age_ms"] * 1e6 or
                prearm_health[0].get("health", {}).get("healthy") is not True):
            causes.append("prearm_health_invalid")
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
    if len(resets) == 1 and arm[0].get("moving_confirmed_ns") is not None and (
            arm[0]["moving_confirmed_ns"] <= resets[0].get("capture_ns", 0)):
        causes.append("moving_before_local_reference")
    if moving_gate is not None:
        pre_rows = [r for r in rows if r.get("kind") == "precondition_motion"
                    and type(r.get("timestamp_ns")) is int and r["timestamp_ns"] < start]
        try:
            required = round(moving_gate["duration_s"] * 1000 /
                             moving_gate["command_period_ms"])
            if len(pre_rows) != required:
                raise ValueError("precondition count")
            poses = [{"timestamp_ns": r["pose_ns"],
                      "x_m": r["pose"]["x_m"], "y_m": r["pose"]["y_m"]}
                     for r in pre_rows]
            if any(r.get("robot_move_ack") is None or
                   type(r.get("state_ns")) is not int or
                   type(r.get("pose_ns")) is not int or
                   type(r.get("pose_request_ns")) is not int or
                   any(abs(body_pose(json.loads(r["raw_body_packet"]))[k] -
                           r["pose"][k]) > 1e-10
                       for k in ("x_m", "y_m", "trunk_z_m", "heading_rad")) or
                   not 0 <= r["pose_ns"] - r["pose_request_ns"] <=
                   moving_gate["maximum_pose_age_ms"] * 1e6 or
                   not r["timestamp_ns"] <= r["state_ns"] <= r["pose_ns"] or
                   r["state_ns"] - r["timestamp_ns"] >
                   moving_gate["maximum_state_age_ms"] * 1e6 or
                   r["pose_ns"] - r["state_ns"] >
                   moving_gate["maximum_pose_age_ms"] * 1e6 or
                   type(r.get("applied_velocity")) is not list or
                   len(r["applied_velocity"]) != 3 or
                   not all(type(v) in (int, float) and math.isfinite(v)
                           for v in r["applied_velocity"]) or
                   any(str(reason).lower() in ("deadman", "fault", "safety")
                       for reason in r.get("limited_by", []))
                   for r in pre_rows):
                raise ValueError("precondition raw freshness or safety")
            speeds = pose_speeds(poses, window_ms=100, max_window_ms=140)
            confirmed = first_sustained(
                speeds, threshold_mps=moving_gate["minimum_pose_speed_mps"],
                duration_ms=moving_gate["minimum_speed_sustain_ms"], at_or_above=True)
            displacement = math.hypot(poses[-1]["x_m"] - poses[0]["x_m"],
                                      poses[-1]["y_m"] - poses[0]["y_m"])
            applied_vx = pre_rows[-1]["applied_velocity"][0]
            if (confirmed is None or confirmed != arm[0]["moving_confirmed_ns"] or
                    abs(displacement - arm[0]["precondition_displacement_m"]) > 1e-10 or
                    abs(applied_vx - arm[0]["precondition_applied_vx_mps"]) > 1e-10 or
                    displacement < moving_gate["minimum_trunk_displacement_m"] or
                    applied_vx < moving_gate["minimum_fresh_applied_vx_mps"]):
                raise ValueError("precondition summary does not match raw")
        except (KeyError, TypeError, ValueError, IndexError, ZeroDivisionError):
            causes.append("moving_precondition_raw_invalid")
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
                if scenario is not None:
                    raw_pose = body_pose(json.loads(r["raw_body_packet"]))
                    if (any(abs(raw_pose[k] - pose[k]) > 1e-10 for k in pose) or
                            type(r["pose_request_ns"]) is not int or
                            type(r["pose_response_ns"]) is not int or
                            not r["pose_request_ns"] <= r["pose_response_ns"] or
                            not 0 <= r["pose_response_ns"] - r["timestamp_ns"] <=
                            100_000_000):
                        causes.append("pose_source_lineage_or_freshness")
                        break
                    trial = VirtualTrial(trial_id, ordinal, "static",
                                         r["virtual_center_x_m"],
                                         r["virtual_center_y_m"],
                                         math.cos(pose["heading_rad"]),
                                         math.sin(pose["heading_rad"]))
                    pixels = render_fractional_pixels(scenario, trial, pose=pose,
                                                      elapsed_s=0)
                    area = sum(p[0] for line in pixels for p in line) / (
                        255 * scenario["image_width_px"] * scenario["image_height_px"])
                    if (abs(area - r["image_area"]) > 1e-12 or
                            pixels_sha256(pixels) != r.get("pixels_sha256")):
                        causes.append("image_area_or_pixel_lineage")
                        break
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
            except (KeyError, TypeError, ValueError, IndexError):
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
    return {"reset_id": trial_id, "ordinal": ordinal, "false_neural_stop": false_neural_stop,
            "clean_true_negative": not causes, "safety_limit_violations": violations,
            "failure_causes": sorted(set(causes)), "visual_frames": len(visual),
            "neural_steps": len(neural), "geometry_min_m": min((r["distance_m"] for r in visual), default=None),
            "geometry_max_m": max((r["distance_m"] for r in visual), default=None)}


def audit_original_ledgers(folder: Path, events: list[dict], summary: dict,
                           tof_mm: int | None = None) -> list[str]:
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
    visual_by_id = {r.get("frame_id"): r for r in visual}
    if (len(visual_by_id) != len(visual)
            or any(type(r.get("frame_id")) is not int or
                   type(r.get("timestamp_ns")) is not int for r in visual)):
        errors.append("original_visual_identity_invalid")
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
        if tof_mm is not None and (
                original.get("tof_source") != "frozen_synthetic_fixture" or
                any(original.get(k) != tof_mm for k in (
                    "tof_left_mm", "tof_center_mm", "tof_right_mm")) or
                original.get("tof_timestamp_ns") != original.get("timestamp_ns") or
                original.get("tof_frame_id") != original.get("frame_id") or
                event.get("tof_timestamp_ns") != original.get("tof_timestamp_ns") or
                event.get("tof_frame_id") != original.get("tof_frame_id") or
                event.get("source_frame_id") != original.get("frame_id") or
                event.get("pixels_sha256") != original.get("pixels_sha256")):
            errors.append("original_rgb_tof_lineage_invalid")
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
        source = visual_by_id.get(original.get("perception_frame_id"))
        if source is None:
            errors.append("original_neural_visual_lineage_missing")
            break
        source_ns = original.get("perception_timestamp_ns")
        started_ns = original.get("neural_call_started_ns")
        age_ms = original.get("perception_age_ms")
        if (type(source_ns) is not int or source_ns != source.get("timestamp_ns")
                or type(started_ns) is not int or type(age_ms) not in (int, float)
                or not math.isfinite(age_ms)
                or not 0 <= started_ns - source_ns <= 100_000_000
                or not math.isclose(age_ms, (started_ns - source_ns) / 1e6,
                                    rel_tol=0, abs_tol=1e-6)):
            errors.append("original_neural_visual_freshness_invalid")
            break
    return errors


def observed_healthy_stop(rows: list[dict]) -> bool:
    """Use the scored window when arm time is known, including abnormal exits."""
    arms = [r.get("timestamp_ns") for r in rows if r.get("kind") == "arm"]
    start = arms[0] if len(arms) == 1 and type(arms[0]) is int else None
    def scored(row: dict) -> bool:
        if start is None:  # UNKNOWN_ARM: retain uncertainty and fail closed.
            return True
        stamp = row.get("timestamp_ns")
        return type(stamp) is int and start <= stamp <= start + 1_000_000_000
    return any(scored(r) and r.get("kind") == "neural_step" and
               r.get("runtime_healthy") is True and
               (type(r.get("dn_escape")) in (int, float) and
                r["dn_escape"] >= .5 or r.get("decoder_stop") is True)
               for r in rows) or any(
        scored(r) and r.get("kind") == "control_publish" and
        r.get("neural_origin") is True
        and r.get("transport") == "robot.stop" for r in rows)


def score_batch(root: Path, config: dict, stage: str) -> dict:
    expected = planned(config, stage)
    journal = json.loads((root / "batch-journal.json").read_text(encoding="utf-8"))
    journal_valid = (journal.get("schema_version") == "p8-03-local-batch-journal-v1"
                     and journal.get("stage") == stage
                     and journal.get("reset_id_semantics") == "UNIQUE_LABEL_ONLY"
                     and journal.get("simulator_rng_seeded") is False
                     and isinstance(journal.get("source_head"), str)
                     and isinstance(journal.get("config_sha256"), str))
    scenario_path = Path(journal["source_path"]) / "config/looming_scenario_v1.json"
    scenario_bytes = scenario_path.read_bytes().replace(b"\r\n", b"\n")
    if hashlib.sha256(scenario_bytes).hexdigest() != (
            config["selected_pipeline"]["scenario_config_sha256"]):
        raise ValueError("frozen scenario source hash mismatch")
    scenario = load_config(scenario_path)
    by_id = {r["reset_id"]: r for r in journal["ids"]}
    trials = []
    for row in expected:
        item = by_id.get(row["reset_id"])
        attempts = item.get("attempts", []) if item else []
        evidence_folders = {root / row["reset_id"] / a.get("name", "") for a in attempts}
        evidence_folders.update((root / row["reset_id"]).glob("attempt-*"))
        observed_stop = False
        for evidence_folder in evidence_folders:
            try:
                observed_stop |= observed_healthy_stop(read_jsonl(
                    evidence_folder / "events.jsonl"))
            except (OSError, ValueError, json.JSONDecodeError):
                pass
        if not item or item.get("ordinal") != row["ordinal"] or not attempts:
            trials.append({"reset_id": row["reset_id"], "ordinal": row["ordinal"],
                           "false_neural_stop": observed_stop, "clean_true_negative": False,
                           "failure_causes": ["missing_or_incomplete_id"],
                           "safety_limit_violations": None})
            continue
        attempt_valid = (item.get("status") == "ARMED_COMPLETE" and
                         1 <= len(attempts) <= 3 and
                         attempts[-1].get("armed") is True and
                         attempts[-1].get("status") == "TRIAL_EXITED" and
                         attempts[-1].get("trial_exit") == 0 and
                         all(a.get("status") == "PREARM_FAILED" and
                             a.get("retry_cause_code") in
                             config["allowed_prearm_retry_cause_codes"] and
                             a.get("armed") is False for a in attempts[:-1]))
        folder = root / row["reset_id"] / attempts[-1]["name"]
        try:
            marker = json.loads((folder / "armed.json").read_text(encoding="utf-8"))
            marker_valid = (
                marker.get("schema_version") == "p8-03-local-arm-v1" and
                marker.get("task") == "P8-03-LOCAL-REFERENCE-PROTOCOL-V1" and
                marker.get("reset_id") == row["reset_id"] and
                marker.get("ordinal") == row["ordinal"] and
                marker.get("attempt") == len(attempts) and
                marker.get("source_head") == journal.get("source_head") and
                marker.get("config_sha256") == journal.get("config_sha256") and
                marker.get("state") == "ARMED" and
                type(marker.get("armed_at_utc_ns")) is int and
                type(marker.get("armed_at_monotonic_ns")) is int)
        except (OSError, ValueError):
            marker_valid = False
        raw = folder / "events.jsonl"
        try:
            events = read_jsonl(raw)
        except (OSError, ValueError, json.JSONDecodeError):
            events = []
        geometry_stage = "S" if row["motion"] == "static" else "R"
        try:
            result = score_raw(events, trial_id=row["reset_id"], ordinal=row["ordinal"],
                               stage=geometry_stage, scenario=scenario,
                               local_gate=config["settled_gate"],
                               moving_gate=config["moving_gate"])
        except (KeyError, TypeError, ValueError, IndexError, ZeroDivisionError):
            result = {"reset_id": row["reset_id"], "ordinal": row["ordinal"],
                      "false_neural_stop": False, "clean_true_negative": False,
                      "failure_causes": ["incomplete_raw"],
                      "safety_limit_violations": None}
        # A completed, accounted trial uses only score_raw's frozen 1,000 ms
        # window. Abnormal/unknown attempts remain conservative and terminal.
        if not attempt_valid:
            result["false_neural_stop"] = result["false_neural_stop"] or observed_stop
        if result["false_neural_stop"] and "false_neural_stop" not in result["failure_causes"]:
            result["failure_causes"].append("false_neural_stop")
        if not attempt_valid:
            result["failure_causes"].append("attempt_accounting")
            result["clean_true_negative"] = False
        if not marker_valid or not any(r.get("kind") == "arm" and
                type(r.get("timestamp_ns")) is int and
                r["timestamp_ns"] >= marker.get("armed_at_monotonic_ns")
                for r in events):
            result["failure_causes"].append("arm_marker_invalid")
            result["clean_true_negative"] = False
        reset_path = root / row["reset_id"] / attempts[-1]["name"] / "local-reference.json"
        try:
            reset = json.loads(reset_path.read_text(encoding="utf-8"))
            reset_agrees = (verify_local_reference(reset, config["settled_gate"]) and
                            reset.get("reset_id") == row["reset_id"] and
                            reset.get("attempt") == len(attempts) and
                            hashlib.sha256(reset_path.read_bytes()).hexdigest() ==
                            attempts[-1].get("local_reference_sha256"))
        except (OSError, ValueError):
            reset_agrees = False
        if not reset_agrees:
            result["failure_causes"].append("local_reference_journal_mismatch")
            result["clean_true_negative"] = False
        else:
            raw_reset = [r for r in events if r.get("kind") == "local_reference"]
            expected_reference_hash = hashlib.sha256(reset_path.read_bytes()).hexdigest()
            if (len(raw_reset) != 1 or raw_reset[0].get("reference") != reset.get("reference")
                    or raw_reset[0].get("capture_ns") != reset.get("capture_ns")
                    or (config["task_id"] == "P8-03-LOCAL-REFERENCE-V1-R1" and
                        (raw_reset[0].get("reference_sha256") != expected_reference_hash or
                         marker.get("reference_sha256") != expected_reference_hash))):
                result["failure_causes"].append("local_reference_event_mismatch")
                result["clean_true_negative"] = False
        summary = folder / "summary.json"
        if (not summary.is_file() or hashlib.sha256(summary.read_bytes()).hexdigest()
                != attempts[-1].get("summary_sha256")):
            result["failure_causes"].append("summary_journal_hash")
            result["clean_true_negative"] = False
        else:
            retained_summary = json.loads(summary.read_text(encoding="utf-8"))
            if (retained_summary.get("reset_id") != row["reset_id"]
                    or retained_summary.get("ordinal") != row["ordinal"]
                    or retained_summary.get("stage") != stage
                    or retained_summary.get("armed") is not True
                    or retained_summary.get("source_head") != journal.get("source_head")
                    or (config["task_id"] == "P8-03-LOCAL-REFERENCE-V1-R1" and
                        retained_summary.get("reference_sha256") !=
                        attempts[-1].get("local_reference_sha256"))):
                result["failure_causes"].append("summary_identity")
            result["failure_causes"].extend(
                audit_original_ledgers(folder, events, retained_summary,
                                       tof_mm=scenario["tof_mm"]))
            if result["failure_causes"]:
                result["clean_true_negative"] = False
        trials.append(result)
    count = sum(t["false_neural_stop"] for t in trials)
    contaminated = sum(any(c != "false_neural_stop" for c in t["failure_causes"])
                       for t in trials)
    safety = sum(t["safety_limit_violations"] or 0 for t in trials)
    final_down = journal.get("final_sim_down") or {}
    down_pass = (final_down.get("exit") == 0 and
                 final_down.get("state_probe_result") == "PASS")
    target_count = 10 if stage == "D" else 20
    limit = target_count if stage == "D" else 1
    return {"schema_version": "p8-03-local-score-v1", "stage": stage,
            "result": "PASS" if (journal_valid and len(by_id) == target_count and count <= limit
                                  and contaminated == 0 and safety == 0 and down_pass
                                  and all(t["safety_limit_violations"] is not None
                                          for t in trials)) else "FAIL",
            "planned": target_count, "false_neural_stops": count,
            "false_positive_rate": count / target_count,
            "wilson_95": wilson_95(count, target_count),
            "contaminated": contaminated, "safety_limit_violations": safety,
            "journal_valid": journal_valid, "final_down_valid": down_pass,
            "trials": trials}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw-root", type=Path, required=True)
    ap.add_argument("--config", type=Path, default=Path("config/p8_03_local_reference_v1_r1.json"))
    ap.add_argument("--stage", choices=("D", "S", "R"), required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    score = score_batch(args.raw_root, config, args.stage)
    score["manifest"] = manifest_check(args.raw_root)
    if score["manifest"]["result"] != "PASS":
        score["result"] = "FAIL"
    args.output.write_text(json.dumps(score, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": score["result"], "stage": args.stage,
                      "false_neural_stops": score["false_neural_stops"]}))


if __name__ == "__main__":
    main()
