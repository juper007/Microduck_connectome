"""Serial official Thor resets for development-only moving-body fault probes."""

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
from scripts.p8_fault_stop_trial import FAULTS


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--microduck", type=Path, required=True)
    parser.add_argument("--microduck-rl", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sim-state", type=Path, required=True)
    parser.add_argument("--body-port", type=int, required=True)
    parser.add_argument("--faults", nargs="+", choices=FAULTS, required=True)
    args = parser.parse_args()
    if not socket.gethostname().startswith("jetsonthor") or platform.python_version_tuple()[:2] != ("3", "12"):
        raise RuntimeError("official Thor Python 3.12 required")
    root = args.root.resolve()
    source_head = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    protocol = json.loads((root / "config/g8_r5d_stop_refresh_v1.json").read_text())
    args.output.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ)
    env.update({
        "PATH": str(args.microduck.parent / "rustup/toolchains/stable-aarch64-unknown-linux-gnu/bin")
                + os.pathsep + env["PATH"],
        "DUCK_SIM_VIEWER": "0", "DUCK_SIM_STATE": str(args.sim_state),
        "DUCK_SIM_RL": str(args.microduck_rl), "DUCK_SIM_PORT": str(args.body_port),
        "PYTHONPATH": str(root),
    })
    sim = args.microduck / "scripts/duck-sim"
    rows = []
    for index, fault in enumerate(args.faults):
        development_seed = 884000 + index
        folder = args.output / f"trial-{index + 1:02d}-{fault}"
        folder.mkdir()
        row = {"index": index, "fault": fault, "development_seed": development_seed,
               "started": False, "steps": {},
               "result": "NOT_STARTED"}
        rows.append(row)
        try:
            for name, command in (
                ("down", [str(sim), "down"]),
                ("up", [str(sim), "up"]),
                ("policy_load", [str(sim), "ctl", "policy", "load", "walk",
                                 protocol["walking_policy_path"]]),
                ("policy_readback", [str(sim), "ctl", "policy", "list", "--json"]),
            ):
                log = folder / ("policy-readback.json" if name == "policy_readback" else name + ".log")
                code = run_logged(command, log, env=env, cwd=root)
                row["steps"][name] = {"exit": code, "sha256": sha(log),
                                      "bytes": log.stat().st_size}
                if code != 0:
                    raise RuntimeError(f"official {name} failed with {code}")
                if name == "policy_readback":
                    validate_loaded_walk_policy(json.loads(log.read_text()),
                                                Path(protocol["walking_policy_path"]),
                                                protocol["walking_policy_sha256"])
            time.sleep(1.0)
            row["started"] = True
            command = [
                sys.executable, str(root / "scripts/p8_fault_stop_trial.py"),
                "--root", str(root), "--socket", str(args.sim_state / "duck-a.sock"),
                "--body-port", str(args.body_port),
                "--microduck", str(args.microduck), "--microduck-rl", str(args.microduck_rl),
                "--source-head", source_head,
                "--policy-readback", str(folder / "policy-readback.json"),
                "--fault", fault, "--development-seed", str(development_seed),
                "--output", str(folder),
            ]
            trial_log = folder / "trial.log"
            code = run_logged(command, trial_log, env=env, cwd=root)
            row["steps"]["trial"] = {"exit": code, "sha256": sha(trial_log),
                                      "bytes": trial_log.stat().st_size}
            summary_path = folder / "summary.json"
            if summary_path.is_file():
                summary = json.loads(summary_path.read_text())
                row["result"] = summary["result"]
                row["summary_sha256"] = sha(summary_path)
                row["summary_bytes"] = summary_path.stat().st_size
            else:
                row["result"] = "NO_SUMMARY"
            if code != 0:
                raise RuntimeError("fault trial failed; subsequent trials withheld")
        except BaseException as error:
            row["failure"] = f"{type(error).__name__}: {error}"
        finally:
            log = folder / "final-down.log"
            try:
                code = run_logged([str(sim), "down"], log, env=env, cwd=root)
                row["steps"]["final_down"] = {"exit": code, "sha256": sha(log),
                                                "bytes": log.stat().st_size}
            except BaseException as error:
                row["final_down_failure"] = f"{type(error).__name__}: {error}"
        if "failure" in row or "final_down_failure" in row:
            break
    batch = {
        "schema_version": "p8-v2-fault-stop-development-batch-v1",
        "evidence_role": "development_only_not_final_p8_04",
        "source_head": source_head,
        "planned_faults": args.faults,
        "rows": rows,
        "result": "DEVELOPMENT_PROBE_PASS" if len(rows) == len(args.faults) and all(
            row["result"] in ("DEVELOPMENT_PROBE_PASS", "DEVELOPMENT_PROBE_EXPECTED_EXCEPTION_SAFE")
            and "failure" not in row and "final_down_failure" not in row
            and row["steps"]["final_down"]["exit"] == 0 for row in rows
        ) else "DEVELOPMENT_PROBE_FAIL",
    }
    path = args.output / "batch-summary.json"
    path.write_text(json.dumps(batch, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({"result": batch["result"], "output": str(args.output),
                      "attempts": len(rows)}))
    if batch["result"] != "DEVELOPMENT_PROBE_PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
