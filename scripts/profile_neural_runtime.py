#!/usr/bin/env python3
"""Profile the P3 sparse runtime on the deterministic matched-scale fixture."""

import json
import os
from pathlib import Path
import platform
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from microduck_connectome.neural_model import load_model_config, model_config_sha256
from microduck_connectome.performance import profile_runtime


def main():
    config_path = ROOT / "config" / "neural_model_v1.json"
    config = load_model_config(config_path)
    report = profile_runtime(config)
    report.update({
        "schema_version": "p3-06-performance-v1",
        "fixture_kind": "synthetic_matched_scale",
        "dataset": "male-cns:v1.0",
        "neural_config_sha256": model_config_sha256(config),
        "workload_sha256": "297f11c6248142fc89c875d7547574a7c97e44eb46335069af82a1935a4540d9",
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "runtime_backend": "python-cpu-float32-contract",
    })
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
