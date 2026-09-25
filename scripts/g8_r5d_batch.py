"""Three fresh official Thor resets for the frozen G8-R5d integration protocol."""
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


def exception_label(error: Exception) -> str:
    """Keep a compact failure in the batch manifest without discarding raw files."""
    return f"{type(error).__name__}: {error}"


def validate_trial_artifacts(summary: dict, folder: Path) -> None:
    """A PASS summary must name the retained, hashed raw evidence in this trial."""
    for key in ("trace_artifact", "events_artifact", "neural_ledger_artifact"):
        artifact = summary.get(key)
        if not isinstance(artifact, dict):
            raise ValueError(f"missing {key}")
        path = Path(artifact["path"]).resolve()
        if path.parent != folder.resolve() or not path.is_file():
            raise ValueError(f"{key} is not retained in trial folder")
        if artifact.get("sha256") != sha(path):
            raise ValueError(f"{key} SHA256 mismatch")
        if type(artifact.get("record_count")) is not int or artifact["record_count"] < 1:
            raise ValueError(f"{key} has no records")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--microduck", type=Path, required=True)
    ap.add_argument("--microduck-rl", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--sim-state", type=Path, required=True)
    ap.add_argument("--body-port", type=int, required=True)
    ap.add_argument("--development-probe", action="store_true",
                    help="run only the first seed with uncommitted draft; never final evidence")
    a = ap.parse_args()
    if not socket.gethostname().startswith("jetsonthor") or platform.python_version_tuple()[:2] != ("3", "12"):
        raise RuntimeError("official Thor Python 3.12 required")
    root = a.root.resolve()
    head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    if not a.development_probe and subprocess.check_output(
            ["git", "-C", str(root), "status", "--porcelain"], text=True).strip():
        raise RuntimeError("batch requires clean committed source")
    protocol_path = root / "config/g8_r5d_stop_refresh_v1.json"
    protocol = json.loads(protocol_path.read_text())
    if not a.development_probe and protocol_path.read_bytes() != subprocess.check_output([
        "git", "-C", str(root), "show", "HEAD:config/g8_r5d_stop_refresh_v1.json"]):
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
    batch_error = None
    try:
        seeds = protocol["scenario_seeds"][:1] if a.development_probe else protocol["scenario_seeds"]
        for index, seed in enumerate(seeds):
            folder = a.output / f"trial-{index + 1:02d}-{seed}"
            row = {"trial_index": index, "seed": seed, "trial_started": False,
                   "pretrial_logs": {}}
            rows.append(row)
            try:
                folder.mkdir()
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
                    break
                time.sleep(1.0)
                row["trial_started"] = True
                command = [
                    sys.executable, str(root / "scripts/g8_r5d_trial.py"),
                    "--root", str(root), "--trial-index", str(index),
                    "--socket", str(a.sim_state / "duck-a.sock"),
                    "--body-port", str(a.body_port),
                    "--microduck", str(a.microduck), "--microduck-rl", str(a.microduck_rl),
                    "--source-head", head,
                    "--policy-readback", str(folder / "policy-readback.json"),
                    "--raw", str(folder / "trace.jsonl"),
                    "--events", str(folder / "events.jsonl"),
                    "--ledger", str(folder / "neural-ledger.jsonl"),
                    "--summary", str(folder / "summary.json"),
                ]
                if a.development_probe:
                    command.append("--development-probe")
                row["trial_exit"] = run_logged(command, folder / "trial.log", env=env, cwd=root)
                row["trial_log_sha256"] = sha(folder / "trial.log")
                if (folder / "summary.json").exists():
                    row["summary_sha256"] = sha(folder / "summary.json")
                    row["summary"] = json.loads((folder / "summary.json").read_text())
                    if not isinstance(row["summary"], dict):
                        raise ValueError("trial summary is not an object")
                    if row["summary"].get("result") == "PASS":
                        validate_trial_artifacts(row["summary"], folder)
                else:
                    row["failure"] = "trial_exited_without_summary"
            except Exception as error:
                row["failure"] = f"trial_exception: {exception_label(error)}"
            if row.get("trial_exit") != 0 or row.get("summary", {}).get("result") != "PASS" or "failure" in row:
                break
    except Exception as error:
        batch_error = f"batch_exception: {exception_label(error)}"
    finally:
        log = a.output / "final-down.log"
        try:
            final_down["exit"] = run_logged([str(sim), "down"], log, env=env)
            final_down["sha256"] = sha(log)
        except Exception as error:
            final_down["failure"] = f"final_down_exception: {exception_label(error)}"
            if log.exists():
                try:
                    final_down["sha256"] = sha(log)
                except OSError as hash_error:
                    final_down["hash_failure"] = exception_label(hash_error)
    if a.development_probe:
        result = "DEVELOPMENT_PROBE" if (batch_error is None and len(rows) == 1
                                         and rows[0].get("trial_exit") == 0
                                         and "failure" not in rows[0]
                                         and rows[0].get("summary", {}).get("result") == "PASS"
                                         and final_down.get("exit") == 0
                                         and "failure" not in final_down
                                         and "sha256" in final_down) else "PROBE_ERROR"
    else:
        result = "PASS" if (batch_error is None
                            and len(rows) == protocol["required_successful_independent_trials"]
                            and all(row.get("trial_exit") == 0 and "failure" not in row
                                    and row.get("summary", {}).get("result") == "PASS"
                                    for row in rows)
                            and final_down.get("exit") == 0
                            and "failure" not in final_down
                            and "sha256" in final_down) else "FAIL"
    report = {
        "schema_version": "g8-r5d-moving-neural-stop-batch-v1",
        "evidence_role": "development_probe" if a.development_probe else "final_batch",
        "result": result, "execution_target": "Thor",
        "source_head": head, "protocol_sha256": sha(protocol_path),
        "started_utc": started_utc, "ended_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "planned_trials": 1 if a.development_probe else protocol["required_successful_independent_trials"],
        "completed_trials": len(rows), "trials": rows, "final_sim_down": final_down,
        "batch_error": batch_error,
        "historical_failed_pr_60_untouched": True,
        "historical_failed_pr_61_untouched": True,
    }
    summary_path = a.output / "batch-summary.json"
    summary_path.write_text(json.dumps(report, sort_keys=True, indent=2,
                                       allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"result": result, "completed_trials": len(rows),
                      "trial_results": [r.get("summary", {}).get("result", r.get("failure"))
                                        for r in rows],
                      "batch_summary_sha256": sha(summary_path)}, sort_keys=True))
    if result not in ("PASS", "DEVELOPMENT_PROBE"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
