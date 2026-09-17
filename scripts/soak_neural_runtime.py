#!/usr/bin/env python3
"""Run zero and bounded 10-minute-neural-time P3 soaks."""

import json
import os
from pathlib import Path
import platform
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from microduck_connectome.neural_model import load_model_config, model_config_sha256
from microduck_connectome.soak import run_soak


def main():
    config = load_model_config(ROOT / "config" / "neural_model_v1.json")
    runs = [run_soak(config, mode="zero"), run_soak(config, mode="bounded")]
    report = {
        "schema_version": "p3-07-soak-v1",
        "dataset": "male-cns:v1.0",
        "fixture_kind": "synthetic_matched_scale",
        "workload_sha256": "297f11c6248142fc89c875d7547574a7c97e44eb46335069af82a1935a4540d9",
        "neural_config_sha256": model_config_sha256(config),
        "runtime_backend": "python-cpu-float32-contract",
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "runs": runs,
        "all_healthy": all(run["healthy"] for run in runs),
        "nonfinite_detected": any(run["nonfinite_detected"] for run in runs),
    }
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
