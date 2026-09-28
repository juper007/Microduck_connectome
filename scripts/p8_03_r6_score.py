"""Standalone raw scorer for the P8-03-R6 SIT reset pose diagnostic."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics

STAGES = ("A_UP_COMPLETE", "B_BODY_REACHABLE", "C_ROBOTD_REACHABLE",
          "D_POLICY_LOADED", "E_STOP_ACK", "F_SHORT_SETTLE", "G_FINAL_PLATEAU")
PAIRS = (("B_BODY_REACHABLE", "C_ROBOTD_REACHABLE"),
         ("C_ROBOTD_REACHABLE", "A_UP_COMPLETE"),
         ("A_UP_COMPLETE", "D_POLICY_LOADED"),
         ("D_POLICY_LOADED", "E_STOP_ACK"),
         ("E_STOP_ACK", "F_SHORT_SETTLE"),
         ("F_SHORT_SETTLE", "G_FINAL_PLATEAU"))


def wrapped_delta(final: float, initial: float) -> float:
    return math.atan2(math.sin(final - initial), math.cos(final - initial))


def finite(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def raw_pose_matches(pose: dict) -> bool:
    """Recompute body pose independently from the retained official packet."""
    try:
        packet = json.loads(pose["raw_body_packet"])
        trunk, quat = packet["trunk"], packet["imu"]["quat"]
        sim_time = packet["sim_time"]
        if (not isinstance(trunk, list) or len(trunk) != 3 or
                not isinstance(quat, list) or len(quat) != 4 or
                not all(finite(v) for v in trunk + quat + [sim_time])):
            return False
        w, x, y, z = quat
        roll = math.atan2(2 * (w*x + y*z), 1 - 2 * (x*x + y*y))
        pitch = math.asin(max(-1., min(1., 2 * (w*y - z*x))))
        heading = math.atan2(2 * (w*z + x*y), 1 - 2 * (y*y + z*z))
        expected = {"sim_time_s": float(sim_time), "x_m": trunk[0],
                    "y_m": trunk[1], "trunk_z_m": trunk[2],
                    "roll_rad": roll, "pitch_rad": pitch,
                    "heading_rad": heading}
        return (pose["imu_quat_wxyz"] == quat and
                all(math.isclose(pose[key], value, abs_tol=1e-10, rel_tol=0)
                    for key, value in expected.items()))
    except (ValueError, TypeError, KeyError, IndexError):
        return False


def expected_matrix(protocol: dict) -> list[dict]:
    if (protocol.get("schema_version") != "p8-03-r6-sit-reset-pose-v1" or
            protocol.get("development_only") is not True or
            protocol.get("development_reset_id_first") != 888300 or
            protocol.get("development_reset_id_last") != 888347 or
            protocol.get("reset_count") != 48 or
            protocol.get("block_count") != 6 or
            protocol.get("resets_per_block") != 8 or
            protocol.get("reset_id_semantics") != "unique_label_only" or
            protocol.get("simulator_rng_seeded") is not False or
            protocol.get("no_robot_move") is not True or
            protocol.get("no_correction_command") is not True or
            protocol.get("checkpoint_labels") != list(STAGES) or
            protocol.get("plateau_samples") != 21 or
            protocol.get("final_reference") != {
                "x_m": .03457887954384973,
                "y_m": .0010909211238251523,
                "trunk_z_m": .11587609862790209,
                "heading_rad": .11693358424258107} or
            protocol.get("unchanged_final_envelope") != {
                "x_m": .03, "y_m": .03, "trunk_z_m": .025,
                "heading_rad": .08}):
        raise ValueError("R6 frozen protocol mismatch")
    return [{"id": f"S{i:02d}", "development_reset_id": 888300 + i,
             "order": i, "block": i // 8} for i in range(48)]


def read_journal(path: Path) -> list[dict]:
    raw = path.read_bytes()
    if not raw or not raw.endswith(b"\n"):
        raise ValueError("empty or torn raw journal")
    rows = [json.loads(line) for line in raw.splitlines()]
    if any(type(row) is not dict or row.get("sample_index") != i
           for i, row in enumerate(rows)):
        raise ValueError("nonconsecutive raw journal index")
    return rows


def flags(pose: dict, protocol: dict) -> list[str]:
    ref, limit = protocol["final_reference"], protocol["unchanged_final_envelope"]
    checks = (("OUTSIDE_X", abs(pose["x_m"] - ref["x_m"]) > limit["x_m"]),
              ("OUTSIDE_Y", abs(pose["y_m"] - ref["y_m"]) > limit["y_m"]),
              ("OUTSIDE_Z", abs(pose["trunk_z_m"] - ref["trunk_z_m"]) > limit["trunk_z_m"]),
              ("OUTSIDE_HEADING", abs(wrapped_delta(
                  pose["heading_rad"], ref["heading_rad"])) > limit["heading_rad"]))
    return [name for name, outside in checks if outside]


def settled_pose(rows: list[dict]) -> dict:
    tail = [row["pose"] for row in rows[-5:]]
    anchor = tail[0]["heading_rad"]
    return {key: statistics.median(p[key] for p in tail)
            for key in ("x_m", "y_m", "trunk_z_m")} | {
        "heading_rad": anchor + statistics.median(
            wrapped_delta(p["heading_rad"], anchor) for p in tail)}


def stage_views(rows: list[dict], protocol: dict) -> dict:
    grouped = {stage: [row for row in rows if row.get("kind") == "pose" and
                       row.get("checkpoint") == stage] for stage in STAGES}
    if any(len(grouped[stage]) != (protocol["plateau_samples"] if stage ==
                                "G_FINAL_PLATEAU" else 1) for stage in STAGES):
        raise ValueError("checkpoint coverage incomplete")
    views = {stage: group[0]["pose"] for stage, group in grouped.items()
             if stage != "G_FINAL_PLATEAU"}
    views["G_FINAL_PLATEAU"] = settled_pose(grouped["G_FINAL_PLATEAU"])
    return views


def displacement(a: dict, b: dict) -> dict:
    dx, dy = b["x_m"] - a["x_m"], b["y_m"] - a["y_m"]
    return {"dx_m": dx, "dy_m": dy,
            "planar_m": math.hypot(dx, dy),
            "dz_m": b["trunk_z_m"] - a["trunk_z_m"],
            "heading_rad": wrapped_delta(b["heading_rad"], a["heading_rad"])}


def verify_trace(record: dict, expected: dict, rows: list[dict],
                 protocol: dict) -> tuple[bool, str]:
    if any(record.get(key) != expected[key] for key in expected):
        return False, "reset ID/order mismatch"
    if (record.get("cleanup_stop", {}).get("result") != "PASS" or
            record.get("down_after_exit") != 0 or
            record.get("final_probe", {}).get("result") != "PASS" or
            not rows or rows[-1].get("kind") != "cleanup"):
        return False, "cleanup/down/probe missing"
    if any(row.get("kind") in ("move", "command_request", "robot.move")
           for row in rows) or record.get("move_count", 0) != 0:
        return False, "motion command present"
    poses = [row for row in rows if row.get("kind") == "pose"]
    if not poses:
        return False, "no durable pose"
    for row in poses:
        pose = row.get("pose", {})
        if not all(finite(pose.get(key)) for key in (
                "request_ns", "response_ns", "sim_time_s", "x_m", "y_m",
                "trunk_z_m", "heading_rad", "roll_rad", "pitch_rad")):
            return False, "malformed pose"
        if (pose["response_ns"] < pose["request_ns"] or
                pose["response_ns"] - pose["request_ns"] >
                protocol["max_pose_response_age_s"] * 1e9 or
                not isinstance(pose.get("raw_body_packet"), str) or
                not isinstance(pose.get("imu_quat_wxyz"), list) or
                len(pose["imu_quat_wxyz"]) != 4 or
                not finite(row.get("host_monotonic_ns"))):
            return False, "pose packet/timestamp invalid"
        if not raw_pose_matches(pose):
            return False, "derived pose disagrees with raw body packet"
        state = row.get("robotd_state")
        if row["checkpoint"] == "B_BODY_REACHABLE":
            if state is not None:
                return False, "body-only checkpoint has robotd state"
        elif record.get("result") == "OBSERVED":
            if (not isinstance(state, dict) or
                    not finite(row.get("robotd_t_ns")) or
                    not finite(row.get("state_received_ns")) or
                    pose["response_ns"] - row["state_received_ns"] >
                    protocol["max_state_age_s"] * 1e9 or
                    not isinstance(row.get("health"), dict)):
                return False, "robotd state/health missing or stale"
    if record.get("result") == "OBSERVED":
        if (record.get("down_before_exit") != 0 or record.get("up_exit") != 0 or
                record.get("policy_load_exit") != 0 or
                record.get("policy_readback_exit") != 0 or
                record.get("initial_stop", {}).get("result") != "PASS"):
            return False, "successful lifecycle missing"
        try:
            views = stage_views(rows, protocol)
        except ValueError as error:
            return False, str(error)
        selected = {stage: [row for row in poses if row["checkpoint"] == stage]
                    for stage in STAGES}
        if (any(row["checkpoint_index"] != index for stage in STAGES
                for index, row in enumerate(selected[stage])) or
                any(b["pose"]["sim_time_s"] <= a["pose"]["sim_time_s"]
                    for a, b in zip(poses, poses[1:])) or
                [row["checkpoint"] for row in poses] != [
                    "B_BODY_REACHABLE", "C_ROBOTD_REACHABLE", "A_UP_COMPLETE",
                    "D_POLICY_LOADED", "E_STOP_ACK", "F_SHORT_SETTLE"] +
                    ["G_FINAL_PLATEAU"] * protocol["plateau_samples"]):
            return False, "checkpoint order or simulator clock invalid"
        positions = {kind: [i for i, row in enumerate(rows) if row.get("kind") == kind]
                     for kind in ("reset_start", "official_up_started", "body_reachable", "up_complete",
                                  "policy_verified", "stop_ack", "cleanup")}
        if (any(len(values) != 1 for values in positions.values()) or
                not (positions["reset_start"][0] < positions["official_up_started"][0] <
                     positions["body_reachable"][0] <
                     selected["B_BODY_REACHABLE"][0]["sample_index"] <
                     selected["C_ROBOTD_REACHABLE"][0]["sample_index"] <
                     positions["up_complete"][0] <
                     selected["A_UP_COMPLETE"][0]["sample_index"] <
                     positions["policy_verified"][0] <
                     selected["D_POLICY_LOADED"][0]["sample_index"] <
                     positions["stop_ack"][0] <
                     selected["E_STOP_ACK"][0]["sample_index"] <
                     selected["F_SHORT_SETTLE"][0]["sample_index"] <
                     selected["G_FINAL_PLATEAU"][0]["sample_index"] <
                     positions["cleanup"][0]) or
                type(rows[positions["body_reachable"][0]].get("robotd_socket_connectable")) is not bool or
                record.get("body_robotd_connectable") != rows[positions["body_reachable"][0]]["robotd_socket_connectable"] or
                rows[positions["stop_ack"][0]].get("result") != "PASS" or
                record.get("checkpoint_metrics") != checkpoint_metrics(views, protocol)):
            return False, "raw lifecycle/derived metrics mismatch"
        return True, "OBSERVED"
    if record.get("result") == "SAFETY_FAIL":
        trigger = record.get("trigger")
        if (not isinstance(trigger, dict) or
                trigger.get("pose_sample_index") not in
                {row["sample_index"] for row in poses} or
                not any(row.get("kind") == "safety_event" and
                        row.get("trigger") == trigger for row in rows) or
                not any(row.get("kind") == "safety_stop_ack" and
                        row.get("result") == "PASS" for row in rows)):
            return False, "safety trigger/stop missing"
        return True, "SAFETY_FAIL"
    return record.get("result") in ("DATA_INTEGRITY_FAIL", "INFRA_FAIL"), \
        record.get("result", "unknown")


def checkpoint_metrics(views: dict, protocol: dict) -> dict:
    return {"stage_flags": {stage: flags(pose, protocol)
                            for stage, pose in views.items()},
            "stage_drift": {f"{a}->{b}": displacement(views[a], views[b])
                            for a, b in PAIRS},
            "initial_to_final": displacement(views["A_UP_COMPLETE"],
                                              views["G_FINAL_PLATEAU"]),
            "final_classification": (flags(views["G_FINAL_PLATEAU"], protocol)
                                     or ["IN_ENVELOPE"])[0],
            "final_flags": flags(views["G_FINAL_PLATEAU"], protocol)}


def stats(values: list[float]) -> dict:
    return {"min": min(values), "max": max(values),
            "mean": statistics.mean(values), "median": statistics.median(values),
            "std": statistics.stdev(values) if len(values) > 1 else 0.0}


def order_diagnostics(valid: list[tuple[dict, dict]]) -> dict:
    """Descriptive block shifts and distinct pose groups, without RNG claims."""
    if not valid:
        return {}
    result = {}
    for stage in ("B_BODY_REACHABLE", "A_UP_COMPLETE", "G_FINAL_PLATEAU"):
        block_means = {}
        for block in range(6):
            group = [view[stage] for record, view in valid if record["block"] == block]
            if group:
                block_means[str(block)] = {
                    key: statistics.mean(p[key] for p in group)
                    for key in ("x_m", "y_m", "trunk_z_m", "heading_rad")}
        xs = [view[stage]["x_m"] for _, view in valid]
        ys = [view[stage]["y_m"] for _, view in valid]
        # Connected groups at 5 mm are a descriptive screen, not a mixture-model test.
        groups = []
        for x, y in sorted(zip(xs, ys)):
            match = next((group for group in groups
                          if any(math.hypot(x - gx, y - gy) <= .005
                                 for gx, gy in group)), None)
            if match is None:
                groups.append([])
                match = groups[-1]
            match.append((x, y))
        result[stage] = {"block_means": block_means,
                         "descriptive_xy_groups_5mm": len(groups),
                         "first_to_last_observed": displacement(
                             valid[0][1][stage], valid[-1][1][stage])}
    return result


def score(protocol: dict, records: list[dict], root: Path) -> dict:
    planned = expected_matrix(protocol)
    checks = []
    valid = []
    for expected, record in zip(planned, records):
        try:
            rows = read_journal(root / expected["id"] / "samples.jsonl")
            good, reason = verify_trace(record, expected, rows, protocol)
        except (OSError, ValueError, TypeError, KeyError) as error:
            good, reason = False, f"raw unreadable: {error}"
            rows = []
        checks.append({"id": expected["id"], "valid_raw": good,
                       "verification": reason, "result": record.get("result")})
        if good and record.get("result") == "OBSERVED":
            valid.append((record, stage_views(rows, protocol)))
    complete = (len(records) == len(planned) and
                all(record.get("id") == planned[i]["id"]
                    for i, record in enumerate(records)))
    distributions = {stage: {key: stats([view[stage][key] for _, view in valid])
                             for key in ("x_m", "y_m", "trunk_z_m", "heading_rad")}
                     for stage in STAGES} if valid else {}
    inside = sum(not record["checkpoint_metrics"]["final_flags"]
                 for record, _ in valid)
    outside = len(valid) - inside
    reset_deltas = {stage: [displacement(a[1][stage], b[1][stage])
                            for a, b in zip(valid, valid[1:])]
                    for stage in ("A_UP_COMPLETE", "G_FINAL_PLATEAU")}
    drift = {f"{a}->{b}": [record["checkpoint_metrics"]["stage_drift"][f"{a}->{b}"]
                            for record, _ in valid] for a, b in PAIRS}
    stage_associations = {name: {
        "median_planar_m": statistics.median(v["planar_m"] for v in values),
        "max_planar_m": max(v["planar_m"] for v in values),
        "count_over_2mm": sum(v["planar_m"] > .002 for v in values),
        "sample_count": len(values), "causal_status": "OBSERVATIONAL_ONLY"}
        for name, values in drift.items() if values}
    root_class = "UNRESOLVED"
    if len(valid) == 48 and all(record.get("body_robotd_connectable") is False
                                for record, _ in valid):
        b_poses = [view["B_BODY_REACHABLE"] for _, view in valid]
        span = max(max(p["x_m"] for p in b_poses) - min(p["x_m"] for p in b_poses),
                   max(p["y_m"] for p in b_poses) - min(p["y_m"] for p in b_poses))
        if (span > .005 and all(
                item["median_planar_m"] <= .002 and item["count_over_2mm"] <= 4
                for item in stage_associations.values())):
            root_class = "SIMULATOR_SPAWN_RESET_VARIABILITY_CANDIDATE"
    pass_gate = (complete and len(valid) == 48 and
                 all(check["valid_raw"] and check["result"] == "OBSERVED"
                     for check in checks))
    return {"schema_version": "p8-03-r6-raw-score-v1",
            "result": "PASS" if pass_gate else "FAIL", "planned": 48,
            "attempted": len(records), "valid_resets": len(valid),
            "in_envelope_count": inside, "outside_envelope_count": outside,
            "distributions": distributions, "checkpoint_drift": drift,
            "stage_associations": stage_associations,
            "reset_to_reset_deltas": reset_deltas,
            "order_diagnostics": order_diagnostics(valid),
            "root_cause_class": root_class if pass_gate else "UNRESOLVED",
            "per_reset": {record["id"]: record["checkpoint_metrics"]
                          for record, _ in valid},
            "raw_verification": checks,
            "reference_change_eligible": False,
            "correction_strategy_eligible": False,
            "reset_id_semantics": "UNIQUE_LABEL_ONLY",
            "simulator_rng_seeded": False,
            "development_only": True}


def score_root(root: Path, protocol_path: Path) -> dict:
    protocol = json.loads(protocol_path.read_text())
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest.get("schema_version") != "p8-03-r6-manifest-v1":
        raise ValueError("manifest schema mismatch")
    listed = {entry["path"] for entry in manifest["files"]}
    actual = {path.relative_to(root).as_posix() for path in root.rglob("*")
              if path.is_file() and path.name not in
              ("manifest.json", "gate.json", "run.json")}
    if (listed != actual or len(listed) != len(manifest["files"]) or
            any(Path(name).is_absolute() or ".." in Path(name).parts
                for name in listed)):
        raise ValueError("manifest inventory mismatch")
    for entry in manifest["files"]:
        data = (root / entry["path"]).read_bytes()
        if (len(data) != entry["bytes"] or
                hashlib.sha256(data).hexdigest() != entry["sha256"] or
                len(data.splitlines()) != entry["record_count"]):
            raise ValueError(f"manifest bytes/hash mismatch: {entry['path']}")
    records = []
    for expected in expected_matrix(protocol):
        path = root / expected["id"] / "trace.json"
        if not path.exists():
            break
        records.append(json.loads(path.read_text()))
    return score(protocol, records, root)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence_root", type=Path)
    args = parser.parse_args()
    print(json.dumps(score_root(args.evidence_root,
                                args.evidence_root / "protocol.json"),
                     sort_keys=True))
