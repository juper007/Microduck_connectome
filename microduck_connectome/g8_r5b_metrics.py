"""Frozen pose-speed and stop-source checks for G8-R5b integration evidence."""
from __future__ import annotations

import math

STATE_PATH = ("SETUP", "MOTION_PRECONDITION", "MOTION_CONFIRMED",
              "NEURAL_LOOMING", "NEURAL_STOP_DETECTED", "STOP_TRANSPORT_ACK",
              "MOTION_STOPPED", "COMPLETE")


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
