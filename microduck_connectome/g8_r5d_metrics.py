"""Pose, geometry, deadman, and state checks for G8-R5d fixture evidence."""
from __future__ import annotations

import math

STATE_PATH = ("SETUP", "MOTION_PRECONDITION", "MOTION_CONFIRMED",
              "NEURAL_OBSERVATION_ARMED", "NEURAL_LOOMING", "NEURAL_STOP_DETECTED",
              "ROBOT_STOP_SENT", "ROBOT_STOP_ACK", "STOP_REFRESHING",
              "MOTION_STOPPED", "COMPLETE")


def stop_refresh_cadence(acks, *, maximum_gap_ms, deadman_timeout_ms,
                         stopped_confirmed_ns=None):
    """Audit actual acknowledged stop transport in one monotonic clock domain."""
    if (type(maximum_gap_ms) not in (int, float) or type(deadman_timeout_ms) not in (int, float)
            or not 0 < maximum_gap_ms < deadman_timeout_ms):
        raise ValueError("refresh bound must be positive and below deadman timeout")
    if any(type(row.get("sent_at_ns")) is not int or type(row.get("ack_at_ns")) is not int
           or row["sent_at_ns"] > row["ack_at_ns"] for row in acks):
        return {"valid": False, "count": len(acks), "max_gap_ms": None,
                "mean_gap_ms": None, "ack_timestamps_ns": []}
    stamps = [row["ack_at_ns"] for row in acks]
    gaps = [(b - a) / 1e6 for a, b in zip(stamps, stamps[1:])]
    tail = ((stopped_confirmed_ns - stamps[-1]) / 1e6
            if stamps and type(stopped_confirmed_ns) is int else None)
    valid = (len(stamps) >= 2 and all(0 < gap <= maximum_gap_ms for gap in gaps)
             and tail is not None and 0 <= tail <= maximum_gap_ms)
    return {"valid": valid, "count": len(stamps), "max_gap_ms": max(gaps, default=None),
            "mean_gap_ms": sum(gaps) / len(gaps) if gaps else None,
            "tail_to_stopped_ms": tail, "ack_timestamps_ns": stamps}


def deadman_limiter_seen_before_stopped(state_samples, stopped_confirmed_ns):
    """Audit every official state sample in the decision-bearing stop interval."""
    if type(stopped_confirmed_ns) is not int:
        return None
    for row in state_samples:
        at_ns = row.get("state_sample_timestamp_ns")
        if type(at_ns) is not int:
            raise ValueError("state sample missing monotonic timestamp")
        if at_ns <= stopped_confirmed_ns and any(
                "deadman" in str(reason).lower() for reason in row.get("limited_by", [])):
            return True
    return False


def material_pre_stop_applied(vx, minimum_vx):
    """Exclude a nearly stopped baseline from apparent robot.stop deceleration."""
    return (type(vx) in (int, float) and type(minimum_vx) in (int, float)
            and math.isfinite(vx) and math.isfinite(minimum_vx)
            and minimum_vx > 0 and vx >= minimum_vx)


def stop_onset_before_deadman(first_stopped_ns, refreshed_deadline_ns, deadman_events):
    """Require actual pose-stop onset before refreshed robotd deadman can intervene."""
    return (type(first_stopped_ns) is int and type(refreshed_deadline_ns) is int
            and first_stopped_ns < refreshed_deadline_ns
            and not any(type(event.get("timestamp_ns")) is not int
                        or event["timestamp_ns"] <= first_stopped_ns
                        for event in deadman_events))


def neural_input_ended_by_ack(ledger, stop_ack_ns):
    """Conservative gate for every completed graph invocation in the raw ledger."""
    return (type(stop_ack_ns) is int and all(
        type(row.get("neural_call_started_ns")) is int
        and type(row.get("neural_call_returned_ns")) is int
        and row["neural_call_started_ns"] <= row["neural_call_returned_ns"] < stop_ack_ns
        for row in ledger))


def deadman_timing(last_move_call_ns, last_move_ack_ns, stop_ack_ns, *,
                   timeout_ms, minimum_margin_ms):
    """Conservative receipt-age bound: move call starts before robotd receives it."""
    if not all(type(t) is int and t >= 0 for t in
               (last_move_call_ns, last_move_ack_ns, stop_ack_ns)):
        return {"valid": False, "age_from_call_ms": None,
                "age_from_ack_ms": None, "margin_from_call_ms": None}
    if not (last_move_call_ns <= last_move_ack_ns < stop_ack_ns):
        return {"valid": False, "age_from_call_ms": None,
                "age_from_ack_ms": None, "margin_from_call_ms": None}
    if not all(type(v) in (int, float) and math.isfinite(v) and v > 0
               for v in (timeout_ms, minimum_margin_ms)):
        raise ValueError("invalid frozen deadman limit")
    age_call = (stop_ack_ns - last_move_call_ns) / 1e6
    age_ack = (stop_ack_ns - last_move_ack_ns) / 1e6
    margin = timeout_ms - age_call
    return {"valid": margin >= minimum_margin_ms,
            "age_from_call_ms": age_call, "age_from_ack_ms": age_ack,
            "margin_from_call_ms": margin}


