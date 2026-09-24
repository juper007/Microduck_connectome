"""Run every preregistered target trial with an official simulator reset on Thor."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import platform
import socket
import statistics
import subprocess
import sys
import time


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def wilson_interval(successes, total):
    if total == 0:
        return [None, None]
    z = 1.959963984540054
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return [center - margin, center + margin]


def percentile(values, fraction):
    if not values:
        return None
    values = sorted(values)
    position = (len(values) - 1) * fraction
    low, high = math.floor(position), math.ceil(position)
    return values[low] + (values[high] - values[low]) * (position - low)


def run_logged(command, path, *, env=None, cwd=None):
    result = subprocess.run(command, cwd=cwd, env=env, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    path.write_text(result.stdout, encoding="utf-8")
    return result.returncode


def main():
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
        raise RuntimeError("final batch requires Thor Python 3.12")
    root = args.root.resolve()
    experiment_path = args.experiment.resolve()
    experiment = json.loads(experiment_path.read_text(encoding="utf-8"))
    if experiment["schema_version"] != "steering-experiment-v1" or len(experiment["target_trials"]) != 100:
        raise RuntimeError("frozen target trial count mismatch")
    head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    if subprocess.check_output(["git", "-C", str(root), "status", "--porcelain"], text=True).strip():
        raise RuntimeError("final batch requires clean source checkout")
    args.output.mkdir(parents=True, exist_ok=False)
    manifest_hash = sha256_file(experiment_path)
    journal = args.output / "trial-results.jsonl"
    env = dict(__import__("os").environ)
    env.update({
        "PATH": f"{args.microduck.parent / 'cargo/bin'}:{env['PATH']}",
        "RUSTUP_HOME": str(args.microduck.parent / "rustup"),
        "CARGO_HOME": str(args.microduck.parent / "cargo"),
        "DUCK_SIM_STATE": str(args.state_dir),
        "DUCK_SIM_RL": str(args.microduck_rl),
        "DUCK_SIM_PORT": str(args.body_port),
        "DUCK_SIM_VIEWER": "0",
        "PYTHONPATH": str(root),
    })
    results = []
    started_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with journal.open("w", encoding="utf-8") as output:
        for index, spec in enumerate(experiment["target_trials"], 1):
            trial_dir = args.output / spec["trial_id"]
            trial_dir.mkdir()
            spec_path = trial_dir / "trial-spec.json"
            spec_path.write_text(json.dumps(spec, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            down_status = run_logged([str(args.sim_script), "down"], trial_dir / "sim-down.log", env=env)
            up_status = run_logged([str(args.sim_script), "up"], trial_dir / "sim-up.log", env=env)
            record = {
                "index": index, "trial_id": spec["trial_id"], "seed": spec["seed"],
                "spec": spec, "sim_down_exit": down_status, "sim_up_exit": up_status,
                "sim_down_sha256": sha256_file(trial_dir / "sim-down.log"),
                "sim_up_sha256": sha256_file(trial_dir / "sim-up.log"),
            }
            if up_status == 0:
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
                    "--run-id", f"p7-steering-v1-{index:03d}",
                    "--artifact", str(trial_dir / "trace.jsonl"),
                    "--summary", str(trial_dir / "summary.json"),
                ]
                trial_status = run_logged(command, trial_dir / "trial.log", env=env, cwd=root)
                record["trial_exit"] = trial_status
                record["trial_log_sha256"] = sha256_file(trial_dir / "trial.log")
                summary_path = trial_dir / "summary.json"
                if summary_path.exists():
                    summary = json.loads(summary_path.read_text(encoding="utf-8"))
                    record["summary_sha256"] = sha256_file(summary_path)
                    record["trace_sha256"] = sha256_file(trial_dir / "trace.jsonl")
                    record["outcome"] = summary["outcome"]
                    record["safety_limit_violations"] = summary["safety_limit_violations"]
                    record["initial_heading_rad"] = summary["initial_heading_rad"]
                    record["final_heading_delta_rad"] = summary["final_heading_delta_rad"]
                    record["response"] = summary["response"]
                    record["invalid_reasons"] = summary["invalid_reasons"]
                    record["max_abs_robot_facing_vyaw"] = summary["max_abs_robot_facing_vyaw"]
                else:
                    record["outcome"] = "invalid"
                    record["invalid_reasons"] = ["trial_process_failed_before_summary"]
            else:
                record["outcome"] = "invalid"
                record["invalid_reasons"] = ["official_simulator_failed_to_start"]
            output.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")
            output.flush()
            results.append(record)
            print(f"{index}/100 {spec['trial_id']} {record['outcome']}", flush=True)
            if record.get("safety_limit_violations", 0):
                print("safety violation: ending final batch early", flush=True)
                break
    counts = Counter(item["outcome"] for item in results)
    evaluated = counts["correct"] + counts["incorrect"] + counts["no_response"]
    latencies = [item["response"]["latency_s"] for item in results
                 if item.get("response") is not None]
    breakdown = {}
    for field in ("target_side", "target_eccentricity", "target_motion", "visual_noise_level"):
        groups = defaultdict(list)
        for item in results:
            if item["outcome"] != "invalid":
                groups[item["spec"][field]].append(item)
        breakdown[field] = {
            label: {"evaluated": len(items), "correct": sum(row["outcome"] == "correct" for row in items),
                    "correct_direction_rate": sum(row["outcome"] == "correct" for row in items) / len(items)}
            for label, items in sorted(groups.items())
        }
    summary = {
        "schema_version": "p7-02-target-batch-v1",
        "execution_target": "Thor", "hostname": socket.gethostname(),
        "started_utc": started_utc,
        "ended_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_head": head, "experiment_sha256": manifest_hash,
        "expected_target_trials": 100, "attempted_trials": len(results),
        "counts": dict(counts), "evaluated_valid_target_trials": evaluated,
        "correct_direction_rate": counts["correct"] / evaluated if evaluated else None,
        "correct_direction_95pct_wilson_ci": wilson_interval(counts["correct"], evaluated),
        "response_latency_median_s": statistics.median(latencies) if latencies else None,
        "response_latency_p95_s": percentile(latencies, .95),
        "breakdown": breakdown,
        "safety_limit_violations": sum(item.get("safety_limit_violations", 0) for item in results),
        "raw_journal_sha256": sha256_file(journal),
        "raw_journal_bytes": journal.stat().st_size,
        "invalid_trial_ids": [item["trial_id"] for item in results if item["outcome"] == "invalid"],
        "result": "PASS" if (len(results) == 100 and evaluated >= 100
                              and counts["correct"] / evaluated >= experiment["target_response"]["correct_direction_rate_min"]
                              and not any(item.get("safety_limit_violations", 0) for item in results)) else "FAIL",
    }
    (args.output / "batch-summary.json").write_text(
        json.dumps(summary, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(json.dumps({key: summary[key] for key in
                      ("result", "attempted_trials", "counts", "correct_direction_rate",
                       "safety_limit_violations")}, sort_keys=True), flush=True)
    if summary["result"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
