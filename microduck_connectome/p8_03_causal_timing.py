"""Causal lineage checks for a prospective timing probe.

The CPDEV stop-bound v2 evaluator remains unchanged. This checks the same
generation, safety, qualification and physical gates at a live ARM boundary.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from .g8_r5d_metrics import first_sustained, pose_speeds


class CausalTimingError(ValueError):
    """The raw evidence does not prove a safe causal moving interval."""


def _uint(value, name):
    if type(value) is not int or value < 0:
        raise CausalTimingError(f"{name} missing or invalid")
    return value


def evaluate_causal_arm(path: Path, poses: list[dict], *, pre_move_tick: int,
                        arm_ns: int, gate: dict, scored_end_ns: int | None = None,
                        durable_rows: list[dict] | None = None) -> dict:
    """Validate causal acquisition and optionally the scored state stream."""
    _uint(pre_move_tick, "pre-move tick")
    _uint(arm_ns, "arm timestamp")
    if scored_end_ns is not None and scored_end_ns != arm_ns + 1_000_000_000:
        raise CausalTimingError("scored window must be exactly 1000 ms")
    rows = (durable_rows if durable_rows is not None else
            [json.loads(line) for line in Path(path).read_text().splitlines()
             if line.strip()])
    if any(row.get("kind") == "diagnostic.failure" for row in rows):
        raise CausalTimingError("diagnostic stream failed")
    requests, acks, states = {}, {}, []
    previous_tick = previous_generation = previous_source = None
    for row in rows:
        kind = row.get("kind")
        if kind == "robot.move.request":
            wire = json.loads(row["wire"])
            ident = wire.get("id")
            sent = _uint(row.get("sent_at_ns"), "move request time")
            vx = wire.get("params", {}).get("vx")
            if (type(ident) not in (str, int) or ident in requests or
                    wire.get("method") != "robot.move" or
                    type(vx) not in (int, float) or not math.isfinite(vx) or vx <= 0):
                raise CausalTimingError("invalid positive move request")
            requests[ident] = sent
        elif kind == "robot.move.ack":
            wire = json.loads(row["wire"])
            ident = wire.get("id")
            result = wire.get("result")
            received = _uint(row.get("received_at_ns"), "move ACK time")
            if (ident not in requests or ident in acks or
                    not isinstance(result, dict) or result.get("accepted") is not True or
                    received < requests[ident]):
                raise CausalTimingError("invalid or unpaired move ACK")
            generation = _uint(result.get("accepted_move_generation"), "accepted generation")
            if generation == 0 or generation in acks.values():
                raise CausalTimingError("duplicate or zero accepted generation")
            acks[ident] = generation
        elif kind == "robot.state":
            state = row.get("state")
            if not isinstance(state, dict):
                raise CausalTimingError("malformed state")
            tick = _uint(state.get("control_tick_sequence"), "control tick")
            generation = _uint(state.get("consumed_move_generation"), "consumed generation")
            source = _uint(state.get("t_ns"), "source time")
            received = _uint(row.get("received_at_ns"), "state receive time")
            if (previous_tick is not None and tick != previous_tick + 1 or
                    previous_generation is not None and generation < previous_generation or
                    previous_source is not None and source < previous_source or
                    source == 0 or received < source or
                    received - source > gate["maximum_state_age_ms"] * 1e6):
                raise CausalTimingError("tick, generation, or source freshness gap")
            previous_tick, previous_generation, previous_source = tick, generation, source
            states.append(row)
    if not states or len(requests) != len(acks):
        raise CausalTimingError("incomplete request, ACK, or state stream")
    generations = set(acks.values())
    first = next((i for i, row in enumerate(states) if
                  row["state"]["control_tick_sequence"] > pre_move_tick and
                  row["state"]["consumed_move_generation"] in generations), None)
    if first is None:
        raise CausalTimingError("no causal positive generation consumed")
    causal = [row for row in states[first:] if row["received_at_ns"] < arm_ns]
    if (not causal or causal[-1]["received_at_ns"] - causal[0]["received_at_ns"] <
            gate["duration_s"] * 1e9 or
            arm_ns - causal[-1]["received_at_ns"] >
            gate["maximum_state_age_ms"] * 1e6):
        raise CausalTimingError("causal duration or endpoint freshness failed")
    for row in causal:
        state = row["state"]
        move, safety = state.get("move"), state.get("safety")
        if not isinstance(move, dict) or not isinstance(safety, dict):
            raise CausalTimingError("malformed causal state")
        limited = move.get("limited_by", [])
        requested, applied = move.get("requested"), move.get("applied")
        if (state["consumed_move_generation"] not in generations or
                not isinstance(limited, list) or
                any(type(token) is not str for token in limited) or limited or
                type(safety.get("fallen")) is not bool or
                type(safety.get("limp")) is not bool or
                safety["fallen"] or safety["limp"] or
                state.get("policy") not in {"stand", "walk"} or
                not isinstance(requested, list) or not isinstance(applied, list) or
                len(requested) != 3 or len(applied) != 3 or
                any(type(x) not in (int, float) or not math.isfinite(x)
                    for x in requested + applied) or
                requested[0] <= 0 or applied[0] < 0):
            raise CausalTimingError("deadman, fault, safety, or malformed causal state")
    end_state = causal[-1]["state"]
    if (end_state["policy"] != "walk" or
            end_state["move"]["applied"][0] < gate["minimum_fresh_applied_vx_mps"]):
        raise CausalTimingError("fresh endpoint below frozen applied-vx gate")
    first_ns = causal[0]["received_at_ns"]
    command_times = sorted(sent for ident, sent in requests.items()
                           if ident in acks and first_ns <= sent < arm_ns)
    gap = gate["command_period_ms"] * 1e6 * 1.5
    if (len(command_times) < math.ceil(gate["duration_s"] * 1000 /
                                      gate["command_period_ms"]) or
            command_times[0] - first_ns > gap or arm_ns - command_times[-1] > gap or
            any(b <= a or b - a > gap for a, b in
                zip(command_times, command_times[1:]))):
        raise CausalTimingError("causal command count or cadence failed")
    points = sorted((p for p in poses if first_ns <= p.get("timestamp_ns", -1) < arm_ns),
                    key=lambda p: p["timestamp_ns"])
    if (len(points) < 3 or arm_ns - points[-1]["timestamp_ns"] >
            gate["maximum_pose_age_ms"] * 1e6 or
            any(p.get("raw_body_packet") is None or
                p["timestamp_ns"] - _uint(p.get("request_ns"), "pose request") >
                gate["maximum_pose_age_ms"] * 1e6 for p in points)):
        raise CausalTimingError("fresh official pose evidence missing")
    speeds = pose_speeds(points, window_ms=100, max_window_ms=140)
    qualifying = None
    for row in causal:
        state = row["state"]
        if (state["policy"] != "walk" or
                state["move"]["applied"][0] < gate["minimum_fresh_applied_vx_mps"]):
            continue
        pose = next((p for p in reversed(speeds)
                     if p["timestamp_ns"] <= row["received_at_ns"]), None)
        if (pose is not None and row["received_at_ns"] - pose["timestamp_ns"] <=
                gate["maximum_pose_age_ms"] * 1e6 and
                pose["pose_speed_mps"] is not None and
                pose["pose_speed_mps"] >= gate["minimum_pose_speed_mps"]):
            qualifying = row
            break
    if qualifying is None:
        raise CausalTimingError("no qualifying moving state")
    if any(row["state"]["policy"] != "walk" or
           row["state"]["move"]["applied"][0] <
           gate["minimum_fresh_applied_vx_mps"] for row in
           causal[causal.index(qualifying):]):
        raise CausalTimingError("qualifying motion interrupted")
    qualified = [p for p in points if p["timestamp_ns"] >= qualifying["received_at_ns"]]
    if len(qualified) < 3:
        raise CausalTimingError("qualified pose evidence missing")
    q_speeds = pose_speeds(qualified, window_ms=100, max_window_ms=140)
    displacement = math.hypot(qualified[-1]["x_m"] - qualified[0]["x_m"],
                              qualified[-1]["y_m"] - qualified[0]["y_m"])
    confirmed = first_sustained(q_speeds, threshold_mps=gate["minimum_pose_speed_mps"],
                                duration_ms=gate["minimum_speed_sustain_ms"],
                                at_or_above=True)
    if displacement < gate["minimum_trunk_displacement_m"] or confirmed is None:
        raise CausalTimingError("qualified physical movement failed")
    scored_count = 0
    if scored_end_ns is not None:
        if not any(row["state"]["t_ns"] >= scored_end_ns for row in states):
            raise CausalTimingError("post-window diagnostic drain barrier missing")
        scored = [row for row in states if arm_ns <= row["state"]["t_ns"] < scored_end_ns]
        if (not scored or scored[0]["state"]["t_ns"] - arm_ns > 40_000_000 or
                scored_end_ns - scored[-1]["state"]["t_ns"] > 40_000_000):
            raise CausalTimingError("scored diagnostic boundary gap")
        for row in scored:
            state = row["state"]
            move, safety = state.get("move"), state.get("safety")
            if (state["consumed_move_generation"] not in generations or
                    not isinstance(move, dict) or not isinstance(safety, dict) or
                    move.get("limited_by", []) != [] or
                    safety.get("fallen") is not False or
                    safety.get("limp") is not False or
                    state.get("policy") != "walk" or
                    not isinstance(move.get("applied"), list) or
                    move["applied"][0] < gate["minimum_fresh_applied_vx_mps"]):
                raise CausalTimingError("scored deadman, fault, safety, or generation gap")
        scored_count = len(scored)
    return {"result": "PASS", "duration_start": "FIRST_CAUSAL_TICK",
            "arm_ns": arm_ns,
            "first_causal_tick": causal[0]["state"]["control_tick_sequence"],
            "first_consumed_generation": causal[0]["state"]["consumed_move_generation"],
            "first_qualifying_tick": qualifying["state"]["control_tick_sequence"],
            "causal_duration_s": (causal[-1]["received_at_ns"] - first_ns) / 1e9,
            "postqualification_displacement_m": displacement,
            "qualified_sustain_ns": confirmed,
            "endpoint_applied_vx_mps": end_state["move"]["applied"][0],
            "prearm_command_count": len(command_times),
            "scored_state_count": scored_count}