def safe_observation_horizon(center_distance_m, sphere_radius_m,
                             sphere_approach_mps, robot_forward_displacement_bound_m,
                             *, observation_ms, margin_ms):
    """Bound virtual camera entry with a frozen body forward-displacement allowance."""
    values = (center_distance_m, sphere_radius_m, sphere_approach_mps,
              robot_forward_displacement_bound_m, observation_ms, margin_ms)
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
        raise ValueError("nonfinite geometry bound")
    if (center_distance_m <= sphere_radius_m + robot_forward_displacement_bound_m
            or sphere_radius_m <= 0 or sphere_approach_mps <= 0
            or robot_forward_displacement_bound_m < 0
            or observation_ms <= 0 or margin_ms <= 0):
        raise ValueError("invalid geometry bound")
    entry_ms = 1000 * (center_distance_m - sphere_radius_m
                       - robot_forward_displacement_bound_m) / sphere_approach_mps
    return {"time_to_camera_entry_lower_bound_ms": entry_ms,
            "safe": observation_ms + margin_ms < entry_ms}


def bounded_neural_lineage(ledger, stop_record, *, max_age_ms, max_runtime_step_gap):
    """Validate complete positive-looming/LPLC2 to later DN-stop step lineage.

    This is temporal consistency, not evidence that LPLC2 is the sole biological
    cause: LC10a can be a simultaneous visual co-input in the frozen mapper.
    """
    failure = {"valid": False, "source_step": None, "stop_step": None,
               "age_ms": None, "reason": None}
    if not isinstance(ledger, list) or not isinstance(stop_record, dict):
        return {**failure, "reason": "missing_ledger_or_stop"}
    if type(max_age_ms) not in (int, float) or not 0 < max_age_ms <= 100:
        raise ValueError("lineage age must honor frozen P6 TTL")
    if type(max_runtime_step_gap) is not int or not 0 <= max_runtime_step_gap <= 5:
        raise ValueError("invalid runtime step gap")
    k = stop_record.get("dn_activity", {}).get("sequence")
    stop_ns = stop_record.get("dn_activity", {}).get("timestamp_ns")
    graph_identity = stop_record.get("identities", {}).get("graph_identity")
    if type(k) is not int or type(stop_ns) is not int:
        return {**failure, "reason": "missing_stop_readout_identity"}
    if not isinstance(graph_identity, str) or not graph_identity:
        return {**failure, "reason": "missing_graph_identity"}
    indexed = {row.get("runtime_step"): (i, row) for i, row in enumerate(ledger)
               if not row.get("result_none") and type(row.get("runtime_step")) is int}
    if k not in indexed or indexed[k][1].get("dn_sequence") != k:
        return {**failure, "stop_step": k, "reason": "stop_step_missing_or_mismatched"}
    stop_index, stop_row = indexed[k]
    if stop_record.get("male_cns", {}).get("runtime_step") != k:
        return {**failure, "stop_step": k, "reason": "stop_record_runtime_mismatch"}
    candidates = []
    for index, row in enumerate(ledger[:stop_index + 1]):
        if (not row.get("result_none") and row.get("perception_valid") is True
                and row.get("looming", 0) > 0
                and max(row.get("stimulus_channels", {}).get("lplc2_left", 0),
                        row.get("stimulus_channels", {}).get("lplc2_right", 0)) > 0):
            candidates.append((index, row))
    if not candidates:
        return {**failure, "stop_step": k, "reason": "no_prior_positive_visual_stimulus"}
    source_index, source = candidates[-1]
    j = source["runtime_step"]
    age_ms = (stop_ns - source["dn_timestamp_ns"]) / 1e6
    result = {"valid": False, "source_step": j, "stop_step": k,
              "age_ms": age_ms, "reason": None,
              "source_frame_id": source["perception_frame_id"],
              "stop_frame_id": stop_row["perception_frame_id"],
              "observed_steps": []}
    if not 0 <= age_ms <= max_age_ms or not 0 <= k - j <= max_runtime_step_gap:
        return {**result, "reason": "age_or_step_gap_exceeded"}
    segment = ledger[source_index:stop_index + 1]
    if len(segment) != k - j + 1:
        return {**result, "reason": "missing_intermediate_neural_call"}
    for offset, row in enumerate(segment):
        step = j + offset
        result["observed_steps"].append(row.get("runtime_step"))
        if (row.get("result_none") or row.get("input_none")
                or row.get("runtime_step") != step or row.get("dn_sequence") != step
                or row.get("male_cns_healthy") is not True
                or row.get("graph_identity") != graph_identity
                or row.get("dn_runtime_healthy") is not True
                or row.get("perception_valid") is not True
                or type(row.get("perception_timestamp_ns")) is not int
                or type(row.get("neural_call_timestamp_ns")) is not int
                or not 0 <= row["neural_call_timestamp_ns"]
                       - row["perception_timestamp_ns"] <= 100_000_000
                or any(row.get(name, 0) != 0 for name in
                       ("proximity_left", "proximity_center", "proximity_right"))):
            return {**result, "reason": "invalid_or_stale_intermediate_step"}
    if stop_row["dn_escape"] != stop_record["dn_activity"]["escape"]:
        return {**result, "reason": "stop_escape_mismatch"}
    return {**result, "valid": True, "reason": "bounded_temporal_visual_lineage"}


