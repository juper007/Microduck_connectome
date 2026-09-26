"""Regenerate the P8-02 fixed-denominator score from retained trial ledgers."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from statistics import median


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
    outcome["safety_limit_violations"] = raw_safety_count
    if any(r.get("input_none") or r.get("result_none") or not r.get("perception_valid")
           or not isinstance(r.get("perception_age_ms"), (int, float))
           or not 0 <= r["perception_age_ms"] <= 100 for r in neural):
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
    if (not first.get("neural_trace") or first.get("watchdog_state") != "healthy"
            or not first.get("robot_facing_stop")
            or first.get("transport_ack_returned_ns") != summary.get("robot_stop_rpc_ack_returned_ns")):
        outcome["failure_causes"].append("first_stop_causal_provenance")
    ack_times = [first["transport_ack_returned_ns"]] + [
        r["ack_at_ns"] for r in events if r.get("kind") == "stop_refresh_ack"
        and r["ack_at_ns"] > first["transport_ack_returned_ns"]]
    ack_times = sorted(set(ack_times))
    stopped = summary.get("stopped_confirmed_at_ns")
    if (len(ack_times) < 2 or stopped is None
            or any((b-a)/1e6 > 100 for a, b in zip(ack_times, ack_times[1:]))
            or (stopped-ack_times[-1])/1e6 > 100):
        outcome["failure_causes"].append("stop_ack_refresh_or_tail")
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
    outcome["margins_m"] = {key: (summary.get("boundary_at_" + key) or {}).get("margin_m")
                            for key in ("first_looming", "first_lplc2", "first_dn_escape",
                                        "decoder_stop", "first_stop_request", "stop_ack",
                                        "stopped_confirmation")}
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
    attempts = [score_attempt(root / r["trial_id"], r) for r in planned]
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
