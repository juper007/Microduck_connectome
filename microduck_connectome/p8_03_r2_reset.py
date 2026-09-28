"""Prospective P8-03-R2 fresh-reset qualification; no scored outcome input."""
from __future__ import annotations

import math

REFERENCE = {
    "x_m": 0.03457887954384973,
    "y_m": 0.0010909211238251523,
    "heading_rad": 0.11693358424258107,
    "trunk_z_m": 0.11587609862790209,
}
TOLERANCE = {"x_m": .03, "y_m": .03, "heading_rad": .08, "trunk_z_m": .025}
HEADING_GUARD_RAD = .06
SAMPLE_PERIOD_S = .05
SETTLE_S = 1.0
MAX_SAMPLE_AGE_S = .10
MAX_HEADING_DRIFT_RAD = .005


def wrapped_delta(value: float, reference: float) -> float:
    return math.atan2(math.sin(value - reference), math.cos(value - reference))


def pose_deltas(pose: dict) -> dict[str, float]:
    if set(REFERENCE) - set(pose):
        raise ValueError("incomplete pose")
    if any(type(pose[key]) not in (int, float) or not math.isfinite(pose[key])
           for key in REFERENCE):
        raise ValueError("nonfinite pose")
    return {key: (wrapped_delta(pose[key], value) if key == "heading_rad"
                  else pose[key] - value) for key, value in REFERENCE.items()}


def alignment_eligible(row: dict, previous: dict | None) -> bool:
    """Safety precheck for a development-only high-level yaw command."""
    deltas = pose_deltas(row["pose"])
    if any(abs(deltas[key]) > TOLERANCE[key] for key in ("x_m", "y_m", "trunk_z_m")):
        return False
    if abs(deltas["heading_rad"]) > .35:
        return False
    if not attitude_ok(row):
        return False
    return fresh_after(row, previous)


def attitude_ok(row: dict) -> bool:
    return all(type(row.get(key)) in (int, float) and
               math.isfinite(row[key]) and abs(row[key]) <= .5
               for key in ("roll_rad", "pitch_rad"))


def fresh_after(row: dict, previous: dict | None) -> bool:
    for key in ("request_ns", "response_ns", "sim_time_s"):
        if key not in row or type(row[key]) not in (int, float) or not math.isfinite(row[key]):
            return False
    if (row["response_ns"] < row["request_ns"] or
            row["response_ns"] - row["request_ns"] > MAX_SAMPLE_AGE_S * 1e9):
        return False
    if previous is None:
        return True
    return (row["request_ns"] > previous["response_ns"] and
            row["response_ns"] > previous["response_ns"] and
            row["sim_time_s"] > previous["sim_time_s"])


def qualification(rows: list[dict], *, stop_ack_ns: int, health: dict,
                  applied_velocity: list[float]) -> dict:
    """Require 1 s of sequential fresh, stable, stopped, in-tolerance samples."""
    reasons = []
    if len(rows) != 21:
        reasons.append("sample_count")
    if health.get("healthy") is not True or health.get("degraded") is True:
        reasons.append("health")
    if (len(applied_velocity) < 3 or
            any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > .005
                for v in applied_velocity)):
        reasons.append("applied_motion")
    if rows:
        if rows[0].get("request_ns", 0) <= stop_ack_ns:
            reasons.append("before_stop_ack")
        if rows[-1].get("response_ns", 0) - rows[0].get("response_ns", 0) < .95e9:
            reasons.append("short_dwell")
    previous = None
    headings = []
    for row in rows:
        if not fresh_after(row, previous):
            reasons.append("stale_pose")
        if not attitude_ok(row):
            reasons.append("attitude")
        try:
            delta = pose_deltas(row["pose"])
            if any(abs(delta[key]) > TOLERANCE[key] for key in TOLERANCE):
                reasons.append("pose_tolerance")
            if abs(delta["heading_rad"]) > HEADING_GUARD_RAD:
                reasons.append("heading_guard")
            headings.append(row["pose"]["heading_rad"])
        except (KeyError, TypeError, ValueError):
            reasons.append("invalid_pose")
        previous = row
    if headings and max(abs(wrapped_delta(v, headings[0])) for v in headings) > MAX_HEADING_DRIFT_RAD:
        reasons.append("heading_drift")
    return {"schema_version": "p8-03-r2-reset-gate-v1",
            "result": "PASS" if not reasons else "FAIL",
            "reasons": sorted(set(reasons)), "reference": REFERENCE,
            "tolerance": TOLERANCE, "heading_guard_rad": HEADING_GUARD_RAD,
            "sample_count": len(rows)}
