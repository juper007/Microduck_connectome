"""Prospective P8-03 moving-body precondition, version 1.

This evaluates a dedicated, durable robotd diagnostic stream. Historical
timestamp-based P8-03 lineage and TPR2A-001 evidence are deliberately separate.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from microduck_connectome.g8_r5d_metrics import first_sustained, pose_speeds


class CausalPreconditionError(RuntimeError):
    pass


def _uint(value, name):
    if type(value) is not int or value < 0:
        raise CausalPreconditionError(f"{name} missing or invalid")
    return value


def evaluate_causal_precondition(
    diagnostic_path: Path, poses: list[dict], *, pre_move_tick: int,
    stop_sent_ns: int, gate: dict, allowed_policies=frozenset({"walk"}),
) -> dict:
    """Require exact generation lineage and frozen physical gate before eligibility.

    The first tick whose source sensor read follows the stop request is a
    delivery barrier, not an attribution of the stop generation. Every earlier
    tick is checked, including frames delivered after the stop request. A
    terminal diagnostic failure rejects the acquisition.
    """
    _uint(pre_move_tick, "pre_move_tick")
    _uint(stop_sent_ns, "stop_sent_ns")
    rows = [json.loads(line) for line in Path(diagnostic_path).read_text().splitlines()]
    if any(row.get("kind") == "diagnostic.failure" for row in rows):
        raise CausalPreconditionError("diagnostic stream failed")
    requests, acks, states = {}, {}, []
    previous_tick = previous_generation = previous_source = None
    for row in rows:
        kind = row.get("kind")
        if kind == "robot.move.request":
            wire = json.loads(row["wire"])
            ident = wire.get("id")
            if (ident in requests or wire.get("method") != "robot.move"
                    or type(ident) not in (str, int)):
                raise CausalPreconditionError("invalid or duplicate move request")
            requests[ident] = wire
        elif kind == "robot.move.ack":
            wire = json.loads(row["wire"])
            ident = wire.get("id")
            if ident not in requests or ident in acks:
                raise CausalPreconditionError("unpaired or duplicate move ACK")
            result = wire.get("result")
            if not isinstance(result, dict) or result.get("accepted") is not True:
                raise CausalPreconditionError("move ACK rejected")
            generation = _uint(result.get("accepted_move_generation"), "accepted generation")
            if not generation:
                raise CausalPreconditionError("zero accepted generation")
            acks[ident] = (generation, requests[ident])
        elif kind == "robot.state":
            state = row["state"]
            tick = _uint(state.get("control_tick_sequence"), "control tick")
            generation = _uint(state.get("consumed_move_generation"), "consumed generation")
            source = _uint(state.get("t_ns"), "source timestamp")
            received = _uint(row.get("received_at_ns"), "received timestamp")
            if (previous_tick is not None and tick != previous_tick + 1):
                raise CausalPreconditionError("diagnostic tick gap or regression")
            if previous_generation is not None and generation < previous_generation:
                raise CausalPreconditionError("generation regression")
            if previous_source is not None and source <= previous_source:
                raise CausalPreconditionError("source timestamp stalled or regressed")
            if source == 0 or received < source or received - source > gate["maximum_state_age_ms"] * 1e6:
                raise CausalPreconditionError("state not fresh")
            states.append(row)
            previous_tick, previous_generation, previous_source = tick, generation, source
    if not states or len(acks) != len(requests):
        raise CausalPreconditionError("incomplete state or request/ACK ledger")
    positive = {}
    for generation, request in acks.values():
        velocity = request.get("params", {}).get("vx")
        if type(velocity) not in (int, float) or not math.isfinite(velocity) or velocity <= 0:
            raise CausalPreconditionError("accepted move is not positive")
        if generation in positive:
            raise CausalPreconditionError("duplicate accepted generation")
        positive[generation] = request
    if not positive:
        raise CausalPreconditionError("no accepted positive move")
    consumed = {r["state"]["consumed_move_generation"] for r in states}
    superseded = sorted(n for n in positive if n not in consumed)
    first = next((r for r in states if
                  r["state"]["control_tick_sequence"] > pre_move_tick and
                  r["state"]["consumed_move_generation"] in positive), None)
    if first is None:
        raise CausalPreconditionError("no causal consumed positive move")
    first_ns = first["received_at_ns"]
    first_index = states.index(first)
    barrier_index = next((i for i in range(first_index + 1, len(states)) if
                          states[i]["state"]["t_ns"] > stop_sent_ns), None)
    if barrier_index is None:
        raise CausalPreconditionError("post-stop source-time delivery barrier missing")
    final_move_generation = max(positive)
    stop_index = next((i for i in range(first_index + 1, len(states)) if
                       states[i]["state"]["consumed_move_generation"] >
                       final_move_generation), None)
    if stop_index is None:
        raise CausalPreconditionError("zero-intent generation transition missing")
    stop_state = states[stop_index]["state"]
    if (states[stop_index]["received_at_ns"] < stop_sent_ns or
            stop_state["consumed_move_generation"] != final_move_generation + 1 or
            stop_state.get("move", {}).get("requested") != [0.0, 0.0, 0.0]):
        raise CausalPreconditionError("unexpected generation at zero-intent transition")
    if any(r["state"]["consumed_move_generation"] != final_move_generation + 1 or
           r["state"].get("move", {}).get("requested") != [0.0, 0.0, 0.0]
           for r in states[stop_index:barrier_index + 1]):
        raise CausalPreconditionError("generation changed before delivery barrier")
    window = states[first_index:stop_index]
    if not window or window[0] is not first:
        raise CausalPreconditionError("causal window incomplete")
    deadman_count = fault_count = 0
    for row in window:
        state = row["state"]
        generation = state["consumed_move_generation"]
        move = state.get("move", {})
        limited = move.get("limited_by")
        safety = state.get("safety", {})
        if generation not in positive:
            raise CausalPreconditionError("unattributed generation inside window")
        if not isinstance(limited, list) or not isinstance(safety, dict):
            raise CausalPreconditionError("missing limiter or safety state")
        deadman_count += "deadman" in limited
        fault_count += (bool(set(limited) - {"deadman"}) or bool(safety.get("fallen"))
                        or bool(safety.get("limp")))
        if deadman_count or fault_count:
            raise CausalPreconditionError("deadman, fault, or safety in causal window")
        requested, applied = move.get("requested"), move.get("applied")
        if (state.get("policy") not in allowed_policies or
                not isinstance(requested, list) or not isinstance(applied, list) or
                len(requested) != 3 or len(applied) != 3 or
                type(requested[0]) not in (int, float) or requested[0] <= 0 or
                type(applied[0]) not in (int, float) or
                applied[0] < gate["minimum_fresh_applied_vx_mps"]):
            raise CausalPreconditionError("invalid causal moving state")
    pre_stop_window = [r for r in window if r["received_at_ns"] <= stop_sent_ns]
    if not pre_stop_window:
        raise CausalPreconditionError("no observed causal state before stop")
    last_state_ns = pre_stop_window[-1]["received_at_ns"]
    duration_ns = last_state_ns - first_ns
    if duration_ns < gate["duration_s"] * 1e9:
        raise CausalPreconditionError("causal duration below frozen minimum")
    if stop_sent_ns - last_state_ns > gate["maximum_state_age_ms"] * 1e6:
        raise CausalPreconditionError("final causal state stale")
    if pre_stop_window[-1]["state"]["move"]["applied"][0] < gate["minimum_fresh_applied_vx_mps"]:
        raise CausalPreconditionError("fresh applied vx below frozen minimum")
    request_times = [_uint(r.get("sent_at_ns"), "move sent time") for r in rows
                     if r.get("kind") == "robot.move.request" and
                     first_ns <= r.get("sent_at_ns", -1) <= stop_sent_ns]
    if len(request_times) < math.ceil(gate["duration_s"] * 1000 / gate["command_period_ms"]):
        raise CausalPreconditionError("too few moving commands in causal window")
    if any(b <= a or b - a > gate["command_period_ms"] * 1e6 * 1.5
           for a, b in zip(request_times, request_times[1:])):
        raise CausalPreconditionError("command cadence gap")
    if (request_times[0] - first_ns > gate["command_period_ms"] * 1e6 * 1.5 or
            stop_sent_ns - request_times[-1] > gate["command_period_ms"] * 1e6 * 1.5):
        raise CausalPreconditionError("command cadence edge gap")
    points = [p for p in poses if first_ns <= p["timestamp_ns"] <= stop_sent_ns]
    if len(points) < 3 or stop_sent_ns - points[-1]["timestamp_ns"] > gate["maximum_pose_age_ms"] * 1e6:
        raise CausalPreconditionError("fresh official pose missing")
    if any(p.get("raw_body_packet") is None or
           p["timestamp_ns"] - _uint(p.get("request_ns"), "pose request") >
           gate["maximum_pose_age_ms"] * 1e6 for p in points):
        raise CausalPreconditionError("official raw pose missing")
    displacement = math.hypot(points[-1]["x_m"] - points[0]["x_m"],
                              points[-1]["y_m"] - points[0]["y_m"])
    speeds = pose_speeds(points, window_ms=100, max_window_ms=140)
    confirmed = first_sustained(speeds, threshold_mps=gate["minimum_pose_speed_mps"],
                                duration_ms=gate["minimum_speed_sustain_ms"], at_or_above=True)
    if displacement < gate["minimum_trunk_displacement_m"] or confirmed is None:
        raise CausalPreconditionError("physical movement below frozen minimum")
    valid_speeds = sorted(r["pose_speed_mps"] for r in speeds if r["pose_speed_mps"] is not None)
    return {"schema_version": "p8-03-causal-precondition-v1", "result": "PASS",
            "accepted_move_generations": sorted(positive),
            "superseded_before_consumption": superseded,
            "first_consumed_generation": first["state"]["consumed_move_generation"],
            "first_causal_tick": first["state"]["control_tick_sequence"],
            "causal_window_duration_s": duration_ns / 1e9,
            "deadman_count_in_window": deadman_count, "fault_count_in_window": fault_count,
            "tick_gap_count": 0, "command_count": len(request_times),
            "physical_displacement_m": displacement,
            "minimum_pose_speed_mps": valid_speeds[0],
            "median_pose_speed_mps": valid_speeds[len(valid_speeds) // 2],
            "final_prearm_eligibility": True}
