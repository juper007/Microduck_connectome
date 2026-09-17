#!/usr/bin/env python3
"""Run zero and bounded 10-minute-neural-time Phase 3 soaks."""

import json
import os
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from microduck_connectome.neural_model import load_model_config, model_config_sha256
from microduck_connectome.soak import run_soak
from microduck_connectome.workload_identity import soak_workload_definition, workload_sha256


def _git_head():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return None


def main():
    config = load_model_config(ROOT / "config" / "neural_model_v1.json")
    workload = soak_workload_definition(timestep_ms=config["timestep_ms"])
    runs = [run_soak(config, mode="zero"), run_soak(config, mode="bounded")]
    report = {
        "schema_version": "p3-07-soak-v3",
        "dataset": "male-cns:v1.0",
        "fixture_kind": "synthetic_matched_scale",
        "workload_definition": workload,
        "workload_sha256": workload_sha256(workload),
        "neural_config_sha256": model_config_sha256(config),
        "source_commit_sha": _git_head(),
        "runtime_backend": "python-cpu-float32-contract",
        "random_seed": "none",
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
