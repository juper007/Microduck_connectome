"""Record a Thor simulator pose before a P7 trial is allowed to start."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import platform
import socket
import time

from scripts.p6_telemetry_runtime_fixture import BodyReader
from microduck_connectome.target_scenario import wrap_angle


def evaluate_pose(body: dict, reference: dict) -> dict:
    heading_error = wrap_angle(body["heading_rad"] - reference["heading_rad"])
    trunk_z_error = body["trunk_z"] - reference["trunk_z_m"]
    values = (body["heading_rad"], body["trunk_z"],
              heading_error, trunk_z_error)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("nonfinite simulator pose")
    return {
        "measured_heading_rad": body["heading_rad"],
        "measured_trunk_z_m": body["trunk_z"],
        "reference_heading_rad": reference["heading_rad"],
        "reference_trunk_z_m": reference["trunk_z_m"],
        "heading_error_rad": heading_error,
        "trunk_z_error_m": trunk_z_error,
        "heading_tolerance_rad": reference["heading_tolerance_rad"],
        "trunk_z_tolerance_m": reference["trunk_z_tolerance_m"],
        "accepted": (abs(heading_error) <= reference["heading_tolerance_rad"]
                     and abs(trunk_z_error) <= reference["trunk_z_tolerance_m"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--body-port", type=int, required=True)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not socket.gethostname().startswith("jetsonthor") or platform.python_version_tuple()[:2] != ("3", "12"):
        raise RuntimeError("pose acquisition requires Thor Python 3.12")
    experiment = json.loads(args.experiment.read_text(encoding="utf-8"))
    body = BodyReader(args.body_port)
    try:
        measurement = body.read()
    finally:
        body.close()
    result = evaluate_pose(measurement, experiment["reset_reference"])
    result["schema_version"] = "p7-pretrial-pose-v1"
    result["sampled_monotonic_ns"] = time.monotonic_ns()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2,
                                      allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"accepted": result["accepted"],
                      "heading_error_rad": result["heading_error_rad"],
                      "trunk_z_error_m": result["trunk_z_error_m"]}, sort_keys=True))
    if not result["accepted"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
