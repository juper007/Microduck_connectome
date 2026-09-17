#!/usr/bin/env python3
"""Profile Phase 3 sparse-runtime latency and process memory."""

import json
import os
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from microduck_connectome.neural_model import load_model_config, model_config_sha256
from microduck_connectome.performance import profile_runtime


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
    config_path = ROOT / "config" / "neural_model_v1.json"
    config = load_model_config(config_path)
    report = profile_runtime(config)
    report.update({
        "schema_version": "p3-06-performance-v2",
        "fixture_kind": "synthetic_matched_scale",
        "dataset": "male-cns:v1.0",
        "neural_config_sha256": model_config_sha256(config),
        "source_commit_sha": _git_head(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "runtime_backend": "python-cpu-float32-contract",
    })
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
