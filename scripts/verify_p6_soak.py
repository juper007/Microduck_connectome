"""Independently verify a Thor P6-07 raw trace against its summary."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path


def verify(raw_path: Path, summary_path: Path) -> dict:
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary["execution_target"] != "Thor" or summary["result"] != "PASS":
        raise ValueError("summary is not a Thor PASS")
    if summary["wall_clock_duration_s"] < 600 or not summary["qualified_600s"]:
        raise ValueError("wall-clock duration is under 600 seconds")
    elapsed = (summary["ended_monotonic_ns"] - summary["started_monotonic_ns"]) / 1e9
    if abs(elapsed - summary["wall_clock_duration_s"]) > 1e-6:
        raise ValueError("duration does not match monotonic timestamps")
    digest = hashlib.sha256()
    count = gaps = bad_state = bad_requested = bad_sensor = bad_stop = nonfinite = 0
    first_ns = last_ns = None
    previous_time = previous_sequence = -1
    scenarios = Counter()
    with raw_path.open("rb") as handle:
        for line in handle:
            digest.update(line)
            record = json.loads(line)
            count += 1
            timestamp = record["timestamp_ns"]
            sequence = record["sequence"]
            if timestamp <= previous_time or sequence <= previous_sequence:
                raise ValueError(f"nonmonotonic telemetry at record {count}")
            if previous_sequence >= 0:
                gaps += max(0, sequence - previous_sequence - 1)
            previous_time, previous_sequence = timestamp, sequence
            first_ns = timestamp if first_ns is None else first_ns
            last_ns = timestamp
            scenario = record["trial_id"].split(":")[-1]
            scenarios[scenario] += 1
            required = (
                "perception", "stimulus_channels", "male_cns", "dn_activity",
                "pre_safety_intent", "post_safety_intent", "watchdog_state",
                "robot_facing_command_type", "robot_state",
            )
            if any(key not in record for key in required):
                raise ValueError(f"missing full-chain stage at record {count}")
            bad_state += record["robot_state"]["sample_timestamp_ns"] < timestamp
            command = [record["robot_facing_vx"], record["robot_facing_vy"], record["robot_facing_vyaw"]]
            nonfinite += any(not math.isfinite(value) for value in command)
            if abs(command[0]) > 0.08 or command[1] != 0.0 or abs(command[2]) > 0.50:
                raise ValueError(f"unsafe command at record {count}")
            bad_requested += any(
                abs(actual - expected) > 1e-9
                for actual, expected in zip(command, record["robot_state"]["requested_velocity"])
            )
            bad_sensor += scenario == "sensor_loss" and (
                record["perception"]["valid"] or any(record["stimulus_channels"].values())
                or any(command)
            )
            bad_stop += scenario == "stop" and (
                not record["robot_facing_stop"]
                or record["robotd_transport_result"] != "robot_stop_refreshed"
            )
    expected = summary["telemetry_artifact"]
    if digest.hexdigest() != expected["sha256"] or raw_path.stat().st_size != expected["bytes"]:
        raise ValueError("raw artifact hash or size differs from summary")
    if (count != expected["record_count"] or count != summary["telemetry_record_count"]
            or first_ns != expected["start_timestamp_ns"] or last_ns != expected["end_timestamp_ns"]):
        raise ValueError("record count or timestamp extent differs from summary")
    if gaps != summary["telemetry_gap_count"] or dict(scenarios) != summary["scenario_record_counts"]:
        raise ValueError("sequence gaps or scenario counts differ from summary")
    if any((bad_state, bad_requested, bad_sensor, bad_stop, nonfinite)):
        raise ValueError("raw trace has a state, command, sensor, stop or finite-value defect")
    if not all(summary["checks"].values()) or not summary["robotd_health"]["healthy"]:
        raise ValueError("summary contains a failed safety or robotd health check")
    return {
        "result": "PASS", "records": count, "sha256": digest.hexdigest(),
        "wall_clock_duration_s": elapsed, "sequence_gaps": gaps,
        "bad_post_command_state": bad_state, "bad_requested": bad_requested,
        "bad_sensor": bad_sensor, "bad_stop": bad_stop, "nonfinite": nonfinite,
        "scenarios": dict(sorted(scenarios.items())),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.raw, args.summary), sort_keys=True))


if __name__ == "__main__":
    main()
