"""Regenerate the P8-02 fixed-denominator score from retained trial ledgers."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import random
from statistics import median

from microduck_connectome.g8_r5d_metrics import (
    bounded_neural_lineage, deadman_timing, first_sustained, pose_speeds,
    valid_state_path,
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="ascii").splitlines()]


def wilson(successes: int, total: int) -> list[float]:
    z = 1.959963984540054
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    radius = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return [max(0.0, center - radius), min(1.0, center + radius)]


def timing(values: list[float]) -> dict:
    ordered = sorted(values)
    return {"count": len(ordered), "median_ms": median(ordered) if ordered else None,
            "p95_nearest_rank_ms": ordered[math.ceil(.95 * len(ordered)) - 1] if ordered else None,
            "maximum_ms": ordered[-1] if ordered else None}


def pose_rows_from_events(events: list[dict]) -> list[dict]:
    samples = []
    for event in events:
        if event.get("kind") not in ("precondition_motion", "control_publish",
                                      "post_ack_read_only_sample"):
            continue
        state = event.get("robot_state") or {}
        timestamp = state.get("body_sample_timestamp_ns")
        if type(timestamp) is int:
            samples.append({"timestamp_ns": timestamp, "x_m": state.get("trunk_x_m"),
                            "y_m": state.get("trunk_y_m"), "kind": event["kind"]})
    samples.sort(key=lambda row: row["timestamp_ns"])
    return samples


def boundary_at(fixture: dict, poses: list[dict], event_ns: int) -> dict | None:
    if type(event_ns) is not int or not poses:
        return None
    before = next((p for p in reversed(poses) if p["timestamp_ns"] <= event_ns), None)
    after = next((p for p in poses if p["timestamp_ns"] >= event_ns), None)
    if before and after:
        gap = after["timestamp_ns"] - before["timestamp_ns"]
        if gap > 100_000_000:
            return None
        fraction = (event_ns - before["timestamp_ns"]) / gap if gap else 0.0
        x = before["x_m"] + fraction * (after["x_m"] - before["x_m"])
        y = before["y_m"] + fraction * (after["y_m"] - before["y_m"])
    else:
        nearest = before or after
        if abs(event_ns - nearest["timestamp_ns"]) > 100_000_000:
            return None
        x, y = nearest["x_m"], nearest["y_m"]
    elapsed = fixture["arm_elapsed_s"] + max(
        0.0, (event_ns - fixture["phase_started_ns"]) / 1e9)
    distance_along = fixture["approach_speed_m_s"] * max(
        0.0, elapsed - fixture["warmup_duration_s"])
    cx = fixture["anchor_x_m"] - distance_along * fixture["axis_x"]
    cy = fixture["anchor_y_m"] - distance_along * fixture["axis_y"]
    distance = math.hypot(cx - x, cy - y)
    return {"distance_m": distance,
            "margin_m": distance - fixture["boundary_center_distance_m"]}


def raw_motion_geometry_audit(events: list[dict], first: dict, origin: dict | None,
                              stopped: int | None, summary: dict, expected: dict) -> tuple[list[str], dict]:
    causes = []
    fixture_rows = [e for e in events if e.get("kind") == "final_fixture_anchor"]
    if len(fixture_rows) != 1:
        return ["missing_or_duplicate_fixture_anchor"], {}
    fixture = fixture_rows[0]
    required_fixture = ("phase_started_ns", "anchor_x_m", "anchor_y_m",
                        "axis_x", "axis_y", "arm_elapsed_s", "approach_speed_m_s",
                        "warmup_duration_s", "boundary_center_distance_m")
    if any(not isinstance(fixture.get(key), (int, float))
           or not math.isfinite(fixture[key]) for key in required_fixture):
        return ["invalid_fixture_anchor"], {}
    if (fixture.get("trial_seed") != expected["seed"]
            or fixture.get("arm_elapsed_s") != expected["arm_elapsed_s"]
            or fixture.get("boundary_center_distance_m") != .25
            or fixture.get("sphere_radius_m") != .07
            or fixture.get("approach_speed_m_s") != .2
            or fixture.get("warmup_duration_s") != .5):
        causes.append("frozen_fixture_mismatch")
    initial = fixture.get("initial_pose") or {}
    if all(isinstance(initial.get(key), (int, float)) for key in
           ("x_m", "y_m", "heading_rad")):
        axis_x, axis_y = math.cos(initial["heading_rad"]), math.sin(initial["heading_rad"])
        distance = .85 + (random.Random(expected["seed"]).random() * 2 - 1) * .01
        if (abs(fixture["axis_x"] - axis_x) > 1e-9
                or abs(fixture["axis_y"] - axis_y) > 1e-9
                or abs(fixture["anchor_x_m"]
                       - (initial["x_m"] + distance * axis_x)) > 1e-9
                or abs(fixture["anchor_y_m"]
                       - (initial["y_m"] + distance * axis_y)) > 1e-9):
            causes.append("raw_anchor_seed_geometry")
    else:
        causes.append("raw_anchor_initial_pose")
    try:
        poses = pose_rows_from_events(events)
        speeds = pose_speeds(poses, window_ms=100, max_window_ms=140)
    except (KeyError, TypeError, ValueError):
        return causes + ["invalid_raw_pose"], {}
    pre = [r for r in speeds if r["kind"] == "precondition_motion"]
    if (len(pre) < 2 or math.hypot(pre[-1]["x_m"] - pre[0]["x_m"],
                                   pre[-1]["y_m"] - pre[0]["y_m"]) < .01
            or first_sustained(pre, threshold_mps=.015, duration_ms=200,
                               at_or_above=True) is None
            or pre[-1]["pose_speed_mps"] is None
            or pre[-1]["pose_speed_mps"] < .015):
        causes.append("raw_moving_precondition")
    call_ns = first.get("transport_call_started_ns")
    ack_ns = first.get("transport_ack_returned_ns")
    origin_ns = (origin or {}).get("dn_timestamp_ns")
    before_neural = [r for r in speeds if type(origin_ns) is int
                     and r["timestamp_ns"] < origin_ns
                     and r["pose_speed_mps"] is not None]
    if (not before_neural or origin_ns - before_neural[-1]["timestamp_ns"] > 100_000_000
            or before_neural[-1]["pose_speed_mps"] < .015):
        causes.append("raw_pre_stop_body_not_moving")
    prior_states = [e["robot_state"] for e in events
                    if e.get("kind") == "control_publish"
                    and e.get("robot_state")
                    and type(e["robot_state"].get("state_sample_timestamp_ns")) is int
                    and type(call_ns) is int
                    and e["robot_state"]["state_sample_timestamp_ns"] <= call_ns]
    prior = max(prior_states, key=lambda s: s["state_sample_timestamp_ns"],
                default=None)
    if (prior is None or call_ns - prior["state_sample_timestamp_ns"] > 100_000_000
            or not isinstance(prior.get("applied_velocity"), list)
            or prior["applied_velocity"][0] < .04
            or any("deadman" in str(reason).lower()
                   for reason in prior.get("limited_by", []))):
        causes.append("raw_pre_stop_applied_vx")
    moves = [e for e in events if e.get("kind") in
             ("precondition_motion", "positive_motion_refresh")]
    last_move = max((e for e in moves if type(e.get("robot_move_ack_at_ns")) is int
                     and type(ack_ns) is int and e["robot_move_ack_at_ns"] < ack_ns),
                    key=lambda e: e["robot_move_ack_at_ns"], default=None)
    deadman = deadman_timing(
        last_move.get("request_call_started_at_ns") if last_move else None,
        last_move.get("robot_move_ack_at_ns") if last_move else None,
        ack_ns, timeout_ms=500, minimum_margin_ms=100)
    if not deadman["valid"]:
        causes.append("raw_deadman_timing")
    state_samples = [e["robot_state"] for e in events
                     if e.get("kind") in ("precondition_motion", "control_publish",
                                           "post_ack_read_only_sample")
                     and e.get("robot_state")]
    if (type(stopped) is not int or any(
            any("deadman" in str(reason).lower() for reason in s.get("limited_by", []))
            for s in state_samples if type(s.get("state_sample_timestamp_ns")) is int
            and s["state_sample_timestamp_ns"] <= stopped)):
        causes.append("raw_deadman_limiter")
    post = [e["robot_state"] for e in events
            if e.get("kind") == "post_ack_read_only_sample" and e.get("robot_state")
            and type(ack_ns) is int and type(stopped) is int
            and ack_ns <= e["robot_state"].get("body_sample_timestamp_ns", -1)
            <= stopped]
    baseline = prior["applied_velocity"][0] if prior and prior.get("applied_velocity") else None
    first_reduction = next((s["state_sample_timestamp_ns"] for s in post
                            if baseline is not None
                            and s.get("applied_velocity", [math.inf])[0] <= baseline * .8), None)
    first_near_zero = next((s["state_sample_timestamp_ns"] for s in post
                            if abs(s.get("applied_velocity", [math.inf])[0]) <= .008), None)
    if (not post or baseline is None
            or first_reduction is None or first_near_zero is None
            or any(s.get("requested_velocity") != [0, 0, 0] for s in post)):
        causes.append("raw_applied_vx_decline_or_zero_twist")
    if (first_reduction != summary.get("first_applied_vx_reduction_at_ns")
            or first_near_zero != summary.get("first_applied_vx_near_zero_at_ns")):
        causes.append("raw_applied_vx_timing_mismatch")
    latch_at = summary.get("motion_arbiter_latch_at_ns")
    if (type(latch_at) is not int or type(origin_ns) is not int
            or type(call_ns) is not int or not origin_ns <= latch_at <= call_ns
            or any(type(e.get("request_call_started_at_ns")) is int
                   and e["request_call_started_at_ns"] > latch_at for e in moves)
            or any(type(e.get("robot_move_ack_at_ns")) is int
                   and type(ack_ns) is int and e["robot_move_ack_at_ns"] > ack_ns
                   for e in moves)):
        causes.append("raw_post_latch_positive_move")
    confirmed = first_sustained(speeds, threshold_mps=.008, duration_ms=200,
                                at_or_above=False, after_ns=ack_ns) if type(ack_ns) is int else None
    if (confirmed is None or confirmed != stopped
            or stopped - ack_ns > 1_000_000_000):
        causes.append("raw_pose_stop_confirmation")
    trigger = boundary_at(fixture, poses, origin_ns)
    request = boundary_at(fixture, poses, call_ns)
    ack_boundary = boundary_at(fixture, poses, ack_ns)
    stop_boundary = boundary_at(fixture, poses, stopped)
    if not trigger or trigger["margin_m"] <= 0 or not request or request["margin_m"] <= 0:
        causes.append("raw_preboundary_trigger_request")
    for name, value in (("decoder_stop", trigger), ("first_stop_request", request),
                        ("stop_ack", ack_boundary), ("stopped_confirmation", stop_boundary)):
        reported = summary.get("boundary_at_" + name)
        if ((value is None) != (reported is None)
                or value is not None and (not isinstance(reported, dict)
                    or abs(value["margin_m"] - reported.get("margin_m", math.inf)) > 1e-6)):
            causes.append("raw_boundary_summary_mismatch_" + name)
    return causes, {"decoder_stop": trigger, "first_stop_request": request,
                    "stop_ack": ack_boundary, "stopped_confirmation": stop_boundary}


def score_attempt(folder: Path, expected: dict) -> dict:
    outcome = {"trial_id": expected["trial_id"], "seed": expected["seed"],
               "arm_elapsed_s": expected["arm_elapsed_s"], "success": False,
               "failure_causes": [], "latencies_ms": {}, "raw_accounted": False,
               "safety_limit_violations": None}
    summary_path = folder / "summary.json"
    if not summary_path.is_file():
        outcome["failure_causes"].append("missing_summary")
        return outcome
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    outcome["safety_limit_violations"] = summary.get("safety_limit_violations")
    if (summary.get("trial_id") != f"p8-02-final-{expected['trial_id']}"
            or summary.get("seed") != expected["seed"]
            or summary.get("arm_elapsed_s") != expected["arm_elapsed_s"]
            or summary.get("schema_version") != "p8-02-final-approach-trial-v1"):
        outcome["failure_causes"].append("trial_identity_mismatch")
        return outcome
    raw = {}
    for name, key in (("events.jsonl", "events_artifact"),
                      ("neural-ledger.jsonl", "neural_ledger_artifact"),
                      ("visual-frames.jsonl", "visual_frame_artifact"),
                      ("trace.jsonl", "trace_artifact")):
        path = folder / name
        artifact = summary.get(key)
        if (not path.is_file() or not isinstance(artifact, dict)
                or Path(artifact.get("path", "")).resolve() != path.resolve()
                or artifact.get("sha256") != sha(path)):
            outcome["failure_causes"].append(f"raw_hash_or_path_{name}")
            return outcome
        raw[name] = rows(path)
        if artifact.get("record_count") != len(raw[name]):
            outcome["failure_causes"].append(f"raw_count_{name}")
            return outcome
    events, neural, visual = (raw[name] for name in
                              ("events.jsonl", "neural-ledger.jsonl", "visual-frames.jsonl"))
    if not events or not neural or len(visual) < 2 or not raw["trace.jsonl"]:
        outcome["failure_causes"].append("empty_raw_ledger")
        return outcome
    outcome["raw_accounted"] = True
    snapshots = [e for e in events if e.get("kind") == "final_safety_snapshot"]
    if len(snapshots) != 1:
        outcome["failure_causes"].append("missing_final_safety_snapshot")
        outcome["raw_accounted"] = False
    else:
        snapshot = snapshots[0]
        if (snapshot.get("fault_stop_latch") is not None
                or snapshot.get("scheduler_exceptions") != 0
                or snapshot.get("deadman_limiter_seen_before_stopped") is not False
                or snapshot.get("fault_stop_latch") != summary.get("fault_stop_latch")
                or snapshot.get("arbiter_latch_reason") != summary.get("motion_arbiter_latch_reason")
                or snapshot.get("arbiter_latch_at_ns") != summary.get("motion_arbiter_latch_at_ns")
                or snapshot.get("scheduler_exceptions") != summary.get("scheduler_exceptions")):
            outcome["failure_causes"].append("raw_fault_or_scheduler_snapshot")
    def unsafe_velocity(values: list[float]) -> bool:
        return (len(values) != 3 or any(not isinstance(v, (int, float))
                or not math.isfinite(v) for v in values)
                or abs(values[0]) > .08 or values[1] != 0 or abs(values[2]) > .5)
    raw_safety_count = sum(
        unsafe_velocity([r.get("robot_facing_vx"), r.get("robot_facing_vy"),
                         r.get("robot_facing_vyaw")]) for r in raw["trace.jsonl"])
    raw_safety_count += sum(
        unsafe_velocity(e.get("robot_state", {}).get("requested_velocity", []))
        or any(not isinstance(v, (int, float)) or not math.isfinite(v)
               for v in e.get("robot_state", {}).get("applied_velocity", []))
        for e in events if e.get("kind") in
        ("precondition_motion", "post_ack_read_only_sample"))
    if raw_safety_count != summary.get("safety_limit_violations"):
        outcome["failure_causes"].append("raw_safety_count_mismatch")
    if snapshots and snapshots[0].get("safety_limit_violations") != raw_safety_count:
        outcome["failure_causes"].append("raw_safety_snapshot_mismatch")
    outcome["safety_limit_violations"] = raw_safety_count
    if any(r.get("input_none") or r.get("result_none") or not r.get("perception_valid")
           or not isinstance(r.get("perception_age_ms"), (int, float))
           or not 0 <= r["perception_age_ms"] <= 100
           or r.get("male_cns_healthy") is not True
           or r.get("dn_runtime_healthy") is not True for r in neural):
        outcome["failure_causes"].append("missing_invalid_or_stale_neural_visual_input")
    if any(not r.get("perception_valid") for r in visual):
        outcome["failure_causes"].append("invalid_rgb")
    frame_times = [r["timestamp_ns"] for r in visual]
    if any(not 0 < (b - a) / 1e6 <= 100 for a, b in zip(frame_times, frame_times[1:])):
        outcome["failure_causes"].append("rgb_frame_gap")
    stop_events = [r for r in events if r.get("kind") == "control_publish"
                   and r.get("transport_action") == "robot_stop_refreshed"]
    if not stop_events:
        outcome["failure_causes"].append("no_authentic_stop_ack")
        return outcome
    first = stop_events[0]
    trace = first.get("neural_trace") or {}
    latch = summary.get("healthy_neural_stop_latch") or {}
    origin = next((r for r in neural
                   if r.get("runtime_step") == latch.get("graph_runtime_step")
                   and r.get("dn_sequence") == latch.get("neural_sequence")
                   and r.get("dn_timestamp_ns") == latch.get("neural_timestamp_ns")), None)
    if (origin is None or origin.get("dn_escape", 0) < .5
            or origin.get("raw_decoder_stop") is not True
            or origin.get("post_safety_stop") is not True
            or origin.get("dn_runtime_healthy") is not True
            or origin.get("male_cns_healthy") is not True
            or latch.get("source") != "healthy_neural_escape"
            or latch.get("first_healthy_stop_ack_ns") != first.get("transport_ack_returned_ns")
            or trace.get("neural_stop_latch", {}).get("source") != "healthy_neural_escape"
            or not trace.get("pre_safety_intent", {}).get("stop")
            or not trace.get("safety_result", {}).get("intent", {}).get("stop")):
        outcome["failure_causes"].append("raw_neural_stop_origin")
    if origin is not None:
        source_record = {
            "dn_activity": {"sequence": origin.get("dn_sequence"),
                            "timestamp_ns": origin.get("dn_timestamp_ns"),
                            "escape": origin.get("dn_escape")},
            "male_cns": {"runtime_step": origin.get("runtime_step")},
            "identities": {"graph_identity": origin.get("graph_identity")},
        }
        lineage = bounded_neural_lineage(
            neural, source_record, max_age_ms=100, max_runtime_step_gap=5)
        outcome["raw_lineage"] = lineage
        if not lineage["valid"]:
            outcome["failure_causes"].append("raw_neural_visual_lineage")
    if (not first.get("neural_trace") or first.get("watchdog_state") != "healthy"
            or not first.get("robot_facing_stop")
            or first.get("transport_ack_returned_ns") != summary.get("robot_stop_rpc_ack_returned_ns")):
        outcome["failure_causes"].append("first_stop_causal_provenance")
    stopped = summary.get("stopped_confirmed_at_ns")
    ack_times = [first["transport_ack_returned_ns"]] + [
        r["ack_at_ns"] for r in events if r.get("kind") == "stop_refresh_ack"
        and type(r.get("ack_at_ns")) is int
        and r["ack_at_ns"] > first["transport_ack_returned_ns"]
        and type(stopped) is int and r["ack_at_ns"] <= stopped]
    ack_times.sort()
    tail_ms = ((stopped - ack_times[-1]) / 1e6
               if type(stopped) is int and ack_times else None)
    if (len(ack_times) < 2 or tail_ms is None
            or any(not 0 < (b-a)/1e6 <= 100 for a, b in zip(ack_times, ack_times[1:]))
            or not 0 <= tail_ms <= 100):
        outcome["failure_causes"].append("stop_ack_refresh_or_tail")
    outcome["stop_ack_times_through_confirmation_ns"] = ack_times
    outcome["stop_ack_tail_to_confirmation_ms"] = tail_ms
    raw_looming = next((e["neural_trace"]["perception_frame"]["timestamp_ns"]
                        for e in events if e.get("kind") == "control_publish"
                        and e.get("neural_trace", {}).get("perception_frame", {}).get("looming", 0) > 0), None)
    raw_lplc2 = next((e["neural_trace"]["dn_readout"]["timestamp_ns"]
                      for e in events if e.get("kind") == "control_publish"
                      and max(e.get("neural_trace", {}).get("stimulus_channels", {}).get("lplc2_left", 0),
                              e.get("neural_trace", {}).get("stimulus_channels", {}).get("lplc2_right", 0)) > 0), None)
    raw_threshold = next((r["dn_timestamp_ns"] for r in neural
                          if r.get("dn_escape", 0) >= .5), None)
    raw_request = first.get("transport_call_started_ns")
    raw_ack = first.get("transport_ack_returned_ns")
    ordered_raw = (origin is not None
                   and all(isinstance(t, int) for t in
                           (raw_looming, raw_lplc2, raw_threshold,
                            raw_request, raw_ack, stopped))
                   and raw_looming <= raw_lplc2 <= raw_threshold <=
                   origin["dn_timestamp_ns"] <= raw_request <= raw_ack <= stopped)
    if (raw_looming != summary.get("looming_first_nonzero_at_ns")
            or raw_lplc2 != summary.get("lplc2_first_nonzero_at_ns")
            or raw_threshold != summary.get("dn_escape_threshold_crossed_at_ns")
            or (origin or {}).get("dn_timestamp_ns") != summary.get("decoder_stop_created_at_ns")
            or raw_request != summary.get("robot_stop_rpc_call_started_ns")
            or raw_ack != summary.get("robot_stop_rpc_ack_returned_ns")
            or not ordered_raw):
        outcome["failure_causes"].append("raw_causal_timeline")
    if any(r.get("kind") == "positive_motion_refresh"
           and r.get("timestamp_ns", 0) > first["transport_ack_returned_ns"] for r in events):
        outcome["failure_causes"].append("post_stop_positive_move")
    if any(e.get("kind") in ("fixture_error", "safe_abort_stop",
                             "cleanup_stop_after_complete", "cleanup_error")
           and type(stopped) is int and e.get("timestamp_ns", math.inf) <= stopped
           for e in events):
        outcome["failure_causes"].append("raw_fixture_or_cleanup_confound")
    if any(e.get("kind") == "control_publish"
           and e.get("transport_ack_returned_ns") is not None
           and type(stopped) is int and e.get("timestamp_ns", math.inf) <= stopped
           and e.get("watchdog_state") != "healthy" for e in events):
        outcome["failure_causes"].append("raw_watchdog_fault_confound")
    if any(e.get("kind") == "control_publish"
           and type(e.get("transport_ack_returned_ns")) is int
           and e["transport_ack_returned_ns"] > first["transport_ack_returned_ns"]
           and type(stopped) is int and e["transport_ack_returned_ns"] <= stopped
           and e.get("transport_action") != "robot_stop_refreshed" for e in events):
        outcome["failure_causes"].append("raw_post_stop_move_transport")
    transitions = [e.get("state") for e in events if e.get("kind") == "transition"]
    if not valid_state_path(transitions, complete=True):
        outcome["failure_causes"].append("raw_state_path_incomplete")
    checks = summary.get("checks", {})
    if not checks or not all(checks.values()):
        outcome["failure_causes"].extend(k for k, v in checks.items() if not v)
    if summary.get("r3_official_screen_result") != "PASS":
        outcome["failure_causes"].append("causal_primary_screen")
    for key in ("boundary_at_decoder_stop", "boundary_at_first_stop_request"):
        if not isinstance(summary.get(key), dict) or summary[key].get("margin_m", 0) <= 0:
            outcome["failure_causes"].append(key)
    if (summary.get("fault_stop_latch") is not None
            or summary.get("scheduler_exceptions") != 0
            or summary.get("safety_limit_violations") != 0
            or summary.get("deadman_limiter_seen_before_stopped") is not False
            or summary.get("positive_move_after_latch_count") != 0
            or summary.get("positive_move_ack_after_first_stop_ack_count") != 0):
        outcome["failure_causes"].append("fault_safety_or_deadman_confound")
    motion_causes, raw_boundaries = raw_motion_geometry_audit(
        events, first, origin, stopped, summary, expected)
    outcome["failure_causes"].extend(motion_causes)
    if any(cause in motion_causes for cause in
           ("missing_or_duplicate_fixture_anchor", "invalid_fixture_anchor",
            "invalid_raw_pose")):
        outcome["raw_accounted"] = False
    if raw_boundaries:
        fixture = next(e for e in events if e.get("kind") == "final_fixture_anchor")
        poses = pose_rows_from_events(events)
        for name, timestamp in (("first_looming", raw_looming),
                                ("first_lplc2", raw_lplc2),
                                ("first_dn_escape", raw_threshold)):
            value = boundary_at(fixture, poses, timestamp)
            raw_boundaries[name] = value
            reported = summary.get("boundary_at_" + name)
            if ((value is None) != (reported is None)
                    or value is not None and (not isinstance(reported, dict)
                        or abs(value["margin_m"] - reported.get("margin_m", math.inf)) > 1e-6)):
                outcome["failure_causes"].append("raw_boundary_summary_mismatch_" + name)
    points = {
        "looming": raw_looming,
        "neural_stop": (origin or {}).get("dn_timestamp_ns"),
        "request": raw_request,
        "ack": raw_ack,
        "stopped": stopped,
    }
    if not all(isinstance(value, int) for value in points.values()) or list(points.values()) != sorted(points.values()):
        outcome["failure_causes"].append("causal_timeline")
    else:
        for name, a, b in (("looming_to_neural_stop", "looming", "neural_stop"),
                           ("neural_stop_to_request", "neural_stop", "request"),
                           ("neural_stop_to_ack", "neural_stop", "ack"),
                           ("ack_to_stopped", "ack", "stopped"),
                           ("looming_to_stopped", "looming", "stopped")):
            outcome["latencies_ms"][name] = (points[b] - points[a]) / 1e6
    outcome["margins_m"] = {key: (value or {}).get("margin_m")
                            for key, value in raw_boundaries.items()}
    outcome["minimum_surface_clearance_m"] = min(
        (r["sphere_surface_clearance_m"] for r in events
         if r.get("kind") == "virtual_geometry"), default=None)
    outcome["failure_causes"] = sorted(set(outcome["failure_causes"]))
    outcome["success"] = not outcome["failure_causes"]
    return outcome


def score_batch(root: Path, protocol: dict) -> dict:
    planned = protocol["batches"]["P8-02"]["runs"]
    if ([r["trial_id"] for r in planned] != [f"A{i:02d}" for i in range(20)]
            or [r["seed"] for r in planned] != list(range(880000, 880020))):
        raise ValueError("P8-02 final matrix differs from preregistration")
    attempts = []
    for row in planned:
        try:
            attempts.append(score_attempt(root / row["trial_id"], row))
        except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
            attempts.append({"trial_id": row["trial_id"], "seed": row["seed"],
                             "arm_elapsed_s": row["arm_elapsed_s"], "success": False,
                             "raw_accounted": False, "safety_limit_violations": None,
                             "latencies_ms": {}, "failure_causes": [
                                 f"raw_extract_exception:{type(error).__name__}:{error}"]})
    success = sum(r["success"] for r in attempts)
    latencies = {name: timing([r["latencies_ms"][name] for r in attempts
                               if name in r["latencies_ms"]])
                 for name in ("looming_to_neural_stop", "neural_stop_to_request",
                              "neural_stop_to_ack", "ack_to_stopped", "looming_to_stopped")}
    confirmed = sum((r.get("margins_m", {}).get("stopped_confirmation") or -1) > 0
                    for r in attempts)
    fully_accounted = all(r["raw_accounted"] for r in attempts)
    zero_safety_violations = all(r["safety_limit_violations"] == 0 for r in attempts)
    return {"schema_version": "p8-02-final-approach-score-v1", "planned": 20,
            "successes": success, "success_rate": success / 20,
            "all_raw_accounted": fully_accounted,
            "zero_safety_limit_violations": zero_safety_violations,
            "wilson_95_ci": wilson(success, 20),
            "confirmed_preboundary_stops": confirmed,
            "confirmed_preboundary_wilson_95_ci": wilson(confirmed, 20),
            "latencies": latencies, "trials": attempts,
            "result": "PASS" if success >= 19 and fully_accounted
                      and zero_safety_violations else "FAIL"}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw-root", type=Path, required=True)
    ap.add_argument("--protocol", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    score = score_batch(args.raw_root, json.loads(args.protocol.read_text()))
    args.output.write_text(json.dumps(score, sort_keys=True, indent=2, allow_nan=False) + "\n",
                           encoding="utf-8", newline="\n")
    print(json.dumps({"result": score["result"], "successes": score["successes"]}))
    if score["result"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
