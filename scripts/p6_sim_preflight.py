#!/usr/bin/env python3
"""Preflight the pinned official MicroDuck simulator environment for P6-01."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess


def _run(args, *, cwd=None):
    try:
        return subprocess.run(
            args,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _git_head(path):
    result = _run(["git", "rev-parse", "HEAD"], cwd=path)
    if result is None or result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value if len(value) == 40 else None


def _module_available(python, module):
    result = _run([
        str(python),
        "-c",
        "import importlib.util,sys;sys.exit(0 if importlib.util.find_spec(sys.argv[1]) else 1)",
        module,
    ])
    return result is not None and result.returncode == 0


def probe_environment(*, microduck, microduck_rl, versions):
    versions = json.loads(Path(versions).read_text(encoding="utf-8"))
    expected_microduck = versions["upstream"]["microduck"]["commit"]
    expected_rl = versions["upstream"]["microduck_rl"]["commit"]

    microduck = Path(microduck)
    microduck_rl = Path(microduck_rl)
    rl_python = microduck_rl / ".venv" / "bin" / "python"
    duck_sim = microduck / "scripts" / "duck-sim"

    actual_microduck = _git_head(microduck) if microduck.is_dir() else None
    actual_rl = _git_head(microduck_rl) if microduck_rl.is_dir() else None

    checks = {
        "microduck_checkout_present": microduck.is_dir(),
        "microduck_commit_matches": actual_microduck == expected_microduck,
        "microduck_rl_checkout_present": microduck_rl.is_dir(),
        "microduck_rl_commit_matches": actual_rl == expected_rl,
        "duck_sim_present": duck_sim.is_file(),
        "rl_venv_python_present": rl_python.is_file(),
        "cargo_present": shutil.which("cargo") is not None,
        "rustc_present": shutil.which("rustc") is not None,
        "uv_present": shutil.which("uv") is not None,
        "mujoco_importable_in_rl_venv": (
            rl_python.is_file() and _module_available(rl_python, "mujoco")
        ),
        "onnxruntime_importable_in_rl_venv": (
            rl_python.is_file() and _module_available(rl_python, "onnxruntime")
        ),
    }

    return {
        "schema_version": "p6-sim-preflight-v1",
        "expected": {
            "microduck_commit": expected_microduck,
            "microduck_rl_commit": expected_rl,
        },
        "observed": {
            "microduck_commit": actual_microduck,
            "microduck_rl_commit": actual_rl,
        },
        "checks": checks,
        "ready": all(checks.values()),
        "official_commands": {
            "launch": "scripts/duck-sim",
            "health": "scripts/duck-sim ctl health",
            "shutdown": "scripts/duck-sim down",
        },
        "note": "ready=true is prerequisite evidence only; P6-01 still requires an actual launch and real robotd health response.",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--microduck", default=str(Path.home() / "Pollen" / "microduck"))
    parser.add_argument("--microduck-rl", default=str(Path.home() / "Pollen" / "microduck_rl"))
    parser.add_argument("--versions", default="config/versions.json")
    args = parser.parse_args()

    result = probe_environment(
        microduck=args.microduck,
        microduck_rl=args.microduck_rl,
        versions=args.versions,
    )
    print(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False))
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
