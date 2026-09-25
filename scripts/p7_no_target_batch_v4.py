"""Run the frozen P7 v4 no-target control batch on official Thor robotd/MuJoCo."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import socket
import subprocess
import sys
import time

from scripts.p7_pretrial_acquisition import acquire, run_logged, sha256_file
from scripts.p7_target_batch import wilson_interval
from scripts.p7_target_batch_v4 import (
    collect_started_trial, ensure_sim_down, started_trial_failed,
)


def false_turn_from_trace(records: list[dict], rule: dict) -> dict:
    """Score sustained absolute robot-facing yaw after the frozen warmup."""
    if not records:
        raise ValueError("empty control trace")
    threshold = float(rule["min_abs_robot_facing_vyaw_radps"])
    sustained_ns = round(float(rule["min_sustained_duration_s"]) * 1e9)
    warmup_ns = round(float(rule["warmup_excluded_s"]) * 1e9)
    if not (math.isfinite(threshold) and threshold > 0 and sustained_ns > 0
            and warmup_ns >= 0):
        raise ValueError("invalid frozen false-turn rule")
    started_ns = min(int(row["perception"]["timestamp_ns"]) for row in records)
    cutoff_ns = started_ns + warmup_ns
    previous_ns = None
    run_start = None
    first_window = None
    max_duration_ns = 0
    max_abs_yaw = 0.0
    active_samples = 0
    for row in records:
        timestamp_ns = int(row["timestamp_ns"])
        yaw = float(row["robot_facing_vyaw"])
        if previous_ns is not None and timestamp_ns <= previous_ns:
            raise ValueError("nonmonotonic control timestamps")
        if not math.isfinite(yaw):
            raise ValueError("nonfinite robot-facing yaw")
        previous_ns = timestamp_ns
        if timestamp_ns < cutoff_ns:
            continue
        active_samples += 1
        max_abs_yaw = max(max_abs_yaw, abs(yaw))
        if abs(yaw) >= threshold:
            if run_start is None:
                run_start = timestamp_ns
            duration_ns = timestamp_ns - run_start
            max_duration_ns = max(max_duration_ns, duration_ns)
            if first_window is None and duration_ns >= sustained_ns:
                first_window = {
                    "start_timestamp_ns": run_start,
                    "end_timestamp_ns": timestamp_ns,
                    "duration_s": duration_ns / 1e9,
                }
        else:
            run_start = None
    if active_samples == 0:
        raise ValueError("no control samples after warmup")
    return {
        "false_turn": first_window is not None,
        "first_false_turn_window": first_window,
        "max_sustained_abs_yaw_duration_s": max_duration_ns / 1e9,
        "max_abs_robot_facing_vyaw_after_warmup": max_abs_yaw,
        "active_control_samples": active_samples,
        "warmup_cutoff_timestamp_ns": cutoff_ns,
    }


def score_trace(path: Path, rule: dict) -> dict:
    records = []
    with path.open(encoding="utf-8") as source:
        for line in source:
            if line.strip():
                records.append(json.loads(line))
    return false_turn_from_trace(records, rule)


def validate_control_specs(experiment: dict) -> list[dict]:
    specs = experiment["no_target_trials"]
    if (experiment["schema_version"] != "steering-experiment-v4"
            or experiment["no_target_trial_count"] != 40
            or len(specs) != 40):
        raise ValueError("frozen v4 no-target trial count or schema mismatch")
    ids = [spec["trial_id"] for spec in specs]
    seeds = [spec["seed"] for spec in specs]
    if len(set(ids)) != 40 or len(set(seeds)) != 40:
        raise ValueError("duplicate no-target trial ID or seed")
    for index, spec in enumerate(specs, 1):
        if (spec["trial_id"] != f"p7-v4-no-target-{index:03d}"
                or spec["target_present"] is not False
                or any(spec[field] != "none" for field in
                       ("target_side", "target_eccentricity", "target_motion"))):
            raise ValueError("invalid ordered no-target control spec")
    return specs


def summarize(rows: list[dict], experiment: dict, *, head: str,
              manifest_sha256: str, fixture_sha256: str,
              journal_sha256: str, started_utc: str) -> dict:
    expected = experiment["no_target_trial_count"]
    rule = experiment["no_target_false_turn"]
    counts = Counter(row["outcome"] for row in rows)
    evaluated = [row for row in rows if (row.get("trial_started")
                 and row.get("outcome") == "no_target"
                 and row.get("safety_limit_violations") == 0
                 and "false_turn" in row)]
    false_ids = [row["trial_id"] for row in evaluated if row["false_turn"]]
    failures = [row["trial_id"] for row in rows if started_trial_failed(row)]
    safety = sum(row.get("safety_limit_violations", 0) for row in rows)
    rate = len(false_ids) / len(evaluated) if evaluated else None
    spec_order = [spec["trial_id"] for spec in experiment["no_target_trials"]]
    observed_order = [row["trial_id"] for row in rows]
    return {
        "schema_version": "p7-02-no-target-batch-v4",
        "execution_target": "Thor",
        "hostname": socket.gethostname(),
        "started_utc": started_utc,
        "ended_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_head": head,
        "experiment_sha256": manifest_sha256,
        "fixture_sha256": fixture_sha256,
        "walking_policy_sha256": experiment["walking_policy"]["sha256"],
        "false_turn_rule_sha256": hashlib.sha256(json.dumps(
            rule, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "false_turn_rule": rule,
        "expected_no_target_trials": expected,
        "attempted_trials": len(rows),
        "evaluated_valid_no_target_trials": len(evaluated),
        "counts": dict(counts),
        "false_turn_trial_ids": false_ids,
        "false_turn_count": len(false_ids),
        "false_turn_rate": rate,
        "false_turn_95pct_wilson_ci": wilson_interval(len(false_ids), len(evaluated)),
        "safety_limit_violations": safety,
        "started_trial_failures": failures,
        "invalid_trial_ids": [row["trial_id"] for row in rows if row["outcome"] == "invalid"],
        "raw_journal_sha256": journal_sha256,
        "result": "PASS" if (len(rows) == expected
                and observed_order == spec_order
                and len(evaluated) == expected
                and not failures and safety == 0
                and rate is not None
                and rate <= rule["false_turn_rate_max"]) else "FAIL",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("root", "experiment", "output", "graph-cache", "sim-script",
                 "state-dir", "microduck", "microduck-rl"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--body-port", type=int, required=True)
    args = parser.parse_args()
    if (not socket.gethostname().startswith("jetsonthor")
            or platform.python_version_tuple()[:2] != ("3", "12")):
        raise RuntimeError("final v4 control batch requires Thor Python 3.12")
    root = args.root.resolve()
    experiment_path = args.experiment.resolve()
    tracked_manifest = (root / "config/steering_experiment_v4.json").resolve()
    if experiment_path != tracked_manifest:
        raise RuntimeError("final batch requires tracked v4 manifest")
    head = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    if subprocess.check_output(
            ["git", "-C", str(root), "status", "--porcelain"], text=True).strip():
        raise RuntimeError("final batch requires clean source checkout")
    committed_manifest = subprocess.check_output(
        ["git", "-C", str(root), "show", "HEAD:config/steering_experiment_v4.json"])
    if experiment_path.read_bytes() != committed_manifest:
        raise RuntimeError("v4 manifest differs from committed bytes")
    experiment = json.loads(experiment_path.read_text(encoding="utf-8"))
    specs = validate_control_specs(experiment)
    fixture_path = Path(__file__).resolve()
    if fixture_path != (root / "scripts/p7_no_target_batch_v4.py").resolve():
        raise RuntimeError("final batch requires tracked no-target harness")
    committed_fixture = subprocess.check_output(
        ["git", "-C", str(root), "show", "HEAD:scripts/p7_no_target_batch_v4.py"])
    if fixture_path.read_bytes() != committed_fixture:
        raise RuntimeError("no-target harness differs from committed bytes")
    args.output.mkdir(parents=True, exist_ok=False)
    journal = args.output / "trial-results.jsonl"
    env = dict(os.environ)
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
    rows = []
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    final_down = {}
    with ensure_sim_down(args.sim_script, args.output, env, final_down), \
            journal.open("w", encoding="utf-8") as output:
        for index, spec in enumerate(specs, 1):
            folder = args.output / spec["trial_id"]
            folder.mkdir()
            spec_path = folder / "trial-spec.json"
            spec_path.write_text(json.dumps(spec, sort_keys=True, indent=2) + "\n",
                                 encoding="utf-8")
            row = {
                "index": index, "trial_id": spec["trial_id"], "seed": spec["seed"],
                "spec": spec, "spec_sha256": sha256_file(spec_path),
                "trial_started": False,
            }
            acquisition = None
            try:
                acquisition = acquire(
                    root=root, experiment_path=experiment_path,
                    experiment=experiment, trial_dir=folder,
                    sim_script=args.sim_script, body_port=args.body_port, env=env)
                row["pretrial_acquisition_sha256"] = sha256_file(
                    folder / "pretrial-acquisition.json")
                row["pretrial_attempts_used"] = acquisition["attempts_used"]
                row["trial_started"] = acquisition["accepted"]
            except BaseException as error:
                row["outcome"] = "invalid"
                row["invalid_reasons"] = ["pretrial_acquisition_exception"]
                row["harness_exception"] = f"{type(error).__name__}: {error}"
            if acquisition is not None and acquisition["accepted"]:
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
                    "--run-id", f"p7-no-target-v4-{index:03d}",
                    "--artifact", str(folder / "trace.jsonl"),
                    "--summary", str(folder / "summary.json"),
                ]
                command_path = folder / "trial-command.json"
                command_path.write_text(json.dumps({
                    "argv": command,
                    "cwd": str(root),
                    "duck_sim_state": str(args.state_dir),
                    "duck_sim_port": args.body_port,
                }, sort_keys=True, indent=2) + "\n", encoding="utf-8")
                row["trial_command_sha256"] = sha256_file(command_path)
                row.update(collect_started_trial(command, folder, env=env, root=root))
                if not started_trial_failed(row) and row.get("outcome") == "no_target":
                    try:
                        row.update(score_trace(folder / "trace.jsonl",
                                               experiment["no_target_false_turn"]))
                    except BaseException as error:
                        row["outcome"] = "invalid"
                        row["invalid_reasons"] = ["false_turn_scorer_exception"]
                        row["harness_exception"] = f"{type(error).__name__}: {error}"
            elif acquisition is not None:
                row["outcome"] = "invalid"
                row["invalid_reasons"] = ["pretrial_pose_acquisition_exhausted"]
            abort = (acquisition is None or started_trial_failed(row)
                     or (row.get("trial_started")
                         and row.get("outcome") != "no_target")
                     or bool(row.get("safety_limit_violations", 0)))
            if abort:
                emergency_log = folder / "emergency-sim-down.log"
                try:
                    row["emergency_sim_down_exit"] = run_logged(
                        [str(args.sim_script), "down"], emergency_log, env=env)
                except BaseException as error:
                    row["emergency_sim_down_error"] = f"{type(error).__name__}: {error}"
                if emergency_log.exists():
                    row["emergency_sim_down_sha256"] = sha256_file(emergency_log)
            output.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
            output.flush()
            rows.append(row)
            print(f"{index}/40 {spec['trial_id']} {row['outcome']}", flush=True)
            if abort:
                print("started trial failure or safety violation: batch stopped",
                      flush=True)
                break
    batch = summarize(
        rows, experiment, head=head,
        manifest_sha256=sha256_file(experiment_path),
        fixture_sha256=sha256_file(fixture_path),
        journal_sha256=sha256_file(journal), started_utc=started)
    batch["final_sim_down_exit"] = final_down.get("exit")
    batch["final_sim_down_sha256"] = final_down.get("sha256")
    batch["final_sim_down_error"] = final_down.get("error")
    if final_down.get("exit") != 0:
        batch["result"] = "FAIL"
    batch["raw_journal_bytes"] = journal.stat().st_size
    (args.output / "batch-summary.json").write_text(
        json.dumps(batch, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8")
    print(json.dumps({key: batch[key] for key in (
        "result", "attempted_trials", "evaluated_valid_no_target_trials",
        "false_turn_count", "false_turn_rate", "safety_limit_violations")},
        sort_keys=True), flush=True)
    if batch["result"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
