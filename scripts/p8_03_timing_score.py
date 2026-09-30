"""Offline, fail-closed scorer for the three development-only P8-03 timing probes."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from microduck_connectome.fractional_rgb_v21 import render_fractional_pixels
from microduck_connectome.control_contracts import (ControlContractError,
                                                    validate_behavior_intent)
from microduck_connectome.g8_r5d_metrics import first_sustained, pose_speeds
from microduck_connectome.looming_scenario import load_config, pixels_sha256
from microduck_connectome.p8_03_geometry import relative_trial
from microduck_connectome.p8_03_causal_timing import (
    CausalTimingError, evaluate_causal_arm)
from scripts.p8_03_local_reference import body_pose


PERIOD_NS = 20_000_000
VISUAL_PERIOD_NS = 50_000_000
WINDOW_NS = 1_000_000_000
PROBE_IDS = {"p8-03-timing-probe-v1": ("TPR2-001", "TPR2-002", "TPR2-003"),
             "p8-03-timing-probe-v2": ("TPR2A-001", "TPR2A-002", "TPR2A-003"),
             "p8-03-timing-probe-v3": ("CTP3-001", "CTP3-002", "CTP3-003")}
ROOT = Path(__file__).resolve().parents[1]


def _read_jsonl(path: Path) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    if not all(type(row) is dict for row in rows):
        raise ValueError(f"non-object JSONL record: {path.name}")
    return rows


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _number(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def _distribution_ns(values: list[int]) -> dict:
    ms = [value / 1e6 for value in values]
    return {"p50_ms": _percentile(ms, .5), "p95_ms": _percentile(ms, .95),
            "p99_ms": _percentile(ms, .99), "max_ms": max(ms, default=None)}


def _stream(rows: list[dict], start: int, end: int) -> dict:
    times = sorted(row["timestamp_ns"] for row in rows
                   if type(row.get("timestamp_ns")) is int
                   and start <= row["timestamp_ns"] < end)
    return {"count": len(times), "first_ns": times[0] if times else None,
            "last_ns": times[-1] if times else None,
            "max_gap_ms": max(((b - a) / 1e6 for a, b in zip(times, times[1:])),
                              default=None)}


def _slots(rows: list[dict], *, domain: str, arm_ns: int, count: int,
           period_ns: int, errors: list[str]) -> list[dict]:
    selected = [row for row in rows if row.get("kind") == "scheduled_tick"
                and row.get("domain") == domain]
    by_slot = {}
    for row in selected:
        slot = row.get("slot")
        if type(slot) is not int or slot in by_slot:
            errors.append(f"{domain}_slot_duplicate_or_invalid")
        else:
            by_slot[slot] = row
    if set(by_slot) != set(range(count)):
        errors.append(f"{domain}_slots_incomplete")
    ordered = []
    for slot in range(count):
        row = by_slot.get(slot)
        if row is None:
            continue
        deadline = arm_ns + slot * period_ns
        wake = row.get("worker_wake_ns")
        step_start = row.get("step_start_ns")
        complete = row.get("tick_complete_ns")
        if (row.get("scheduled_deadline_ns") != deadline or
                type(wake) is not int or type(step_start) is not int or
                type(complete) is not int or
                type(row.get("thread_id")) is not int or
                not deadline <= wake <= step_start <= complete < deadline + period_ns or
                row.get("late_or_overrun") is not False):
            errors.append(f"{domain}_slot_{slot}_timing_invalid")
        ordered.append(row)
    return ordered


def _motion_request_accounting(journal: list[dict], timing: list[dict]) -> list[str]:
    """Require a durable terminal and a timing-ledger row for every v2 attempt."""
    errors = []
    starts = [row for row in journal if row.get("kind") == "motion_request_start"]
    ends = [row for row in journal if row.get("kind") == "motion_request_end"]
    attempts = [row for row in timing if row.get("kind") == "motion_attempt"]
    refreshes = [row for row in timing if row.get("kind") == "motion_refresh"]
    if (len(starts) != len(ends) or len(ends) != len(attempts) or
            len(journal) != len(starts) + len(ends)):
        return ["motion_request_terminal_or_attempt_missing"]
    keys = lambda rows: [(row.get("phase"), row.get("period_index"),
                          row.get("scored_slot")) for row in rows]
    start_keys, end_keys, attempt_keys = keys(starts), keys(ends), keys(attempts)
    if (len(set(start_keys)) != len(starts) or start_keys != end_keys or
            start_keys != attempt_keys):
        errors.append("motion_request_identity_invalid")
    common = ("period_index", "scored_slot", "phase", "scheduled_deadline_ns",
              "next_deadline_ns", "worker_wake_ns", "thread_id",
              "previous_slot_completion_ns", "state_queue_depth", "pose_queue_depth",
              "request_id", "outstanding_before")
    statuses = {"acknowledged", "late_ack", "exception", "arm_race",
                "cancelled_at_arm"}
    for start, end, attempt in zip(starts, ends, attempts):
        if (any(start.get(key) != end.get(key) or end.get(key) != attempt.get(key)
                for key in common) or
                {key: value for key, value in end.items() if key != "kind"} !=
                {key: value for key, value in attempt.items() if key != "kind"} or
                type(start.get("period_index")) is not int or
                start.get("phase") not in ("prearm", "scored", "postscore") or
                type(start.get("thread_id")) is not int or
                type(start.get("request_id")) is not int or
                start.get("outstanding_before") != 0 or
                start.get("next_deadline_ns") !=
                start.get("scheduled_deadline_ns", -1) + PERIOD_NS or
                not (type(start.get("worker_wake_ns")) is int and
                     start.get("timestamp_ns") == start["worker_wake_ns"] and
                     start["scheduled_deadline_ns"] <= start["worker_wake_ns"] <
                     start["next_deadline_ns"] and
                     type(end.get("timestamp_ns")) is int and
                     end["timestamp_ns"] >= start["worker_wake_ns"])):
            errors.append("motion_request_row_invalid")
            break
        if (end.get("status") not in statuses or
                type(end.get("lock_wait_start_ns")) is not int or
                type(end.get("command_lock_acquired_ns")) is not int or
                not start["worker_wake_ns"] <= end["lock_wait_start_ns"] <=
                end["command_lock_acquired_ns"] <= end["timestamp_ns"]):
            errors.append("motion_request_status_or_lock_invalid")
            break
        status = end["status"]
        if status in ("acknowledged", "late_ack"):
            ordered = ("command_lock_acquired_ns", "pre_send_ns",
                       "socket_write_start_ns", "socket_write_end_ns", "flush_end_ns",
                       "response_wait_start_ns", "first_response_byte_ns",
                       "parse_complete_ns", "ack_ns", "timestamp_ns")
            values = [end.get(key) for key in ordered]
            if (not all(type(value) is int for value in values) or
                    values != sorted(values) or
                    end.get("first_response_byte_observable") is not True or
                    (status == "acknowledged") !=
                    (end["ack_ns"] < end["next_deadline_ns"])):
                errors.append("motion_request_ack_trace_invalid")
                break
        if status == "acknowledged":
            matching = [row for row in refreshes if
                        row.get("phase") == start["phase"] and
                        row.get("period_index") == start["period_index"] and
                        row.get("scored_slot") == start["scored_slot"]]
            if (len(matching) != 1 or
                    matching[0].get("move_ack_ns") != end.get("ack_ns") or
                    matching[0].get("scheduled_deadline_ns") !=
                    start["scheduled_deadline_ns"]):
                errors.append("motion_request_refresh_mismatch")
                break
        elif any(row.get("phase") == start["phase"] and
                 row.get("period_index") == start["period_index"] and
                 row.get("scored_slot") == start["scored_slot"] for row in refreshes):
            errors.append("motion_request_failed_refresh_present")
            break
        if status in ("late_ack", "exception", "arm_race") and not end.get("failure_reason"):
            errors.append("motion_request_failure_reason_missing")
            break
        if status in ("late_ack", "exception", "arm_race"):
            errors.append("motion_request_failed_attempt")
    if len(refreshes) != sum(row.get("status") == "acknowledged" for row in ends):
        errors.append("motion_request_refresh_count_mismatch")
    return errors


def _score_trial(folder: Path, spec: dict, config: dict) -> dict:
    ident = spec["reset_id"]
    errors: list[str] = []
    result = {"reset_id": ident, "result": "FAIL", "failure_causes": errors}
    names = {"events": "events.jsonl", "neural": "neural-ledger.jsonl",
              "visual": "visual-frames.jsonl", "timing": "timing-ledger.jsonl"}
    v3 = config.get("schema_version") == "p8-03-timing-probe-v3"
    v2 = config.get("schema_version") in ("p8-03-timing-probe-v2",
                                          "p8-03-timing-probe-v3")
    try:
        rows = {name: _read_jsonl(folder / filename) for name, filename in names.items()}
        summary = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
        reference = json.loads((folder / "local-reference.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        errors.append(f"raw_unreadable:{type(error).__name__}")
        return result
    result["primary_fixture_errors"] = summary.get("fixture_errors")
    raw_fixture_errors = [row.get("error") for row in rows["events"]
                          if row.get("kind") in ("fixture_error", "scheduler_exception")]
    if summary.get("fixture_errors") != raw_fixture_errors:
        errors.append("fixture_error_summary_mismatch")
    if v2:
        journal_path = folder / "motion-request-journal.jsonl"
        lifecycle = summary.get("motion_journal")
        coordinator_reached = summary.get("motion_coordinator_reached")
        if journal_path.is_file():
            result["motion_journal_lifecycle"] = "PRESENT"
            if (type(lifecycle) is not dict or lifecycle.get("present") is not True or
                    lifecycle.get("sha256") != _sha(journal_path) or
                    lifecycle.get("lifecycle") != "PRESENT" or
                    summary.get("motion_request_journal_sha256") != _sha(journal_path)):
                errors.append("motion_journal_lifecycle_or_hash_invalid")
            try:
                rows["motion_request"] = _read_jsonl(journal_path)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                errors.append("motion_request_journal_unreadable")
            else:
                errors.extend(_motion_request_accounting(rows["motion_request"], rows["timing"]))
        else:
            coordinator_rows = [row for row in rows["timing"] if row.get("kind") in
                                ("motion_attempt", "motion_refresh", "state_observation",
                                 "pose_observation", "motion_fault", "motion_arm")]
            optional = (coordinator_reached is False and
                        summary.get("armed") is False and
                        type(lifecycle) is dict and lifecycle == {
                            "present": False, "sha256": None,
                            "reason": "not_created_before_precondition_failure",
                            "lifecycle": "OPTIONAL_NOT_REACHED_ARTIFACT"} and
                        summary.get("motion_request_journal_sha256") is None and
                        not coordinator_rows and
                        not any(row.get("kind") == "arm" for row in rows["events"]) and
                        bool(raw_fixture_errors) and
                        summary.get("fixture_errors") == raw_fixture_errors)
            result["motion_journal_lifecycle"] = (
                "OPTIONAL_NOT_REACHED_ARTIFACT" if optional else
                "REQUIRED_BUT_MISSING_ARTIFACT")
            if not optional:
                errors.append("motion_request_journal_required_missing")
    for name, filename in names.items():
        key = {"events": "event_sha256", "neural": "neural_ledger_sha256",
                "visual": "visual_sha256", "timing": "timing_ledger_sha256",
                "motion_request": "motion_request_journal_sha256"}[name]
        if summary.get(key) != _sha(folder / filename):
            errors.append(f"{name}_summary_hash_mismatch")
    if summary.get("armed") is False and not any(
            row.get("kind") == "arm" for row in rows["events"]):
        errors.append("prearm_not_armed")
        return result
    try:
        marker = json.loads((folder / "armed.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        errors.append(f"raw_unreadable:{type(error).__name__}")
        return result
    if (summary.get("reset_id") != ident or summary.get("armed") is not True or
            summary.get("scheduler_exceptions") != 0 or
            summary.get("safety_limit_violations") != 0 or
            summary.get("fixture_errors") != [] or
            reference.get("result") != "PASS" or reference.get("reset_id") != ident):
        errors.append("summary_reference_or_safety_invalid")
    arms = [row for row in rows["events"] if row.get("kind") == "arm"]
    if (len(arms) != 1 or arms[0].get("reset_id") != ident or
            arms[0].get("ordinal") != spec["ordinal"] or
            type(arms[0].get("timestamp_ns")) is not int):
        errors.append("arm_identity_or_count_invalid")
        return result
    arm = arms[0]
    start = arm["timestamp_ns"]
    end = start + WINDOW_NS
    result["arm_ns"] = start
    anchors = [row for row in rows["events"] if row.get("kind") == "timing_arm_anchor"]
    if (len(anchors) != 1 or anchors[0].get("timestamp_ns") != start or
            type(anchors[0].get("pose_source_ns")) is not int or
            not 0 <= start - anchors[0]["pose_source_ns"] <=
            config["freshness_ttl_ms"] * 1e6 or
            not any(row.get("kind") == "pose_observation" and
                    row.get("source_timestamp_ns") == anchors[0]["pose_source_ns"] and
                    row.get("value", {}).get("pose") == anchors[0].get("pose")
                    for row in rows["timing"])):
        errors.append("arm_geometry_anchor_invalid")
    prearm_pose = [row for row in rows["timing"]
                   if row.get("kind") == "pose_observation" and
                   type(row.get("source_timestamp_ns")) is int and
                   start - 400_000_000 <= row["source_timestamp_ns"] < start]
    try:
        for row in prearm_pose:
            value = row["value"]
            pose = value["pose"]
            raw_pose = body_pose(json.loads(value["raw_body_packet"]))
            if (any(abs(raw_pose[key] - pose[key]) > 1e-10
                    for key in ("x_m", "y_m", "trunk_z_m", "heading_rad")) or
                    type(value["request_ns"]) is not int or
                    not 0 <= row["source_timestamp_ns"] - value["request_ns"] <=
                    config["moving_gate"]["maximum_pose_age_ms"] * 1e6 or
                    type(row.get("move_ack_ns")) is not int or
                    row["move_ack_ns"] > row["source_timestamp_ns"]):
                raise ValueError("prearm raw pose lineage invalid")
        samples = [{"timestamp_ns": row["source_timestamp_ns"],
                    "x_m": row["value"]["pose"]["x_m"],
                    "y_m": row["value"]["pose"]["y_m"]}
                   for row in prearm_pose]
        speeds_before_arm = pose_speeds(samples, window_ms=100, max_window_ms=140)
        confirmed_before_arm = first_sustained(
            speeds_before_arm,
            threshold_mps=config["moving_gate"]["minimum_pose_speed_mps"],
            duration_ms=200, at_or_above=True)
        if (len(samples) < 12 or confirmed_before_arm is None or
                start - confirmed_before_arm > 100_000_000 or
                start - samples[-1]["timestamp_ns"] > 100_000_000 or
                len(anchors) != 1 or
                anchors[0].get("pose_source_ns") != samples[-1]["timestamp_ns"] or
                type(anchors[0].get("moving_confirmed_ns")) is not int or
                abs(anchors[0]["moving_confirmed_ns"] - confirmed_before_arm) >
                40_000_000 or
                any(row["pose_speed_mps"] is None or
                    row["pose_speed_mps"] < config["moving_gate"]["minimum_pose_speed_mps"]
                    for row in speeds_before_arm[-2:])):
            errors.append("arm_body_motion_not_confirmed")
    except (KeyError, TypeError, ValueError, IndexError):
        errors.append("arm_body_motion_not_confirmed")
    if (marker.get("state") != "ARMED" or marker.get("reset_id") != ident or
            type(marker.get("armed_at_monotonic_ns")) is not int or
            marker["armed_at_monotonic_ns"] > start or
            marker.get("source_head") != summary.get("source_head") or
            marker.get("reference_sha256") != summary.get("reference_sha256") or
            summary.get("reference_sha256") != _sha(folder / "local-reference.json")):
        errors.append("durable_arm_or_reference_invalid")
    complete = [row for row in rows["events"] if row.get("kind") == "window_complete"]
    if len(complete) != 1 or not _number(complete[0].get("timestamp_ns")) or complete[0]["timestamp_ns"] < end:
        errors.append("scored_window_incomplete")
    before = [row for row in rows["events"] if row.get("kind") == "robotd_health_before"]
    after = [row for row in rows["events"] if row.get("kind") == "robotd_health_after"]
    if (len(before) != 1 or before[0].get("healthy") is not True or
            len(after) != 1 or after[0].get("healthy") is not True):
        errors.append("robotd_health_invalid")
    prehealth = [row for row in rows["events"] if row.get("kind") == "prearm_health"
                 and row.get("after_ready") is True]
    if (len(prehealth) != 1 or type(prehealth[0].get("timestamp_ns")) is not int or
            not 0 <= start - prehealth[0]["timestamp_ns"] <=
            config["settled_gate"]["max_prearm_health_age_ms"] * 1e6 or
            prehealth[0].get("health", {}).get("healthy") is not True):
        errors.append("prearm_health_invalid")
    if (not _number(arm.get("precondition_displacement_m")) or
            arm["precondition_displacement_m"] < config["moving_gate"]["minimum_trunk_displacement_m"] or
            not _number(arm.get("precondition_applied_vx_mps")) or
            arm["precondition_applied_vx_mps"] < config["moving_gate"]["minimum_fresh_applied_vx_mps"] or
            type(arm.get("moving_confirmed_ns")) is not int or
            arm["moving_confirmed_ns"] >= start):
        errors.append("moving_precondition_invalid")
    precondition = [row for row in rows["events"] if row.get("kind") == "precondition_motion"
                    and type(row.get("timestamp_ns")) is int and row["timestamp_ns"] < start]
    expected_precondition = round(config["moving_gate"]["duration_s"] * 1000 /
                                  config["moving_gate"]["command_period_ms"])
    if v3:
        diagnostic_path = folder / "diagnostic.jsonl"
        causal_path = folder / "causal-precondition.json"
        if (not diagnostic_path.is_file() or not causal_path.is_file() or
                summary.get("diagnostic_sha256") != _sha(diagnostic_path) or
                summary.get("causal_precondition_sha256") != _sha(causal_path) or
                type(summary.get("pre_move_tick")) is not int or
                len(precondition) < 91 or
                len({row.get("timestamp_ns") for row in precondition}) != len(precondition)):
            errors.append("causal_raw_evidence_missing_or_invalid")
        else:
            try:
                saved = json.loads(causal_path.read_text())
                all_poses = [
                    {"timestamp_ns": row["source_timestamp_ns"],
                     "request_ns": row["value"]["request_ns"],
                     "x_m": row["value"]["pose"]["x_m"],
                     "y_m": row["value"]["pose"]["y_m"],
                     "raw_body_packet": row["value"]["raw_body_packet"]}
                    for row in rows["timing"] if row.get("kind") == "pose_observation"]
                prearm_proof = evaluate_causal_arm(
                    diagnostic_path, all_poses,
                    pre_move_tick=summary["pre_move_tick"],
                    arm_ns=saved["arm_ns"], gate=config["moving_gate"])
                final_proof = evaluate_causal_arm(
                    diagnostic_path, all_poses,
                    pre_move_tick=summary["pre_move_tick"],
                    arm_ns=start, gate=config["moving_gate"],
                    scored_end_ns=end)
                if (saved != prearm_proof or
                        final_proof["first_causal_tick"] != saved["first_causal_tick"] or
                        final_proof["first_qualifying_tick"] != saved["first_qualifying_tick"] or
                        not saved["arm_ns"] < start):
                    raise CausalTimingError("causal pre-arm proof changed or mismatched")
                result["causal_precondition"] = final_proof
            except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
                errors.append(f"causal_precondition_invalid:{type(error).__name__}")
    elif len(precondition) != expected_precondition:
        errors.append("precondition_raw_count_invalid")
    else:
        try:
            raw_displacement = math.hypot(
                precondition[-1]["pose"]["x_m"] - precondition[0]["pose"]["x_m"],
                precondition[-1]["pose"]["y_m"] - precondition[0]["pose"]["y_m"])
            if (any(row.get("robot_move_ack") is None or
                    not 0 <= row["state_ns"] - row["timestamp_ns"] <=
                    config["moving_gate"]["maximum_state_age_ms"] * 1e6 or
                    not 0 <= row["pose_ns"] - row["state_ns"] <=
                    config["moving_gate"]["maximum_pose_age_ms"] * 1e6 or
                    row["applied_velocity"][0] < 0 or
                    any("deadman" in str(reason).lower() for reason in row.get("limited_by", []))
                    for row in precondition) or
                    not math.isclose(raw_displacement, arm["precondition_displacement_m"],
                                     rel_tol=0, abs_tol=1e-10) or
                    precondition[-1]["applied_velocity"][0] !=
                    arm["precondition_applied_vx_mps"]):
                raise ValueError("raw precondition mismatch")
        except (KeyError, TypeError, ValueError, IndexError):
            errors.append("precondition_raw_invalid")
    if any(row.get("kind") in ("scheduler_exception", "fixture_error", "fault", "motion_fault")
           for row in rows["events"] + rows["timing"]):
        errors.append("fault_or_exception")
    safety = [row for row in rows["events"] if row.get("kind") == "safety_snapshot"]
    if len(safety) != 1 or safety[0].get("violations") != 0:
        errors.append("safety_snapshot_invalid")
    scheduler_summary = safety[0].get("scheduler_result") if len(safety) == 1 else None
    if (not isinstance(scheduler_summary, dict) or
            scheduler_summary.get("dropped_neural") != 0 or
            scheduler_summary.get("scheduler_exceptions") != 0 or
            any(value != 0 for value in scheduler_summary.get("missed_deadlines", {}).values())):
        errors.append("scheduler_summary_invalid")
    motion_summary = summary.get("timing_motion")
    scheduler_row_count = sum(row.get("kind") == "scheduled_tick"
                              for row in rows["timing"])
    if (not isinstance(motion_summary, dict) or
            motion_summary.get("scored_slots_sent") != 50 or
            motion_summary.get("missed_periods") != 0 or
            motion_summary.get("queue_drops") != 0 or
            motion_summary.get("fault_reason") is not None or
            summary.get("timing_scheduler_ticks") != scheduler_row_count):
        errors.append("timing_summary_invalid")

    timing = rows["timing"]
    neural_slots = _slots(timing, domain="neural", arm_ns=start, count=50,
                          period_ns=PERIOD_NS, errors=errors)
    control_slots = _slots(timing, domain="watchdog", arm_ns=start, count=50,
                           period_ns=PERIOD_NS, errors=errors)
    perception_slots = _slots(timing, domain="perception", arm_ns=start, count=50,
                              period_ns=PERIOD_NS, errors=errors)
    outer_locks = [row for row in timing if row.get("kind") == "neural_outer_arbiter_lock"
                   and type(row.get("timestamp_ns")) is int and start <= row["timestamp_ns"] < end]
    if len(outer_locks) != 50:
        errors.append("neural_outer_lock_count_invalid")
    for slot, (scheduled, row) in enumerate(zip(neural_slots, outer_locks)):
        if (type(row.get("thread_id")) is not int or
                row.get("thread_id") != scheduled.get("thread_id") or
                not scheduled.get("step_start_ns", -1) <= row.get("wait_start_ns", -1) <=
                row.get("acquired_ns", -1) <= row.get("released_ns", -1) <=
                scheduled.get("tick_complete_ns", -1) or
                not row.get("acquired_ns", -1) <= row.get("queue_access_start_ns", -1) <=
                row.get("queue_access_end_ns", -1) <= row.get("released_ns", -1) or
                row.get("queue_wait_ns") != row.get("queue_access_end_ns", -1) -
                row.get("queue_access_start_ns", -1) or
                row.get("perception_wait_ns") != 0 or
                type(row.get("perception_source_age_ns")) is not int or
                not 0 <= row["perception_source_age_ns"] <=
                config["freshness_ttl_ms"] * 1_000_000 or
                row.get("timestamp_ns") != row.get("acquired_ns")):
            errors.append(f"neural_outer_lock_slot_{slot}_invalid")
    neural = [row for row in rows["neural"] if type(row.get("neural_call_started_ns")) is int
              and start <= row["neural_call_started_ns"] < end]
    neural_events = [row for row in rows["events"] if row.get("kind") == "neural_step"
                     and type(row.get("timestamp_ns")) is int and start <= row["timestamp_ns"] < end]
    timings = [row for row in timing if row.get("kind") == "neural_span" and
               type(row.get("neural_call_timestamp_ns")) is int
               and start <= row["neural_call_timestamp_ns"] < end]
    if len(neural) != 50 or len(neural_events) != 50 or len(timings) != 50:
        errors.append("neural_count_or_timing_missing")
    if len({row.get("runtime_step") for row in neural}) != len(neural):
        errors.append("neural_runtime_step_duplicate")
    if any((row.get("male_cns_healthy") is True and
            (_number(row.get("dn_escape")) and row["dn_escape"] >= .5 or
             row.get("raw_decoder_stop") is True)) for row in neural):
        errors.append("scored_false_neural_stop")
    if (len(neural) == 50 and any(b.get("runtime_step") != a.get("runtime_step", -2) + 1
                                  for a, b in zip(neural, neural[1:]))):
        errors.append("neural_runtime_step_gap")
    for slot, (scheduled, original, event, detail) in enumerate(
            zip(neural_slots, neural, neural_events, timings)):
        deadline = start + slot * PERIOD_NS
        span = detail.get("spans", {}).get("neural_call", {})
        if (original.get("neural_call_timestamp_ns") != scheduled.get("step_start_ns") or
                original.get("neural_call_timestamp_ns") != event.get("timestamp_ns") or
                detail.get("neural_call_timestamp_ns") != original.get("neural_call_timestamp_ns") or
                detail.get("result_none") is not False or
                span.get("start_ns") != original.get("neural_call_started_ns") or
                span.get("end_ns") != original.get("neural_call_returned_ns") or
                not deadline <= original["neural_call_started_ns"] <=
                original.get("neural_call_returned_ns", -1) < deadline + PERIOD_NS or
                original.get("input_none") is not False or original.get("result_none") is not False or
                original.get("male_cns_healthy") is not True or
                original.get("dn_runtime_healthy") is not True or
                not _number(original.get("dn_escape")) or
                type(original.get("raw_decoder_stop")) is not bool or
                original.get("perception_valid") is not True or
                event.get("runtime_healthy") is not True or
                event.get("dn_escape") != original.get("dn_escape") or
                event.get("decoder_stop") != original.get("raw_decoder_stop") or
                event.get("source_age_ms") != original.get("perception_age_ms") or
                event.get("source_frame_id") != original.get("perception_frame_id") or
                not _number(event.get("source_age_ms")) or
                not _number(original.get("perception_age_ms")) or
                not 0 <= original["perception_age_ms"] <= config["freshness_ttl_ms"]):
            errors.append(f"neural_slot_{slot}_invalid")
    publish = [row for row in rows["events"] if row.get("kind") == "control_publish"
               and type(row.get("timestamp_ns")) is int and start <= row["timestamp_ns"] < end]
    if len(publish) != 50 or len({row.get("sequence") for row in publish}) != 50:
        errors.append("control_publications_incomplete_or_duplicate")
    if (len(publish) == 50 and any(b.get("sequence") != a.get("sequence", -2) + 1
                                   for a, b in zip(publish, publish[1:]))):
        errors.append("control_sequence_gap")
    for slot, (scheduled, event) in enumerate(zip(control_slots, publish)):
        deadline = start + slot * PERIOD_NS
        if (type(event.get("call_ns")) is not int or
                type(event.get("ack_ns")) is not int or
                event.get("timestamp_ns") != event.get("ack_ns") or
                not deadline <= scheduled.get("worker_wake_ns", -1) <=
                scheduled.get("step_start_ns", -1) <=
                event["call_ns"] <= event["ack_ns"] <=
                scheduled.get("tick_complete_ns", -1) < deadline + PERIOD_NS or
                event.get("watchdog_state") != "healthy" or
                event.get("stop") is not False or
                type(event.get("intent")) is not dict or
                event["intent"].get("sequence") != event.get("sequence") or
                event["intent"].get("stop") is not False or
                event.get("transport") !=
                "suppressed_neutral_for_stop_causality_fixture"):
            errors.append(f"control_slot_{slot}_invalid")
        try:
            intent = validate_behavior_intent(event["intent"])
            if (not deadline <= intent["timestamp_ns"] <= event["call_ns"] or
                    any(intent[key] != 0 for key in ("vx", "vy", "vyaw"))):
                errors.append(f"control_slot_{slot}_intent_invalid")
        except (KeyError, ControlContractError, TypeError):
            errors.append(f"control_slot_{slot}_intent_invalid")
        if slot < len(neural_slots) and scheduled.get("step_start_ns", -1) < neural_slots[
                slot].get("tick_complete_ns", 1 << 64):
            errors.append(f"control_slot_{slot}_preceded_neural")
    visual = [row for row in rows["visual"] if type(row.get("timestamp_ns")) is int
              and start <= row["timestamp_ns"] < end]
    visual_events = [row for row in rows["events"] if row.get("kind") == "visual_frame"
                     and type(row.get("timestamp_ns")) is int and start <= row["timestamp_ns"] < end]
    if len(visual) != 20 or len(visual_events) != 20 or len({row.get("frame_id") for row in visual}) != 20:
        errors.append("visual_frames_incomplete_or_duplicate")
    if (visual and (visual[0]["timestamp_ns"] - start > VISUAL_PERIOD_NS or
                    end - visual[-1]["timestamp_ns"] > 100_000_000)):
        errors.append("visual_boundary_gap")
    scenario = load_config(ROOT / "config/looming_scenario_v1.json")
    baseline = [row for row in rows["events"] if row.get("kind") == "prearm_visual_anchor"
                and type(row.get("timestamp_ns")) is int and row["timestamp_ns"] < start]
    if len(baseline) != 1:
        errors.append("prearm_visual_baseline_missing")
    else:
        try:
            base_pose = baseline[0]["pose"]
            base_trial, base_distance = relative_trial(
                pose=base_pose, trial_id=ident, ordinal=spec["ordinal"],
                mode=spec["mode"], elapsed_after_arm_s=0.0)
            base_pixels = render_fractional_pixels(scenario, base_trial,
                                                   pose=base_pose, elapsed_s=0)
            base_area = sum(pixel[0] for line in base_pixels for pixel in line) / (
                255 * scenario["image_width_px"] * scenario["image_height_px"])
            if (abs(baseline[0]["distance_m"] - base_distance) > 1e-10 or
                    abs(baseline[0]["image_area"] - base_area) > 1e-12):
                errors.append("prearm_visual_baseline_invalid")
        except (KeyError, TypeError, ValueError, IndexError):
            errors.append("prearm_visual_baseline_invalid")
    frame_by_id = {row.get("frame_id"): row for row in rows["visual"]}
    for slot, (original, event) in enumerate(zip(visual, visual_events)):
        if (original.get("perception_valid") is not True or
                event.get("source_valid") is not True or
                event.get("timestamp_ns") != original.get("timestamp_ns") or
                event.get("source_frame_id") != original.get("frame_id") or
                event.get("pixels_sha256") != original.get("pixels_sha256") or
                original.get("tof_source") != "frozen_synthetic_fixture" or
                any(original.get(key) != scenario["tof_mm"] for key in
                    ("tof_left_mm", "tof_center_mm", "tof_right_mm")) or
                original.get("tof_timestamp_ns") != original.get("timestamp_ns") or
                original.get("tof_frame_id") != original.get("frame_id") or
                event.get("tof_timestamp_ns") != original.get("tof_timestamp_ns") or
                event.get("tof_frame_id") != original.get("tof_frame_id") or
                not _number(event.get("image_area")) or
                not math.isclose(event["image_area"], original.get("perception_target_area", -1),
                                 rel_tol=0, abs_tol=1e-12)):
            errors.append(f"visual_slot_{slot}_invalid")
        try:
            pose = event["pose"]
            raw_pose = body_pose(json.loads(event["raw_body_packet"]))
            if (any(abs(raw_pose[key] - pose[key]) > 1e-10 for key in pose) or
                    type(event["pose_request_ns"]) is not int or
                    type(event["pose_response_ns"]) is not int or
                    not event["timestamp_ns"] <= event["pose_request_ns"] <=
                    event["pose_response_ns"] <=
                    event["timestamp_ns"] + config["freshness_ttl_ms"] * 1e6):
                raise ValueError("visual pose source invalid")
            virtual, distance = relative_trial(
                pose=pose, trial_id=ident, ordinal=spec["ordinal"],
                mode=spec["mode"],
                elapsed_after_arm_s=(event["timestamp_ns"] - start) / 1e9)
            pixels = render_fractional_pixels(scenario, virtual, pose=pose, elapsed_s=0)
            area = sum(pixel[0] for line in pixels for pixel in line) / (
                255 * scenario["image_width_px"] * scenario["image_height_px"])
            if (abs(event["distance_m"] - distance) >
                    config["static_tolerance_m"] or
                    abs(event["target_distance_m"] - distance) >
                    config["static_tolerance_m"] or
                    abs(event["virtual_center_x_m"] - virtual.anchor_x_m) > 1e-10 or
                    abs(event["virtual_center_y_m"] - virtual.anchor_y_m) > 1e-10 or
                    abs(event["bearing_rad"]) > 1e-10 or
                    abs(event["image_area"] - area) > 1e-12 or
                    event["pixels_sha256"] != pixels_sha256(pixels)):
                raise ValueError("visual geometry or pixels invalid")
        except (KeyError, TypeError, ValueError, IndexError):
            errors.append(f"visual_slot_{slot}_geometry_invalid")
    for original in neural:
        source = frame_by_id.get(original.get("perception_frame_id"))
        if (source is None or source.get("timestamp_ns") != original.get("perception_timestamp_ns") or
                not 0 <= original["neural_call_started_ns"] - source["timestamp_ns"] <=
                config["freshness_ttl_ms"] * 1e6):
            errors.append("neural_visual_lineage_invalid")
            break
    motion = [row for row in timing if row.get("kind") == "motion_refresh"
              and row.get("phase") == "scored"]
    prearm_motion = [row for row in timing if row.get("kind") == "motion_refresh"
                     and row.get("phase") == "prearm" and
                     type(row.get("move_ack_ns")) is int and row["move_ack_ns"] < start]
    if (not v3 and precondition and prearm_motion and
            not 0 <= prearm_motion[0]["move_ack_ns"] - precondition[-1]["timestamp_ns"] <=
            config["moving_gate"]["maximum_state_age_ms"] * 1e6):
        errors.append("precondition_to_keepalive_gap_invalid")
    if (v3 and precondition and prearm_motion and
            (len(prearm_motion) < len(precondition) or
             precondition[-1]["timestamp_ns"] != prearm_motion[
                 len(precondition) - 1]["move_ack_ns"])):
        errors.append("causal_prearm_motion_lineage_invalid")
    arm_handoff = [row for row in timing if row.get("kind") == "motion_arm"]
    if (not prearm_motion or len(arm_handoff) != 1 or
            arm_handoff[0].get("timestamp_ns") != start or
            arm_handoff[0].get("last_move_ack_ns") != prearm_motion[-1]["move_ack_ns"] or
            type(arm_handoff[0].get("handoff_gap_ns")) is not int or
            not 0 <= arm_handoff[0]["handoff_gap_ns"] <= 40_000_000):
        errors.append("prearm_motion_handoff_invalid")
    ready = [row for row in rows["events"] if row.get("kind") == "timing_prearm_ready"]
    if (len(ready) != 1 or ready[0].get("worker_count") != 6 or
            type(ready[0].get("timestamp_ns")) is not int or
            not 0 <= start - ready[0]["timestamp_ns"] <=
            config["moving_gate"]["maximum_state_age_ms"] * 1e6 or
            type(ready[0].get("state_source_ns")) is not int or
            not 0 <= ready[0]["timestamp_ns"] - ready[0]["state_source_ns"] <=
            config["moving_gate"]["maximum_state_age_ms"] * 1e6 or
            type(ready[0].get("applied_velocity")) is not list or
            len(ready[0]["applied_velocity"]) != 3 or
            ready[0]["applied_velocity"][0] <
            config["moving_gate"]["minimum_fresh_applied_vx_mps"] or
            any(any(word in str(reason).lower() for word in
                    ("deadman", "fault", "safety", "stale", "ttl"))
                for reason in ready[0].get("limited_by", [])) or
            ready[0].get("policy") not in
            config["settled_gate"]["allowed_observed_policy_states"] or
            ready[0].get("safety", {}).get("fallen") or
            ready[0].get("safety", {}).get("limp") or
            not prearm_motion or ready[0].get("last_move_ack_ns") not in
            {row["move_ack_ns"] for row in prearm_motion} or
            ready[0]["last_move_ack_ns"] > ready[0]["timestamp_ns"] or
            type(ready[0].get("last_pose_source_ns")) is not int or
            not 0 <= start - ready[0]["last_pose_source_ns"] <=
            config["moving_gate"]["maximum_pose_age_ms"] * 1e6):
        errors.append("prearm_ready_lineage_invalid")
    motion_events = [row for row in rows["events"] if row.get("kind") == "motion_refresh"
                     and type(row.get("timestamp_ns")) is int and start <= row["timestamp_ns"] < end]
    if (len(motion) != 50 or len(motion_events) != 50 or
            {row.get("scored_slot") for row in motion} != set(range(50))):
        errors.append("motion_slots_incomplete_or_duplicate")
    if v3 and (folder / "diagnostic.jsonl").is_file():
        try:
            diagnostic_rows = _read_jsonl(folder / "diagnostic.jsonl")
            accepted = {}
            for row in diagnostic_rows:
                if row.get("kind") == "robot.move.ack":
                    response = json.loads(row["wire"])
                    result_wire = response["result"]
                    accepted[result_wire["accepted_move_generation"]] = row["received_at_ns"]
            scored_generations = [row["result"]["accepted_move_generation"] for row in motion]
            if (len(set(scored_generations)) != 50 or
                    any(accepted.get(row["result"]["accepted_move_generation"]) !=
                        row["move_ack_ns"] for row in motion)):
                errors.append("scored_move_generation_ack_lineage_invalid")
            result["scored_move_generations"] = scored_generations
        except (KeyError, TypeError, ValueError, IndexError):
            errors.append("scored_move_generation_ack_lineage_invalid")
    for slot, (detail, event) in enumerate(zip(motion, motion_events)):
        deadline = start + slot * PERIOD_NS
        if (detail.get("scored_slot") != slot or
                detail.get("scheduled_deadline_ns") != deadline or
                type(detail.get("thread_id")) is not int or
                not deadline <= detail.get("wake_ns", -1) <=
                detail.get("move_call_ns", -1) <= detail.get("move_write_ns", -1) <=
                detail.get("move_ack_ns", -1) < deadline + PERIOD_NS or
                detail.get("timestamp_ns") != detail.get("move_ack_ns") or
                not isinstance(detail.get("result"), dict) or
                detail["result"].get("accepted") is not True or
                event.get("timestamp_ns") != detail.get("move_ack_ns") or
                event.get("result") != detail.get("result")):
            errors.append(f"motion_slot_{slot}_invalid")
    stop_acks = [row["ack_ns"] for row in publish
                 if row.get("transport") == "robot.stop" and type(row.get("ack_ns")) is int]
    stop_acks.extend(row["timestamp_ns"] for row in rows["events"]
                     if row.get("kind") == "cleanup" and
                     type(row.get("timestamp_ns")) is int and
                     row.get("robot_stop_result") is not None)
    if stop_acks and any(row.get("move_ack_ns", -1) >= min(stop_acks)
                         for row in timing if row.get("kind") == "motion_refresh"):
        errors.append("positive_move_after_stop_ack")
    observations = {}
    scored_ack_set = {row.get("move_ack_ns") for row in motion}
    for kind in ("state", "pose"):
        selected = [row for row in timing if row.get("kind") == f"{kind}_observation"
                    and type(row.get("timestamp_ns")) is int and start <= row["timestamp_ns"] < end
                    and row.get("move_ack_ns") in scored_ack_set]
        observations[kind] = selected
        if len(selected) < 40 or len({row.get("source_timestamp_ns") for row in selected}) < 40:
            errors.append(f"{kind}_observation_count_low")
        for row in selected:
            if (type(row.get("source_timestamp_ns")) is not int or
                    type(row.get("move_ack_ns")) is not int or
                    row["move_ack_ns"] not in scored_ack_set or
                    not 0 <= row["timestamp_ns"] - row["source_timestamp_ns"] <=
                    config["freshness_ttl_ms"] * 1e6 or
                    type(row.get("thread_id")) is not int or
                    type(row.get("value")) is not dict):
                errors.append(f"{kind}_observation_lineage_invalid")
                break
    poses = []
    for row in observations["state"]:
        value = row.get("value", {})
        applied = value.get("applied_velocity")
        requested = value.get("requested_velocity")
        if (type(applied) not in (list, tuple) or len(applied) != 3 or
                not all(_number(v) for v in applied) or applied[0] <
                config["moving_gate"]["minimum_fresh_applied_vx_mps"] or
                type(requested) not in (list, tuple) or len(requested) != 3 or
                not all(_number(v) for v in requested) or
                any(abs(value) > limit for values in (applied, requested)
                    for value, limit in zip(values, (.08, 0, .5))) or
                any(any(word in str(reason).lower() for word in
                        ("deadman", "fault", "safety", "stale", "ttl"))
                    for reason in value.get("limited_by", [])) or
                value.get("policy") not in config["settled_gate"]["allowed_observed_policy_states"] or
                value.get("safety", {}).get("fallen") or value.get("safety", {}).get("limp")):
            errors.append("state_motion_or_deadman_invalid")
            break
    for row in observations["pose"]:
        value = row.get("value", {})
        pose = value.get("pose", value)
        if not _number(pose.get("x_m")) or not _number(pose.get("y_m")):
            errors.append("pose_motion_invalid")
            break
        try:
            raw_pose = body_pose(json.loads(value["raw_body_packet"]))
            if (any(abs(raw_pose[key] - pose[key]) > 1e-10
                    for key in ("x_m", "y_m", "trunk_z_m", "heading_rad")) or
                    not 0 <= row["source_timestamp_ns"] - value["request_ns"] <=
                    config["moving_gate"]["maximum_pose_age_ms"] * 1e6):
                raise ValueError("pose source mismatch")
        except (KeyError, TypeError, ValueError):
            errors.append("pose_raw_lineage_invalid")
            break
        poses.append((row["timestamp_ns"], pose["x_m"], pose["y_m"]))
    if len(poses) >= 40:
        poses.sort()
        displacement = math.hypot(poses[-1][1] - poses[0][1],
                                  poses[-1][2] - poses[0][2])
        speeds = [math.hypot(b[1] - a[1], b[2] - a[2]) / ((b[0] - a[0]) / 1e9)
                  for a, b in zip(poses, poses[1:]) if b[0] > a[0]]
        if (len(speeds) < 39 or displacement < config["moving_gate"]["minimum_trunk_displacement_m"]
                or sum(speed >= config["moving_gate"]["minimum_pose_speed_mps"]
                       for speed in speeds) < math.ceil(.8 * len(speeds)) or
                any(speed < config["moving_gate"]["minimum_pose_speed_mps"]
                    for speed in speeds[-2:])):
            errors.append("body_motion_not_continuous")
    metrics = {"visual": _stream(visual_events, start, end),
               "neural": _stream(neural_events, start, end),
               "control": _stream(publish, start, end),
               "motion": _stream(motion_events, start, end),
               "state": _stream(observations["state"], start, end),
               "pose": _stream(observations["pose"], start, end)}
    for name, limit in (("visual", 100), ("neural", 40), ("control", 40),
                        ("motion", 100), ("state", 100), ("pose", 100)):
        gap = metrics[name]["max_gap_ms"]
        if gap is not None and gap > limit:
            errors.append(f"{name}_gap_exceeded")
    for name in ("state", "pose"):
        last = metrics[name]["last_ns"]
        if last is None or end - last > 100_000_000:
            errors.append(f"{name}_tail_gap")
    spans = {}
    for name in ("neural_call", "graph_runtime", "sensory_channels", "sensory_external",
                 "readout", "decoder_safety_latch", "arbiter_lock_wait",
                 "trace_construction", "ledger_append"):
        durations = []
        for row in timings:
            span = row.get("spans", {}).get(name, {})
            if (type(span.get("start_ns")) is not int or type(span.get("end_ns")) is not int
                    or span["end_ns"] < span["start_ns"]):
                errors.append(f"{name}_span_missing_or_invalid")
                break
            durations.append(span["end_ns"] - span["start_ns"])
        spans[name] = _distribution_ns(durations)
    metrics["spans"] = spans
    metrics["outer_arbiter_lock_wait"] = _distribution_ns([
        row["acquired_ns"] - row["wait_start_ns"] for row in outer_locks
        if type(row.get("acquired_ns")) is int and type(row.get("wait_start_ns")) is int])
    metrics["neural_queue_access"] = _distribution_ns([
        row["queue_wait_ns"] for row in outer_locks
        if type(row.get("queue_wait_ns")) is int and row["queue_wait_ns"] >= 0])
    metrics["control_publish"] = _distribution_ns([
        row["ack_ns"] - row["call_ns"] for row in publish
        if type(row.get("ack_ns")) is int and type(row.get("call_ns")) is int])
    visual_durations = []
    for row in visual:
        if (type(row.get("processing_started_ns")) is not int or
                type(row.get("processing_finished_ns")) is not int or
                row["processing_finished_ns"] < row["processing_started_ns"]):
            errors.append("visual_processing_span_missing")
            break
        visual_durations.append(row["processing_finished_ns"] -
                                row["processing_started_ns"])
    metrics["visual_processing"] = _distribution_ns(visual_durations)
    cpu_durations = []
    for row in timings:
        if (type(row.get("thread_cpu_start_ns")) is not int or
                type(row.get("thread_cpu_return_ns")) is not int or
                row["thread_cpu_return_ns"] < row["thread_cpu_start_ns"]):
            errors.append("neural_thread_cpu_span_missing")
            break
        cpu_durations.append(row["thread_cpu_return_ns"] - row["thread_cpu_start_ns"])
    metrics["neural_thread_cpu"] = _distribution_ns(cpu_durations)
    process_cpu = [row for row in rows["events"] if row.get("kind") == "timing_process_cpu"]
    if (len(process_cpu) != 1 or type(process_cpu[0].get("cpu_at_arm_ns")) is not int or
            type(process_cpu[0].get("cpu_at_complete_ns")) is not int or
            process_cpu[0]["cpu_at_complete_ns"] < process_cpu[0]["cpu_at_arm_ns"]):
        errors.append("process_cpu_span_missing")
    else:
        metrics["process_cpu_ms"] = (process_cpu[0]["cpu_at_complete_ns"] -
                                     process_cpu[0]["cpu_at_arm_ns"]) / 1e6
    metrics["neural_wake_jitter"] = _distribution_ns([
        row["worker_wake_ns"] - row["scheduled_deadline_ns"] for row in neural_slots
        if type(row.get("worker_wake_ns")) is int and type(row.get("scheduled_deadline_ns")) is int])
    metrics["move_rpc"] = _distribution_ns([
        row["move_ack_ns"] - row["move_call_ns"] for row in motion
        if type(row.get("move_ack_ns")) is int and type(row.get("move_call_ns")) is int])
    result.update({"metrics": metrics, "result": "PASS" if not errors else "FAIL"})
    return result


def score_batch(output: Path, config: dict) -> dict:
    """Reconstruct all three probe IDs from raw files; never trust summary PASS."""
    output = Path(output)
    ids = PROBE_IDS.get(config.get("schema_version"))
    if (ids is None or
            (config.get("scored_window_ms"), config.get("visual_hz"),
             config.get("neural_hz"), config.get("control_hz")) != (1000, 20, 50, 50)):
        return {"result": "FAIL", "error": "frozen_probe_config_invalid"}
    specs = config.get("development_gate", {}).get("ids", [])
    if [row.get("reset_id") for row in specs] != list(ids):
        return {"result": "FAIL", "error": "probe_ID_allocation_invalid"}
    try:
        journal = json.loads((output / "batch-journal.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {"result": "FAIL", "error": "batch_journal_unreadable"}
    final = journal.get("final_sim_down") or {}
    final_ok = (final.get("exit") == 0 and final.get("interrupted") is False and
                final.get("state_probe_result") == "PASS")
    try:
        raw_final = json.loads((output / "final-state-probe.json").read_text(encoding="utf-8"))
        final_ok = (final_ok and raw_final.get("result") == "PASS" and
                    final.get("state_probe_sha256") == _sha(output / "final-state-probe.json") and
                    final.get("sha256") == _sha(output / "final-down.log"))
    except (OSError, ValueError, TypeError):
        final_ok = False
    trials = []
    for spec in specs:
        entries = [item for item in journal.get("ids", [])
                   if item.get("reset_id") == spec["reset_id"]]
        if len(entries) != 1 or len(entries[0].get("attempts", [])) != 1:
            trials.append({"reset_id": spec["reset_id"], "result": "FAIL",
                           "failure_causes": ["attempt_accounting_invalid"]})
            continue
        attempt = entries[0]["attempts"][0]
        folder = output / spec["reset_id"] / attempt.get("name", "attempt-01")
        try:
            trial = _score_trial(folder, spec, config)
        except (KeyError, TypeError, ValueError, IndexError, ZeroDivisionError) as error:
            trial = {"reset_id": spec["reset_id"], "result": "FAIL",
                     "failure_causes": [f"raw_schema_invalid:{type(error).__name__}"]}
        if (attempt.get("armed") is not True or attempt.get("status") != "TRIAL_EXITED" or
                attempt.get("trial_exit") != 0 or entries[0].get("status") != "ARMED_COMPLETE"):
            trial["failure_causes"].append("journal_trial_incomplete")
            trial["result"] = "FAIL"
        trials.append(trial)
    return {"schema_version": config["schema_version"].replace("probe-", "probe-score-"),
            "result": "PASS" if final_ok and len(trials) == 3 and
            all(t["result"] == "PASS" for t in trials)
            else "FAIL", "trials": trials, "final_down_raw_valid": final_ok,
            "behavioral_acceptance_change": False}