def pose_speeds(samples, *, window_ms=100, max_window_ms=140):
    """Return pose-derived speeds using a bounded preceding monotonic window."""
    if not 0 < window_ms <= max_window_ms:
        raise ValueError("invalid speed window")
    low, high = window_ms * 1_000_000, max_window_ms * 1_000_000
    results = []
    previous_ns = -1
    for index, item in enumerate(samples):
        timestamp = item["timestamp_ns"]
        x, y = item["x_m"], item["y_m"]
        if (type(timestamp) is not int or timestamp <= previous_ns
                or not all(type(v) in (int, float) and math.isfinite(v) for v in (x, y))):
            raise ValueError("nonmonotonic or nonfinite official pose")
        previous_ns = timestamp
        prior = None
        for candidate in reversed(samples[:index]):
            elapsed = timestamp - candidate["timestamp_ns"]
            if elapsed >= low:
                if elapsed <= high:
                    prior = candidate
                break
        speed = None if prior is None else math.hypot(x - prior["x_m"], y - prior["y_m"]) / (
            (timestamp - prior["timestamp_ns"]) / 1e9)
        results.append({**item, "pose_speed_mps": speed})
    return results


def first_sustained(rows, *, threshold_mps, duration_ms, at_or_above, after_ns=None,
                    before_ns=None):
    """Return first confirmation timestamp of a continuous threshold interval."""
    if not math.isfinite(threshold_mps) or threshold_mps < 0 or duration_ms <= 0:
        raise ValueError("invalid criterion")
    started = None
    previous = None
    for row in rows:
        timestamp = row["timestamp_ns"]
        if after_ns is not None and timestamp < after_ns:
            continue
        if before_ns is not None and timestamp >= before_ns:
            break
        value = row["pose_speed_mps"]
        passed = (value is not None and math.isfinite(value)
                  and (value >= threshold_mps if at_or_above else value <= threshold_mps))
        if not passed or (previous is not None and timestamp - previous > 80_000_000):
            started = None
        if passed:
            if started is None:
                started = timestamp
            if timestamp - started >= duration_ms * 1_000_000:
                return timestamp
            previous = timestamp
        else:
            previous = None
    return None


def is_healthy_neural_stop(record, *, threshold):
    if not math.isfinite(threshold) or not 0 < threshold <= 1:
        raise ValueError("invalid escape threshold")
    return (
        record["male_cns"]["healthy"]
        and record["dn_activity"]["runtime_healthy"]
        and record["dn_activity"]["escape"] >= threshold
        and record["pre_safety_intent"]["stop"]
        and record["post_safety_intent"]["stop"]
        and record["watchdog_state"] == "healthy"
        and record["robot_facing_stop"]
        and record["robot_facing_command_type"] == "robot.stop"
        and record["robotd_transport_result"] == "robot_stop_refreshed"
    )


def causal_timeline_ok(*timestamps):
    """Validate measured same-clock stage ordering; no missing time is inferred."""
    return (len(timestamps) >= 3 and all(type(t) is int and t >= 0 for t in timestamps)
            and all(a <= b for a, b in zip(timestamps, timestamps[1:]))
            and timestamps[0] < timestamps[-1])


def valid_state_path(states, *, complete):
    """A failed trial may end early; a PASS needs every ordered transition."""
    if not isinstance(states, (tuple, list)) or any(s not in STATE_PATH for s in states):
        return False
    expected = STATE_PATH if complete else STATE_PATH[:len(states)]
    return tuple(states) == expected
