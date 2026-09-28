"""Standalone, raw-only scorer for P8-03-R7 official startup capture."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics

EVENTS = ("BODY_REACHABLE", "ROBOTD_REACHABLE", "POLICY_HELD",
          "POLICY_STAND", "FIRST_NONZERO_APPLIED", "FIRST_POSE_DEVIATION",
          "UP_EXIT", "STAND_SETTLED")
POSE_KEYS = ("sim_time_s", "x_m", "y_m", "trunk_z_m", "heading_rad",
             "roll_rad", "pitch_rad")


def finite(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def wrap(delta: float) -> float:
    return math.atan2(math.sin(delta), math.cos(delta))


def matrix(protocol: dict) -> list[dict]:
    if (protocol.get("schema_version") != "p8-03-r7-startup-interval-v1" or
            protocol.get("development_only") is not True or
            protocol.get("development_reset_id_first") != 888400 or
            protocol.get("development_reset_id_last") != 888495 or
            protocol.get("reset_count") != 96 or
            protocol.get("block_count") != 12 or
            protocol.get("resets_per_block") != 8 or
            protocol.get("reset_id_semantics") != "unique_label_only" or
            protocol.get("simulator_rng_seeded") is not False or
            protocol.get("no_robot_move") is not True or
            protocol.get("no_correction_command") is not True or
            protocol.get("no_explicit_policy_load") is not True or
            protocol.get("pose_deviation") != {
                "consecutive_fresh_samples": 2, "planar_m": .002,
                "z_m": .002, "heading_rad": .02,
                "baseline": "first fresh body sample at BODY_REACHABLE"} or
            protocol.get("applied_nonzero") != {
                "consecutive_distinct_robotd_states": 2,
                "abs_component_threshold": .0001} or
            protocol.get("final_reference_read_only") != {
                "x_m": .03457887954384973,
                "y_m": .0010909211238251523,
                "trunk_z_m": .11587609862790209,
                "heading_rad": .11693358424258107} or
            protocol.get("unchanged_final_envelope_read_only") != {
                "x_m": .03, "y_m": .03, "trunk_z_m": .025,
                "heading_rad": .08}):
        raise ValueError("R7 frozen protocol mismatch")
    return [{"id": f"T{i:02d}", "development_reset_id": 888400 + i,
             "order": i, "block": i // 8} for i in range(96)]


def read_journal(path: Path) -> list[dict]:
    data = path.read_bytes()
    if not data or not data.endswith(b"\n"):
        raise ValueError("empty or torn raw journal")
    rows = [json.loads(line) for line in data.splitlines()]
    if any(type(row) is not dict or row.get("sample_index") != i or
           not finite(row.get("host_monotonic_ns")) or
           not finite(row.get("host_utc_ns"))
           for i, row in enumerate(rows)):
        raise ValueError("raw journal chronology/index invalid")
    if any(b["host_monotonic_ns"] < a["host_monotonic_ns"]
           for a, b in zip(rows, rows[1:])):
        # Fsync order and event receipt order may differ across threads, but a
        # persisted row is stamped inside the lock, so inversion is a defect.
        raise ValueError("raw journal host clock inverted")
    return rows


def body_pose_from_packet(packet_text: str) -> dict:
    packet = json.loads(packet_text)
    trunk, quat = packet["trunk"], packet["imu"]["quat"]
    sim_time = packet["sim_time"]
    if (type(trunk) is not list or len(trunk) != 3 or
            type(quat) is not list or len(quat) != 4 or
            not all(finite(v) for v in trunk + quat + [sim_time])):
        raise ValueError("invalid official body packet")
    w, x, y, z = quat
    return {"sim_time_s": float(sim_time), "x_m": trunk[0], "y_m": trunk[1],
            "trunk_z_m": trunk[2],
            "heading_rad": math.atan2(2*(w*z + x*y), 1-2*(y*y+z*z)),
            "roll_rad": math.atan2(2*(w*x + y*z), 1-2*(x*x+y*y)),
            "pitch_rad": math.asin(max(-1., min(1., 2*(w*y-z*x)))),
            "imu_quat_wxyz": quat,
            "joint_positions": packet.get("positions"),
            "joint_velocities": packet.get("velocities"),
            "currents_ma": packet.get("currents_ma"),
            "contact_or_gait": packet.get("contacts", packet.get("gait"))}


def pose_agrees(row: dict) -> bool:
    try:
        expected = body_pose_from_packet(row["pose"]["raw_body_packet"])
        actual = row["pose"]
        return (all(finite(actual.get(k)) and math.isclose(
                    actual[k], expected[k], abs_tol=1e-10, rel_tol=0)
                    for k in POSE_KEYS) and
                all(actual.get(k) == expected[k] for k in (
                    "imu_quat_wxyz", "joint_positions", "joint_velocities",
                    "currents_ma", "contact_or_gait")))
    except (KeyError, ValueError, TypeError, IndexError):
        return False


def source_ns(row: dict) -> int:
    """Host monotonic receipt time of the source, before journal/fsync latency."""
    return {"body_sample": lambda: row["pose"]["response_ns"],
            "robotd_state": lambda: row["received_ns"],
            "robotd_health": lambda: row["received_ns"],
            "body_reachable": lambda: row["reached_ns"],
            "robotd_reachable": lambda: row["connected_ns"],
            "up_exit": lambda: row["observed_exit_ns"],
            "process_log": lambda: row["received_ns"]}.get(
                row["kind"], lambda: row["host_monotonic_ns"])()


def _event(name: str, row: dict | None, *, status: str = "OBSERVED",
           preceding: dict | None = None) -> dict:
    if row is None:
        return {"name": name, "status": status, "source_sample_index": None,
                "host_monotonic_ns": None, "interval_start_ns": None,
                "interval_end_ns": None}
    time_ns = source_ns(row)
    return {"name": name, "status": status,
            "source_sample_index": row["sample_index"],
            "host_monotonic_ns": time_ns,
            "interval_start_ns": (row["last_alive_poll_ns"]
                                  if row["kind"] == "up_exit" else
                                  source_ns(preceding or row)),
            "interval_end_ns": time_ns}


def pose_deviates(pose: dict, base: dict, protocol: dict) -> bool:
    threshold = protocol["pose_deviation"]
    return (math.hypot(pose["x_m"]-base["x_m"],
                       pose["y_m"]-base["y_m"]) >= threshold["planar_m"] or
            abs(pose["trunk_z_m"]-base["trunk_z_m"]) >= threshold["z_m"] or
            abs(wrap(pose["heading_rad"]-base["heading_rad"])) >=
            threshold["heading_rad"])


def settled_candidate(body: list[dict], up_exit_ns: int,
                      protocol: dict) -> dict | None:
    if not body or source_ns(body[-1]) < up_exit_ns + int(
            protocol["post_up_min_capture_s"] * 1e9):
        return None
    window_ns = int(protocol["settle_window_s"] * 1e9)
    for start in body:
        if source_ns(start) < up_exit_ns + int(.5e9):
            continue
        end_ns = source_ns(start) + window_ns
        if end_ns > source_ns(body[-1]):
            break
        window = [r for r in body if source_ns(start) <=
                  source_ns(r) <= end_ns]
        if (len(window) < 10 or
                source_ns(window[-1]) -
                source_ns(start) < window_ns - int(.06e9)):
            continue
        first = start["pose"]
        if all(math.hypot(r["pose"]["x_m"]-first["x_m"],
                          r["pose"]["y_m"]-first["y_m"]) <=
               protocol["settle_max_planar_m"] and
               abs(r["pose"]["trunk_z_m"]-first["trunk_z_m"]) <=
               protocol["settle_max_z_m"] and
               abs(wrap(r["pose"]["heading_rad"]-first["heading_rad"])) <=
               protocol["settle_max_heading_rad"] for r in window):
            return start
    return None


def derive_timeline(rows: list[dict], protocol: dict) -> dict:
    body = [r for r in rows if r["kind"] == "body_sample"]
    states = [r for r in rows if r["kind"] == "robotd_state"]
    lookup = lambda kind: next((r for r in rows if r["kind"] == kind), None)
    timeline = {}
    for name, kind in (("BODY_REACHABLE", "body_reachable"),
                       ("ROBOTD_REACHABLE", "robotd_reachable"),
                       ("UP_EXIT", "up_exit")):
        row = lookup(kind)
        timeline[name] = _event(name, row, status="MISSING" if row is None else "OBSERVED")
    for name, policy in (("POLICY_HELD", "held"), ("POLICY_STAND", "stand")):
        row = next((r for r in states if r["state"].get("policy") == policy), None)
        preceding = states[states.index(row)-1] if row is not None and states.index(row) else None
        timeline[name] = _event(name, row, status="MISSING" if row is None else "OBSERVED",
                                preceding=preceding)
    nonzero = None
    limit = protocol["applied_nonzero"]["abs_component_threshold"]
    for a, b in zip(states, states[1:]):
        av = a["state"].get("move", {}).get("applied", [])
        bv = b["state"].get("move", {}).get("applied", [])
        if (a["state"].get("t_ns") != b["state"].get("t_ns") and
                len(av) == len(bv) == 3 and
                any(abs(v) > limit for v in av) and
                any(abs(v) > limit for v in bv)):
            nonzero = (a, b)
            break
    timeline["FIRST_NONZERO_APPLIED"] = _event(
        "FIRST_NONZERO_APPLIED", nonzero[0] if nonzero else None,
        status="OBSERVED" if nonzero else "NOT_OBSERVED",
        preceding=states[states.index(nonzero[0])-1] if nonzero and
        states.index(nonzero[0]) else None)
    deviation = None
    if body:
        baseline = body[0]["pose"]
        for a, b in zip(body, body[1:]):
            if (b["pose"]["sim_time_s"] > a["pose"]["sim_time_s"] and
                    pose_deviates(a["pose"], baseline, protocol) and
                    pose_deviates(b["pose"], baseline, protocol)):
                deviation = (a, b)
                break
    timeline["FIRST_POSE_DEVIATION"] = _event(
        "FIRST_POSE_DEVIATION", deviation[0] if deviation else None,
        status="OBSERVED" if deviation else "NOT_OBSERVED",
        preceding=body[body.index(deviation[0])-1] if deviation and
        body.index(deviation[0]) else None)
    up_exit = lookup("up_exit")
    settled = settled_candidate(body, source_ns(up_exit), protocol) if up_exit else None
    timeline["STAND_SETTLED"] = _event(
        "STAND_SETTLED", settled,
        status="OBSERVED" if settled else "MISSING",
        preceding=body[body.index(settled)-1] if settled and body.index(settled) else None)
    return timeline


def final_flags(pose: dict, protocol: dict) -> list[str]:
    ref = protocol["final_reference_read_only"]
    bounds = protocol["unchanged_final_envelope_read_only"]
    return [name for name, outside in (
        ("OUTSIDE_X", abs(pose["x_m"]-ref["x_m"]) > bounds["x_m"]),
        ("OUTSIDE_Y", abs(pose["y_m"]-ref["y_m"]) > bounds["y_m"]),
        ("OUTSIDE_Z", abs(pose["trunk_z_m"]-ref["trunk_z_m"]) > bounds["trunk_z_m"]),
        ("OUTSIDE_HEADING", abs(wrap(pose["heading_rad"]-ref["heading_rad"])) >
         bounds["heading_rad"])) if outside]


def event_relation(first: dict, second: dict) -> str:
    if first["status"] != "OBSERVED" or second["status"] != "OBSERVED":
        return "NOT_OBSERVED"
    if first["interval_end_ns"] < second["interval_start_ns"]:
        return "BEFORE"
    if second["interval_end_ns"] < first["interval_start_ns"]:
        return "AFTER"
    return "ORDER_UNRESOLVED_INTERVAL_OVERLAP"


def trial_metrics(rows: list[dict], protocol: dict) -> dict:
    body = [r for r in rows if r["kind"] == "body_sample"]
    states = [r for r in rows if r["kind"] == "robotd_state"]
    timeline = derive_timeline(rows, protocol)
    event_order = {
        "POLICY_STAND_vs_FIRST_POSE_DEVIATION": event_relation(
            timeline["POLICY_STAND"], timeline["FIRST_POSE_DEVIATION"]),
        "FIRST_NONZERO_APPLIED_vs_FIRST_POSE_DEVIATION": event_relation(
            timeline["FIRST_NONZERO_APPLIED"], timeline["FIRST_POSE_DEVIATION"]),
        "FIRST_NONZERO_APPLIED_vs_POLICY_STAND": event_relation(
            timeline["FIRST_NONZERO_APPLIED"], timeline["POLICY_STAND"])}
    up_ns = timeline["UP_EXIT"]["host_monotonic_ns"]
    c_ns = source_ns(states[0]) if states else None
    c = next((r for r in body if c_ns is not None and
              source_ns(r) >= c_ns), None)
    a = next((r for r in body if up_ns is not None and
              source_ns(r) >= up_ns), None)
    c_to_a = None
    if c and a:
        cp, ap = c["pose"], a["pose"]
        dx, dy = ap["x_m"]-cp["x_m"], ap["y_m"]-cp["y_m"]
        c_to_a = {"dx_m": dx, "dy_m": dy, "planar_m": math.hypot(dx, dy),
                  "dz_m": ap["trunk_z_m"]-cp["trunk_z_m"],
                  "heading_rad": wrap(ap["heading_rad"]-cp["heading_rad"]),
                  "c_body_sample_index": c["sample_index"],
                  "a_body_sample_index": a["sample_index"]}
    final = body[-5:] if len(body) >= 5 else body
    final_pose = None
    if final:
        anchor = final[0]["pose"]["heading_rad"]
        final_pose = {key: statistics.median(r["pose"][key] for r in final)
                      for key in ("x_m", "y_m", "trunk_z_m")}
        final_pose["heading_rad"] = anchor + statistics.median(
            wrap(r["pose"]["heading_rad"]-anchor) for r in final)
    trajectory = None
    if body:
        base = body[0]["pose"]
        speeds = [math.hypot(b["pose"]["x_m"]-a["pose"]["x_m"],
                             b["pose"]["y_m"]-a["pose"]["y_m"]) /
                  (b["pose"]["sim_time_s"]-a["pose"]["sim_time_s"])
                  for a, b in zip(body, body[1:])
                  if b["pose"]["sim_time_s"] > a["pose"]["sim_time_s"]]
        trajectory = {
            "peak_planar_from_sit_m": max(math.hypot(
                r["pose"]["x_m"]-base["x_m"],
                r["pose"]["y_m"]-base["y_m"]) for r in body),
            "peak_abs_heading_from_sit_rad": max(abs(wrap(
                r["pose"]["heading_rad"]-base["heading_rad"])) for r in body),
            "peak_planar_speed_mps": max(speeds, default=0.),
            "min_z_m": min(r["pose"]["trunk_z_m"] for r in body),
            "max_z_m": max(r["pose"]["trunk_z_m"] for r in body)}
    return {"timeline": timeline, "event_order": event_order,
            "c_to_a": c_to_a,
            "trajectory": trajectory,
            "settled_pose": final_pose,
            "final_flags": final_flags(final_pose, protocol) if final_pose else [],
            "body_sample_count": len(body), "robotd_state_count": len(states),
            "max_body_gap_s": max(((source_ns(b)-
                                  source_ns(a))/1e9
                                  for a, b in zip(body, body[1:])), default=None)}


def verify_trial(record: dict, expected: dict, rows: list[dict],
                 protocol: dict) -> tuple[bool, str]:
    if any(record.get(key) != value for key, value in expected.items()):
        return False, "reset identity/order mismatch"
    if (not rows or rows[-1]["kind"] != "cleanup" or
            record.get("cleanup_stop", {}).get("result") != "PASS" or
            record.get("down_after_exit") != 0 or
            record.get("final_probe", {}).get("result") != "PASS"):
        return False, "cleanup/down/probe missing"
    if (record.get("move_count") != 0 or any(r["kind"] in (
            "move", "command_request", "robot.move", "correction",
            "explicit_policy_load") for r in rows)):
        return False, "forbidden command path recorded"
    body = [r for r in rows if r["kind"] == "body_sample"]
    states = [r for r in rows if r["kind"] == "robotd_state"]
    notifications = [r for r in rows if r["kind"] == "robotd_raw_notification"]
    by_index = {r["sample_index"]: r for r in rows}
    if not body:
        return False, "no durable body samples"
    for index, r in enumerate(body):
        p = r.get("pose", {})
        if (r.get("body_index") != index or not pose_agrees(r) or
                not all(finite(p.get(k)) for k in ("request_ns", "response_ns")) or
                not 0 <= (p["response_ns"]-p["request_ns"])/1e9 <=
                protocol["max_body_response_age_s"] or
                not all(finite(r.get(k)) for k in (
                    "socket_probe_start_ns", "socket_probe_end_ns")) or
                type(r.get("robotd_socket_available")) is not bool):
            return False, "body packet/index/timing invalid"
    for index, r in enumerate(states):
        try:
            state = json.loads(r["raw_state_line"])
            raw_source = by_index.get(r.get("raw_notification_index"))
            if (r.get("state_index") != index or state.get("method") != "robot.state" or
                    state["params"] != r["state"] or
                    raw_source is None or raw_source["kind"] != "robotd_raw_notification" or
                    raw_source["sample_index"] >= r["sample_index"] or
                    raw_source["raw_line"] != r["raw_state_line"] or
                    raw_source["received_ns"] != r["received_ns"] or
                    not finite(r["state"]["t_ns"]) or
                    not isinstance(r["state"].get("move", {}).get("applied"), list) or
                    len(r["state"]["move"]["applied"]) != 3):
                return False, "robotd state raw/index invalid"
        except (KeyError, TypeError, ValueError):
            return False, "robotd state unreadable"
    paired_notifications = {r.get("raw_notification_index") for r in states}
    for notification in notifications:
        try:
            parsed = json.loads(notification["raw_line"])
            if not isinstance(parsed, dict):
                raise ValueError("notification is not an object")
            if (parsed.get("method") == "robot.state" and
                    notification["sample_index"] not in paired_notifications):
                return False, "unpaired raw robotd state notification"
        except (ValueError, TypeError):
            if record.get("result") == "OBSERVED":
                return False, "malformed raw robotd notification in observed trial"
    for sample in body:
        state_ref = sample.get("snapshot_state_index")
        health_ref = sample.get("snapshot_health_index")
        if state_ref is not None:
            source = by_index.get(state_ref)
            if (source is None or source["kind"] != "robotd_state" or
                    state_ref >= sample["sample_index"] or
                    sample.get("policy") != source["state"].get("policy") or
                    sample.get("requested") != source["state"].get("move", {}).get("requested") or
                    sample.get("applied") != source["state"].get("move", {}).get("applied") or
                    sample.get("limited_by") != source["state"].get("move", {}).get("limited_by") or
                    sample.get("safety") != source["state"].get("safety") or
                    not finite(sample.get("snapshot_state_age_s")) or
                    abs(sample["snapshot_state_age_s"] -
                        (sample["pose"]["response_ns"]-source["received_ns"])/1e9) > 1e-9):
                return False, "body/state snapshot linkage invalid"
        if health_ref is not None:
            source = by_index.get(health_ref)
            if (source is None or source["kind"] != "robotd_health" or
                    health_ref >= sample["sample_index"] or
                    sample.get("health") != source.get("health")):
                return False, "body/health snapshot linkage invalid"
    if record.get("result") != "OBSERVED":
        return record.get("result") in ("SAFETY_FAIL", "DATA_INTEGRITY_FAIL",
                                        "INFRA_FAIL"), record.get("result", "unknown")
    if (record.get("down_before_exit") != 0 or record.get("up_exit") != 0 or
            len(states) < 10 or len(body) < 50 or
            record.get("capture_end_reason") != "STAND_SETTLED"):
        return False, "successful lifecycle/capture incomplete"
    if any(source_ns(r) > r["host_monotonic_ns"] for r in rows
           if r["kind"] in ("body_sample", "robotd_state", "robotd_health",
                            "body_reachable", "robotd_reachable", "up_exit",
                            "process_log")):
        return False, "source timestamp after durable journal timestamp"
    kinds = ("reset_start", "official_down", "official_up_started",
             "body_reachable", "robotd_reachable", "up_exit",
             "capture_end", "cleanup")
    loc = {kind: [i for i, r in enumerate(rows) if r["kind"] == kind]
           for kind in kinds}
    if (any(len(v) != 1 for v in loc.values()) or
            not (loc["reset_start"][0] < loc["official_down"][0] <
                 loc["official_up_started"][0] < loc["body_reachable"][0] <
                 body[0]["sample_index"] < loc["robotd_reachable"][0] <
                 loc["up_exit"][0] < loc["capture_end"][0] < loc["cleanup"][0]) or
            rows[loc["official_down"][0]].get("exit") != 0 or
            rows[loc["up_exit"][0]].get("exit") != 0 or
            not finite(rows[loc["up_exit"][0]].get("last_alive_poll_ns")) or
            rows[loc["up_exit"][0]]["last_alive_poll_ns"] >
            source_ns(rows[loc["up_exit"][0]]) or
            source_ns(body[-1]) <
            source_ns(rows[loc["up_exit"][0]]) + int(
                protocol["post_up_min_capture_s"] * 1e9)):
        return False, "lifecycle event order/timing invalid"
    if (source_ns(body[0]) -
            source_ns(rows[loc["body_reachable"][0]]) >
            protocol["max_body_gap_s"] * 1e9 or
            any((source_ns(b)-source_ns(a)) >
                protocol["max_body_gap_s"] * 1e9
                for a, b in zip(body, body[1:])) or
            any(b["pose"]["sim_time_s"] < a["pose"]["sim_time_s"]
                for a, b in zip(body, body[1:]))):
        return False, "continuous body capture gap/clock failure"
    if (source_ns(states[0]) <
            source_ns(rows[loc["robotd_reachable"][0]]) or
            any(b["state"]["t_ns"] < a["state"]["t_ns"] or
                source_ns(b)-source_ns(a) >
                protocol["max_robotd_state_age_s"] * 1e9
                for a, b in zip(states, states[1:])
                if source_ns(b) <=
                source_ns(rows[loc["up_exit"][0]]))):
        return False, "robotd state stream gap/clock failure"
    reached_ns = source_ns(rows[loc["robotd_reachable"][0]])
    if any(sample.get("snapshot_state_index") is None or
           sample.get("snapshot_health_index") is None or
           source_ns(sample) - source_ns(by_index[
               sample["snapshot_state_index"]]) >
               protocol["max_robotd_state_age_s"] * 1e9 or
           source_ns(sample) - source_ns(by_index[
               sample["snapshot_health_index"]]) >
               protocol["max_health_age_s"] * 1e9
           for sample in body if source_ns(sample) > reached_ns +
           int(.25e9)):
        return False, "body has stale or missing robotd snapshot"
    if not any(r["kind"] == "process_log" and
               "standing up" in r.get("line", "") for r in rows):
        return False, "official stand lifecycle log absent"
    snapshots = [r for r in rows if r["kind"] == "daemon_log_snapshot"]
    if (len(snapshots) != 2 or
            {r.get("source") for r in snapshots} != {"body.log", "duck-a.log"} or
            any(type(r.get("available")) is not bool or
                not finite(r.get("captured_ns")) or
                r["captured_ns"] > r["host_monotonic_ns"]
                for r in snapshots)):
        return False, "daemon log availability evidence missing"
    timeline = derive_timeline(rows, protocol)
    if (any(timeline[name]["status"] != "OBSERVED" for name in (
            "BODY_REACHABLE", "ROBOTD_REACHABLE", "POLICY_HELD",
            "POLICY_STAND", "FIRST_POSE_DEVIATION", "UP_EXIT",
            "STAND_SETTLED")) or
            record.get("metrics") != trial_metrics(rows, protocol)):
        return False, "required timeline or raw-derived metrics missing"
    recorded = {r["name"]: r["event"] for r in rows if r["kind"] == "timeline_event"}
    if (set(recorded) != set(EVENTS) or
            any(recorded[name] != timeline[name] for name in EVENTS)):
        return False, "timeline events do not match raw samples"
    return True, "OBSERVED"


def stats(values: list[float]) -> dict:
    return {"min": min(values), "max": max(values),
            "mean": statistics.mean(values), "median": statistics.median(values),
            "std": statistics.stdev(values) if len(values) > 1 else 0.0}


def score(protocol: dict, records: list[dict], root: Path) -> dict:
    expected = matrix(protocol)
    checks, valid = [], []
    for plan, record in zip(expected, records):
        try:
            rows = read_journal(root / plan["id"] / "samples.jsonl")
            good, reason = verify_trial(record, plan, rows, protocol)
            if good and record.get("result") == "OBSERVED":
                for snapshot in (r for r in rows if r["kind"] == "daemon_log_snapshot"):
                    path = root / plan["id"] / f"official-{snapshot['source']}"
                    if snapshot["available"]:
                        if (not path.is_file() or path.stat().st_size != snapshot.get("bytes") or
                                hashlib.sha256(path.read_bytes()).hexdigest() != snapshot.get("sha256")):
                            good, reason = False, "daemon log snapshot/file mismatch"
                            break
                    elif path.exists():
                        good, reason = False, "daemon log unexpectedly present"
                        break
        except (OSError, ValueError, TypeError, KeyError) as error:
            good, reason, rows = False, f"raw unreadable: {error}", []
        checks.append({"id": plan["id"], "valid_raw": good,
                       "reason": reason, "result": record.get("result")})
        if good and record.get("result") == "OBSERVED":
            valid.append((record, record["metrics"]))
    complete = (len(records) == len(expected) and
                all(records[i].get("id") == expected[i]["id"]
                    for i in range(len(records))))
    inside = sum(not metrics["final_flags"] for _, metrics in valid)
    c_to_a = [m["c_to_a"] for _, m in valid if m["c_to_a"]]
    event_order = {}
    for _, metrics in valid:
        for pair, relation in metrics["event_order"].items():
            category = f"{pair}:{relation}"
            event_order[category] = event_order.get(category, 0) + 1
    root_class = "UNRESOLVED"
    if len(valid) == 96 and event_order.get(
            "POLICY_STAND_vs_FIRST_POSE_DEVIATION:BEFORE", 0) >= 87:
        root_class = "B_ROBOTD_STAND_TRANSITION_ASSOCIATED"
    passed = complete and len(valid) == 96 and all(
        c["valid_raw"] and c["result"] == "OBSERVED" for c in checks)
    outliers = [{"id": record["id"], "flags": m["final_flags"],
                 "first_deviation_ns": m["timeline"]["FIRST_POSE_DEVIATION"]["host_monotonic_ns"],
                 "c_to_a": m["c_to_a"]} for record, m in valid if m["final_flags"]]
    groups = {"inside": [m for _, m in valid if not m["final_flags"]],
              "outside": [m for _, m in valid if m["final_flags"]]}
    outlier_pattern = {"classification": "NOT_REPRODUCED" if not outliers else
                       "DESCRIPTIVE_COMPARISON_ONLY", "outside_count": len(outliers),
                       "groups": {name: {"count": len(values),
                           "median_c_to_a_planar_m": statistics.median(
                               m["c_to_a"]["planar_m"] for m in values)
                           if values else None,
                           "median_c_to_a_heading_rad": statistics.median(
                               m["c_to_a"]["heading_rad"] for m in values)
                           if values else None,
                           "median_policy_to_pose_s": statistics.median(
                               (m["timeline"]["FIRST_POSE_DEVIATION"]["host_monotonic_ns"] -
                                m["timeline"]["POLICY_STAND"]["host_monotonic_ns"])/1e9
                               for m in values) if values else None,
                           "median_peak_planar_from_sit_m": statistics.median(
                               m["trajectory"]["peak_planar_from_sit_m"]
                               for m in values) if values else None,
                           "median_peak_abs_heading_from_sit_rad": statistics.median(
                               m["trajectory"]["peak_abs_heading_from_sit_rad"]
                               for m in values) if values else None,
                           "median_peak_planar_speed_mps": statistics.median(
                               m["trajectory"]["peak_planar_speed_mps"]
                               for m in values) if values else None}
                                  for name, values in groups.items()}}
    return {"schema_version": "p8-03-r7-raw-score-v1",
            "result": "PASS" if passed else "FAIL", "planned": 96,
            "attempted": len(records), "valid_resets": len(valid),
            "inside_final_envelope": inside,
            "outside_final_envelope": len(valid)-inside,
            "outliers": outliers, "event_order_counts": event_order,
            "outlier_pattern": outlier_pattern,
            "c_to_a_distributions": {key: stats([r[key] for r in c_to_a])
                                     for key in ("dx_m", "dy_m", "planar_m",
                                                 "dz_m", "heading_rad")}
                                     if c_to_a else {},
            "root_cause_class": root_class if passed else "UNRESOLVED",
            "actuator_causality_established": False,
            "reference_change_eligible": False,
            "correction_strategy_eligible": False,
            "reset_id_semantics": "UNIQUE_LABEL_ONLY",
            "simulator_rng_seeded": False,
            "raw_verification": checks,
            "per_reset": {record["id"]: metrics for record, metrics in valid}}


def score_root(root: Path) -> dict:
    protocol = json.loads((root / "protocol.json").read_text())
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest.get("schema_version") != "p8-03-r7-manifest-v1":
        raise ValueError("manifest schema mismatch")
    listed = {item["path"] for item in manifest["files"]}
    actual = {path.relative_to(root).as_posix() for path in root.rglob("*")
              if path.is_file() and path.name not in
              ("manifest.json", "gate.json")}
    if (listed != actual or len(listed) != len(manifest["files"]) or
            any(Path(name).is_absolute() or ".." in Path(name).parts
                for name in listed)):
        raise ValueError("manifest inventory mismatch")
    for item in manifest["files"]:
        data = (root / item["path"]).read_bytes()
        if (len(data) != item["bytes"] or
                hashlib.sha256(data).hexdigest() != item["sha256"] or
                len(data.splitlines()) != item["record_count"]):
            raise ValueError(f"manifest mismatch: {item['path']}")
    records = []
    for plan in matrix(protocol):
        path = root / plan["id"] / "trace.json"
        if not path.exists():
            break
        records.append(json.loads(path.read_text()))
    result = score(protocol, records, root)
    preflight = json.loads((root / "preflight.json").read_text())
    result["preflight_result"] = preflight.get("result")
    if result["preflight_result"] != "PASS":
        result["result"] = "FAIL"
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence_root", type=Path)
    args = parser.parse_args()
    print(json.dumps(score_root(args.evidence_root), sort_keys=True))
