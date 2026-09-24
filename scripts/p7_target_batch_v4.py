"""Run a preregistered P7 v4 target batch on official Thor robotd/MuJoCo."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import platform
import socket
import statistics
import subprocess
import sys
import time

from scripts.p7_pretrial_acquisition import acquire, run_logged, sha256_file
from scripts.p7_target_batch import percentile, wilson_interval


def summarize(results: list[dict], experiment: dict, *, head: str,
              manifest_hash: str, journal_hash: str, started_utc: str) -> dict:
    counts = Counter(item["outcome"] for item in results)
    valid = counts["correct"] + counts["incorrect"] + counts["no_response"]
    latencies = [item["response"]["latency_s"] for item in results
                 if item.get("response") is not None]
    breakdown = {}
    for field in ("target_side", "target_eccentricity", "target_motion", "visual_noise_level"):
        groups = defaultdict(list)
        for item in results:
            if item["outcome"] != "invalid":
                groups[item["spec"][field]].append(item)
        breakdown[field] = {
            label: {"evaluated": len(items),
                    "correct": sum(row["outcome"] == "correct" for row in items),
                    "correct_direction_rate": sum(row["outcome"] == "correct" for row in items) / len(items)}
            for label, items in sorted(groups.items())
        }
    safety = sum(item.get("safety_limit_violations", 0) for item in results)
    expected = experiment["target_trial_count"]
    rate = counts["correct"] / valid if valid else None
    return {
        "schema_version": "p7-02-target-batch-v4",
        "execution_target": "Thor", "hostname": socket.gethostname(),
        "started_utc": started_utc,
        "ended_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_head": head, "experiment_sha256": manifest_hash,
        "walking_policy_sha256": experiment["walking_policy"]["sha256"],
        "expected_target_trials": expected, "attempted_trials": len(results),
        "counts": dict(counts), "evaluated_valid_target_trials": valid,
        "correct_direction_rate": rate,
        "correct_direction_95pct_wilson_ci": wilson_interval(counts["correct"], valid),
        "response_latency_median_s": statistics.median(latencies) if latencies else None,
        "response_latency_p95_s": percentile(latencies, .95),
        "max_heading_sample_delay_ms": max(
            (item.get("max_heading_sample_delay_ms", 0.0) for item in results), default=0.0),
        "breakdown": breakdown,
        "safety_limit_violations": safety,
        "raw_journal_sha256": journal_hash,
        "invalid_trial_ids": [item["trial_id"] for item in results if item["outcome"] == "invalid"],
        "result": "PASS" if (len(results) == expected and valid >= 100
                             and rate is not None
                             and rate >= experiment["target_response"]["correct_direction_rate_min"]
                             and safety == 0) else "FAIL",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--graph-cache", type=Path, required=True)
    parser.add_argument("--sim-script", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--microduck", type=Path, required=True)
    parser.add_argument("--microduck-rl", type=Path, required=True)
    parser.add_argument("--body-port", type=int, required=True)
    args = parser.parse_args()
    if not socket.gethostname().startswith("jetsonthor") or platform.python_version_tuple()[:2] != ("3", "12"):
        raise RuntimeError("final v4 batch requires Thor Python 3.12")
    root = args.root.resolve()
    experiment_path = args.experiment.resolve()
    experiment = json.loads(experiment_path.read_text(encoding="utf-8"))
    expected = experiment["target_trial_count"]
    if (experiment["schema_version"] != "steering-experiment-v4" or expected != 120
            or len(experiment["target_trials"]) != expected):
        raise RuntimeError("v4 target trial count or schema mismatch")
    head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    if subprocess.check_output(["git", "-C", str(root), "status", "--porcelain"], text=True).strip():
        raise RuntimeError("final batch requires clean source checkout")
    args.output.mkdir(parents=True, exist_ok=False)
    journal = args.output / "trial-results.jsonl"
    env = dict(__import__("os").environ)
    env.update({
        "PATH": f"{args.microduck.parent / 'cargo/bin'}:{env['PATH']}",
        "RUSTUP_HOME": str(args.microduck.parent / "rustup"),
        "CARGO_HOME": str(args.microduck.parent / "cargo"),
        "DUCK_SIM_STATE": str(args.state_dir),
        "DUCK_SIM_RL": str(args.microduck_rl),
        "DUCK_SIM_PORT": str(args.body_port),
        "DUCK_SIM_VIEWER": "0", "PYTHONPATH": str(root),
    })
    results = []
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with journal.open("w", encoding="utf-8") as output:
        for index, spec in enumerate(experiment["target_trials"], 1):
            folder = args.output / spec["trial_id"]
            folder.mkdir()
            spec_path = folder / "trial-spec.json"
            spec_path.write_text(json.dumps(spec, sort_keys=True, indent=2) + "\n",
                                 encoding="utf-8")
            acquisition = acquire(root=root, experiment_path=experiment_path,
                                  experiment=experiment, trial_dir=folder,
                                  sim_script=args.sim_script, body_port=args.body_port,
                                  env=env)
            row = {"index": index, "trial_id": spec["trial_id"], "seed": spec["seed"],
                   "spec": spec, "pretrial_acquisition_sha256": sha256_file(
                       folder / "pretrial-acquisition.json"),
                   "pretrial_attempts_used": acquisition["attempts_used"]}
            if acquisition["accepted"]:
                command = [
                    sys.executable, str(root / "scripts/p7_target_steering_trial.py"),
                    "--root", str(root), "--graph-cache", str(args.graph_cache),
                    "--graph-key", experiment["graph_key"],
                    "--socket", str(args.state_dir / "duck-a.sock"),
                    "--body-port", str(args.body_port),
                    "--microduck", str(args.microduck),
                    "--microduck-rl", str(args.microduck_rl),
                    "--source-head", head, "--trial-spec", str(spec_path),
                    "--experiment", str(experiment_path),
                    "--run-id", f"p7-steering-v4-{index:03d}",
                    "--artifact", str(folder / "trace.jsonl"),
                    "--summary", str(folder / "summary.json"),
                ]
                row["trial_exit"] = run_logged(command, folder / "trial.log", env=env, cwd=root)
                row["trial_log_sha256"] = sha256_file(folder / "trial.log")
                summary_path = folder / "summary.json"
                if summary_path.exists():
                    summary = json.loads(summary_path.read_text(encoding="utf-8"))
                    row.update({field: summary[field] for field in (
                        "outcome", "safety_limit_violations", "initial_heading_rad",
                        "final_heading_delta_rad", "response", "invalid_reasons",
                        "max_abs_robot_facing_vyaw", "max_heading_sample_delay_ms")})
                    row["summary_sha256"] = sha256_file(summary_path)
                    row["trace_sha256"] = sha256_file(folder / "trace.jsonl")
                else:
                    row["outcome"] = "invalid"
                    row["invalid_reasons"] = ["trial_process_failed_before_summary"]
            else:
                row["outcome"] = "invalid"
                row["invalid_reasons"] = ["pretrial_pose_acquisition_exhausted"]
            output.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
            output.flush()
            results.append(row)
            print(f"{index}/{expected} {spec['trial_id']} {row['outcome']}", flush=True)
            if row.get("safety_limit_violations", 0):
                print("safety violation: ending final batch early", flush=True)
                break
    batch = summarize(results, experiment, head=head,
                      manifest_hash=sha256_file(experiment_path),
                      journal_hash=sha256_file(journal), started_utc=started)
    batch["raw_journal_bytes"] = journal.stat().st_size
    (args.output / "batch-summary.json").write_text(
        json.dumps(batch, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8")
    print(json.dumps({field: batch[field] for field in (
        "result", "attempted_trials", "counts", "correct_direction_rate",
        "safety_limit_violations")}, sort_keys=True), flush=True)
    if batch["result"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
