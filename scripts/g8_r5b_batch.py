"""Three fresh official Thor resets for the frozen G8-R5b integration protocol."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import socket
import subprocess
import sys
import time

from scripts.p7_pretrial_acquisition import run_logged, validate_loaded_walk_policy


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--microduck", type=Path, required=True)
    ap.add_argument("--microduck-rl", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--sim-state", type=Path, required=True)
    ap.add_argument("--body-port", type=int, required=True)
    a = ap.parse_args()
    if not socket.gethostname().startswith("jetsonthor") or platform.python_version_tuple()[:2] != ("3", "12"):
        raise RuntimeError("official Thor Python 3.12 required")
    root = a.root.resolve()
    head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    if subprocess.check_output(["git", "-C", str(root), "status", "--porcelain"], text=True).strip():
        raise RuntimeError("batch requires clean committed source")
    protocol_path = root / "config/g8_r5b_motion_stop_v1.json"
    protocol = json.loads(protocol_path.read_text())
    if protocol_path.read_bytes() != subprocess.check_output([
        "git", "-C", str(root), "show", "HEAD:config/g8_r5b_motion_stop_v1.json"]):
        raise RuntimeError("uncommitted protocol bytes")
    a.output.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ)
    env.update({
        "PATH": str(a.microduck.parent / "rustup/toolchains/stable-aarch64-unknown-linux-gnu/bin")
                + os.pathsep + env["PATH"],
        "DUCK_SIM_VIEWER": "0", "DUCK_SIM_STATE": str(a.sim_state),
        "DUCK_SIM_RL": str(a.microduck_rl), "DUCK_SIM_PORT": str(a.body_port),
        "PYTHONPATH": str(root),
    })
    sim = a.microduck / "scripts/duck-sim"
    started_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    rows = []
    final_down = {}
    try:
        for index, seed in enumerate(protocol["scenario_seeds"]):
            folder = a.output / f"trial-{index + 1:02d}-{seed}"
            folder.mkdir()
            row = {"trial_index": index, "seed": seed, "trial_started": False,
                   "pretrial_logs": {}}
            for name, command in (
                ("down", [str(sim), "down"]),
                ("up", [str(sim), "up"]),
                ("policy_load", [str(sim), "ctl", "policy", "load", "walk",
                                 protocol["walking_policy_path"]]),
                ("policy_readback", [str(sim), "ctl", "policy", "list", "--json"]),
            ):
                log = folder / ("policy-readback.json" if name == "policy_readback" else name + ".log")
                exit_code = run_logged(command, log, env=env)
                row["pretrial_logs"][name] = {"exit": exit_code, "sha256": sha(log),
                                               "bytes": log.stat().st_size}
                if exit_code != 0:
                    row["failure"] = f"official_{name}_failed"
                    break
                if name == "policy_readback":
                    try:
                        validate_loaded_walk_policy(json.loads(log.read_text()),
                                                    Path(protocol["walking_policy_path"]),
                                                    protocol["walking_policy_sha256"])
                    except (ValueError, KeyError, TypeError, OSError) as error:
                        row["failure"] = f"policy_readback_mismatch: {error}"
                        break
            if "failure" in row:
                rows.append(row)
                break
            time.sleep(1.0)
            row["trial_started"] = True
            command = [
                sys.executable, str(root / "scripts/g8_r5b_trial.py"),
                "--root", str(root), "--trial-index", str(index),
                "--socket", str(a.sim_state / "duck-a.sock"),
                "--body-port", str(a.body_port),
                "--microduck", str(a.microduck), "--microduck-rl", str(a.microduck_rl),
                "--source-head", head,
                "--policy-readback", str(folder / "policy-readback.json"),
                "--raw", str(folder / "trace.jsonl"),
                "--events", str(folder / "events.jsonl"),
                "--summary", str(folder / "summary.json"),
            ]
            row["trial_exit"] = run_logged(command, folder / "trial.log", env=env, cwd=root)
            row["trial_log_sha256"] = sha(folder / "trial.log")
            if (folder / "summary.json").exists():
                row["summary_sha256"] = sha(folder / "summary.json")
                row["summary"] = json.loads((folder / "summary.json").read_text())
            else:
                row["failure"] = "trial_exited_without_summary"
            rows.append(row)
            if row["trial_exit"] != 0 or row.get("summary", {}).get("result") != "PASS":
                break
    finally:
        log = a.output / "final-down.log"
        final_down["exit"] = run_logged([str(sim), "down"], log, env=env)
        final_down["sha256"] = sha(log)
    result = "PASS" if (len(rows) == protocol["required_successful_independent_trials"]
                         and all(row.get("summary", {}).get("result") == "PASS" for row in rows)
                         and final_down["exit"] == 0) else "FAIL"
    report = {
        "schema_version": "g8-r5b-moving-neural-stop-batch-v1",
        "result": result, "execution_target": "Thor",
        "source_head": head, "protocol_sha256": sha(protocol_path),
        "started_utc": started_utc, "ended_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "planned_trials": protocol["required_successful_independent_trials"],
        "completed_trials": len(rows), "trials": rows, "final_sim_down": final_down,
        "historical_failed_pr_60_untouched": True,
    }
    summary_path = a.output / "batch-summary.json"
    summary_path.write_text(json.dumps(report, sort_keys=True, indent=2,
                                       allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"result": result, "completed_trials": len(rows),
                      "trial_results": [r.get("summary", {}).get("result", r.get("failure"))
                                        for r in rows],
                      "batch_summary_sha256": sha(summary_path)}, sort_keys=True))
    if result != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
