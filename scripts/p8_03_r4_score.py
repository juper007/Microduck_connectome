"""Independent raw scorer for the frozen P8-03-R4 development diagnostic."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import statistics

from scripts.p6_motion_fixture import wrapped_delta

CONDITIONS = ("sham", "positive_low", "negative_low",
              "positive_high", "negative_high")
REFERENCE = {"x_m": .03457887954384973, "y_m": .0010909211238251523,
             "heading_rad": .11693358424258107, "trunk_z_m": .11587609862790209}


def expected_matrix(protocol: dict) -> list[dict]:
    if (protocol["schema_version"] != "p8-03-r4-actuator-pose-v1" or
            protocol["seed_first"] != 888100 or protocol["seed_last"] != 888129 or
            protocol["blocks"] != 6 or
            protocol["even_block"] != list(CONDITIONS) or
            protocol["odd_block"] != ["sham", "negative_low", "positive_low",
                                      "negative_high", "positive_high"] or
            protocol["sham_ticks_by_block"] != [5, 8, 5, 8, 5, 8] or
            protocol.get("development_only") is not True or
            protocol.get("dose") != {
                "low_ticks": 5, "high_ticks": 8, "tick_s": .02,
                "abs_vyaw_radps": .2, "vx_mps": 0., "vy_mps": 0.,
                "max_through_stop_s": .30, "max_command_integral_rad": .08,
                "ttl_s": .10} or
            protocol["pose"]["max_motion_xy_from_initial_m"] != .01 or
            protocol["measurement"]["minimum_abs_delta_rad"] != .005):
        raise ValueError("R4 matrix differs from frozen protocol")
    rows = []
    for block in range(6):
        for condition in (protocol["even_block"] if block % 2 == 0
                          else protocol["odd_block"]):
            ticks = (protocol["sham_ticks_by_block"][block] if condition == "sham"
                     else 5 if condition.endswith("_low") else 8)
            rows.append({"id": f"A{len(rows):02d}", "seed": 888100 + len(rows),
                         "block": block, "condition": condition, "ticks": ticks,
                         "vyaw_radps": 0. if condition == "sham" else
                         .2 if condition.startswith("positive") else -.2})
    return rows


def read_journal(path: Path) -> list[dict]:
    raw = path.read_bytes()
    if raw and not raw.endswith(b"\n"):
        raise ValueError("torn journal line")
    rows = [json.loads(line) for line in raw.splitlines()]
    if any(type(row) is not dict or row.get("sample_index") != i
           for i, row in enumerate(rows)):
        raise ValueError("nonconsecutive raw journal index")
    return rows


def _finite(value) -> bool:
    return type(value) in (float, int) and math.isfinite(value)


def _pose_record_valid(row: dict) -> bool:
    try:
        pose = row["pose"]
        required = ("request_ns", "response_ns", "sim_time_s", "x_m", "y_m",
                    "trunk_z_m", "heading_rad", "roll_rad", "pitch_rad")
        if not all(_finite(pose[key]) for key in required):
            return False
        if (pose["response_ns"] < pose["request_ns"] or
                pose["response_ns"] - pose["request_ns"] > 100_000_000 or
                abs(pose["roll_rad"]) > .5 or abs(pose["pitch_rad"]) > .5):
            return False
        if (not isinstance(pose["raw_body_packet"], str) or
                not isinstance(pose["imu_quat_wxyz"], list) or
                len(pose["imu_quat_wxyz"]) != 4):
            return False
        if (not isinstance(row["requested"], list) or
                not isinstance(row["applied"], list) or
                not all(_finite(v) for v in row["requested"] + row["applied"])):
            return False
        if not isinstance(row["limited_by"], list) or row["policy"] not in ("stand", "walk"):
            return False
        health = row["robotd_health"]
        if (not isinstance(health, dict) or health.get("healthy") is not True or
                health.get("degraded") is True or
                not _finite(row["robotd_health_received_ns"]) or
                pose["response_ns"] - row["robotd_health_received_ns"] > 100_000_000):
            return False
        if (not _finite(row["robot_t_ns"]) or
                not _finite(row["state_received_ns"]) or
                pose["response_ns"] - row["state_received_ns"] > 100_000_000 or
                row["safety"]["fallen"] or row["safety"]["limp"]):
            return False
        if (not _finite(row["displacement_from_reset_start_m"]) or
                not _finite(row["wrapped_heading_delta_rad"]) or
                "last_command_ack" not in row or "commanded_vyaw_radps" not in row):
            return False
        return True
    except (KeyError, TypeError, ValueError):
        return False


def _pose_record_retained(row: dict) -> bool:
    """An unsafe or malformed observation is still valid abort evidence."""
    pose = row.get("pose")
    return (isinstance(pose, dict) and
            all(key in pose for key in ("request_ns", "response_ns", "raw_body_packet",
                                         "sim_time_s", "x_m", "y_m", "trunk_z_m",
                                         "heading_rad", "roll_rad", "pitch_rad",
                                         "imu_quat_wxyz")) and
            all(key in row for key in ("requested", "applied", "limited_by", "policy",
                                       "robotd_health", "last_command_ack",
                                       "displacement_from_reset_start_m",
                                       "wrapped_heading_delta_rad")))


def verify_trace(record: dict, expected: dict, journal_rows: list[dict]) -> tuple[bool, str]:
    for key in ("id", "seed", "block", "condition", "ticks", "vyaw_radps"):
        if record.get(key) != expected[key]:
            return False, f"matrix mismatch {key}"
    if (record.get("cleanup_stop", {}).get("result") != "PASS" or
            record.get("down_after_exit") != 0 or
            record.get("final_probe", {}).get("result") != "PASS"):
        return False, "cleanup/down/probe missing"
    if not journal_rows or journal_rows[-1].get("kind") != "cleanup":
        return False, "raw cleanup event missing"
    cleanup = journal_rows[-1]
    if (cleanup.get("stop") != record["cleanup_stop"] or
            cleanup.get("down_exit") != record["down_after_exit"] or
            cleanup.get("final_probe") != record["final_probe"]):
        return False, "raw cleanup does not match trace"
    poses = {row["sample_index"]: row for row in journal_rows if row.get("kind") == "pose"}
    if not poses:
        return False, "no raw pose"
    if record.get("result") == "SAFETY_ABORT":
        trigger = record.get("trigger")
        if not isinstance(trigger, dict):
            return False, "safety abort missing trigger metadata"
        index = trigger.get("trigger_sample_index")
        if index not in poses or poses[index].get("pose") != trigger.get("trigger_pose"):
            return False, "threshold-triggering pose absent or altered"
        if not _pose_record_retained(poses[index]):
            return False, "threshold-triggering pose telemetry incomplete"
        previous = trigger.get("previous_sample_index")
        if previous is not None and (
                previous not in poses or poses[previous].get("pose") != trigger.get("previous_pose")):
            return False, "previous pose absent or altered"
        if ((record.get("pulses") and
             not any(x.get("kind") == "stop_ack" and x.get("result") == "PASS"
                     for x in journal_rows)) or
                any(x.get("kind") == "command_request" and
                    x["sample_index"] > index for x in journal_rows) or
                any(pulse.get("stop", {}).get("result") != "PASS"
                    for pulse in record.get("pulses", []))):
            return False, "safety abort stop or no-next-command evidence missing"
        if trigger.get("reason") == "command_induced_translation_bound_exceeded":
            pose = poses[index]
            prior = poses[previous] if previous is not None else None
            first = next(iter(poses.values()))
            measured = math.hypot(
                pose["pose"]["x_m"] - first["pose"]["x_m"],
                pose["pose"]["y_m"] - first["pose"]["y_m"])
            if (trigger.get("threshold") != .01 or
                    not measured > .01 or
                    not math.isclose(trigger.get("measured"), measured, abs_tol=1e-10) or
                    prior is None):
                return False, "translation crossing cannot be reconstructed"
        return True, "SAFETY_ABORT"
    if record.get("result") != "VALID":
        return False, "invalid reset"
    if (record.get("down_before_exit") != 0 or record.get("up_exit") != 0 or
            record.get("initial_stop", {}).get("result") != "PASS" or
            len(record.get("initial_plateau", [])) != 21 or
            len(record.get("pulses", [])) != 1):
        return False, "valid reset lifecycle incomplete"
    pulse = record["pulses"][0]
    ticks = expected["ticks"]
    if (pulse.get("vyaw_radps") != expected["vyaw_radps"] or
            pulse.get("ticks") != ticks or
            pulse.get("duration_s") != ticks * .02 or
            pulse.get("stop", {}).get("result") != "PASS" or
            not ticks * .02 <= pulse.get("active_through_stop_s", -1) <= .3 or
            len(pulse.get("requests", [])) != ticks or
            len(pulse.get("trajectory", [])) != ticks or
            len(pulse.get("post_stop_trajectory", [])) != 21 or
            len(pulse.get("plateau", [])) != 21):
        return False, "valid pulse shape/timing invalid"
    commands = [row for row in journal_rows if row.get("kind") == "command_request"]
    acknowledgements = [row for row in journal_rows if row.get("kind") == "command_ack"]
    stops = [row for row in journal_rows if row.get("kind") == "stop_ack"]
    if len(commands) != ticks or len(acknowledgements) != ticks or len(stops) != 1:
        return False, "raw command/ACK/stop count mismatch"
    if stops[0].get("result") != "PASS":
        return False, "raw stop failed"
    for index, (command, ack, saved) in enumerate(
            zip(commands, acknowledgements, pulse["requests"])):
        if (command.get("tick") != index or ack.get("tick") != index or
                command.get("vyaw_radps") != expected["vyaw_radps"] or
                command.get("vx_mps") != 0. or command.get("vy_mps") != 0. or
                ack.get("ack") != saved.get("ack") or
                ack.get("ack", {}).get("accepted") is not True or
                ack.get("ack_ns") - ack.get("call_ns") > 100_000_000):
            return False, "raw command or ACK mismatch"
    if any(not 10_000_000 <= b["call_ns"] - a["call_ns"] <= 30_000_000
           for a, b in zip(pulse["requests"], pulse["requests"][1:])):
        return False, "command cadence mismatch"
    phases = (record["initial_plateau"] + pulse["trajectory"] +
              pulse["post_stop_trajectory"] + pulse["plateau"])
    if any(row.get("sample_index") not in poses or
           row["pose"] != poses[row["sample_index"]]["pose"]
           for row in phases):
        return False, "scored pose missing from raw journal"
    if any(not _pose_record_valid(row) for row in phases):
        return False, "invalid raw pose or robotd telemetry"
    initial_pose = record["initial_plateau"][0]["pose"]
    if (abs(initial_pose["x_m"] - REFERENCE["x_m"]) > .03 or
            abs(initial_pose["y_m"] - REFERENCE["y_m"]) > .03 or
            abs(initial_pose["trunk_z_m"] - REFERENCE["trunk_z_m"]) > .025 or
            abs(wrapped_delta(initial_pose["heading_rad"], REFERENCE["heading_rad"])) > .35):
        return False, "initial pose outside inclusion"
    for row in phases:
        pose = row["pose"]
        displacement = math.hypot(pose["x_m"] - initial_pose["x_m"],
                                  pose["y_m"] - initial_pose["y_m"])
        if (displacement > .01 or
                not math.isclose(row["displacement_from_reset_start_m"],
                                 displacement, abs_tol=1e-10)):
            return False, "unsafe or inconsistent planar displacement"
    if expected["vyaw_radps"] != 0. and any(
            row["policy"] != "walk" for row in pulse["trajectory"][2:]):
        return False, "walk policy inactive during pulse"
    for plateau in (record["initial_plateau"], pulse["plateau"]):
        if (any(max(abs(v) for v in row["applied"]) > .005 for row in plateau) or
                abs(wrapped_delta(plateau[-1]["pose"]["heading_rad"],
                                  plateau[0]["pose"]["heading_rad"])) > .005):
            return False, "stopped plateau invalid"
    if any(max(abs(v) for v in row["applied"]) > .005
           for row in pulse["post_stop_trajectory"][9:]):
        return False, "motion persisted after stop"
    def median_heading(rows):
        anchor = rows[0]["pose"]["heading_rad"]
        return anchor + statistics.median(
            wrapped_delta(row["pose"]["heading_rad"], anchor) for row in rows[-5:])
    computed = wrapped_delta(median_heading(pulse["plateau"]),
                             median_heading(record["initial_plateau"]))
    if not math.isclose(record.get("delta_heading_rad"), computed, abs_tol=1e-10):
        return False, "saved heading response differs from raw"
    return True, "VALID"


def classify(condition: str, delta: float | None, floor: float,
             status: str) -> str:
    if status == "SAFETY_ABORT":
        return "SAFETY_ABORT"
    if status != "VALID" or delta is None:
        return "DATA_INTEGRITY_ABORT"
    if condition == "sham":
        return "SHAM"
    sign = 1 if condition.startswith("positive") else -1
    signed = sign * delta
    return "EXPECTED" if signed > floor else (
        "WRONG_SIGN" if signed < -floor else "INCONCLUSIVE")


def score(protocol: dict, records: list[dict], root: Path) -> dict:
    planned = expected_matrix(protocol)
    verified = []
    for expected, record in zip(planned, records):
        path = root / expected["id"] / "samples.jsonl"
        try:
            good, reason = verify_trace(record, expected, read_journal(path))
        except (OSError, ValueError, KeyError, TypeError) as error:
            good, reason = False, f"raw journal unreadable: {error}"
        verified.append({"id": expected["id"], "valid_raw": good,
                         "verification": reason, "result": record.get("result")})
    complete = (len(records) == len(planned) and
                all(a.get("id") == b["id"] for a, b in zip(records, planned)))
    shams = [abs(row["delta_heading_rad"]) for row in records
             if row.get("condition") == "sham" and row.get("result") == "VALID"
             and _finite(row.get("delta_heading_rad"))]
    floor = max(.005, max(shams, default=0.) + .002)
    classes = {
        row["id"]: classify(row["condition"], row.get("delta_heading_rad"),
                            floor, row.get("result", ""))
        for row in records if "id" in row and "condition" in row}
    cells = {condition: [
        row.get("delta_heading_rad") for row in records
        if row.get("condition") == condition and row.get("result") == "VALID"]
        for condition in CONDITIONS}
    pass_gate = (complete and len(verified) == 30 and
                 all(v["valid_raw"] and v["result"] == "VALID" for v in verified) and
                 all(len(cells[condition]) == 6 for condition in CONDITIONS) and
                 all(classes[row["id"]] == "EXPECTED" for row in records
                     if row["condition"] != "sham"))
    return {"schema_version": "p8-03-r4-raw-score-v1",
            "result": "PASS" if pass_gate else "FAIL",
            "planned": 30, "observed": len(records),
            "sham_floor_rad": floor,
            "sham_floor_final": len(shams) == 6,
            "classifications": classes, "cells": cells,
            "raw_verification": verified, "development_only": True}


def score_root(root: Path, protocol_path: Path) -> dict:
    protocol = json.loads(protocol_path.read_text())
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest.get("schema_version") != "p8-03-r4-manifest-v1":
        raise RuntimeError("manifest version mismatch")
    listed = {entry["path"] for entry in manifest["files"]}
    actual = {path.relative_to(root).as_posix() for path in root.rglob("*")
              if path.is_file() and path.name not in
              ("manifest.json", "gate.json", "run.json")}
    if (listed != actual or len(listed) != len(manifest["files"]) or
            any(Path(name).is_absolute() or ".." in Path(name).parts for name in listed)):
        raise RuntimeError("raw inventory mismatch")
    for entry in manifest["files"]:
        path = root / entry["path"]
        data = path.read_bytes()
        if (len(data) != entry["bytes"] or
                hashlib.sha256(data).hexdigest() != entry["sha256"] or
                len(data.splitlines()) != entry["record_count"]):
            raise RuntimeError(f"raw manifest mismatch: {entry['path']}")
    records = []
    for expected in expected_matrix(protocol):
        relative = f"{expected['id']}/trace.json"
        if relative not in listed:
            break
        records.append(json.loads((root / relative).read_text()))
    return score(protocol, records, root)
