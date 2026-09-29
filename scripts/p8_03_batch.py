"""P8-03 Thor S/R supervisor with pre-output audit and durable attempt journal."""

from __future__ import annotations

import argparse
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

from scripts.p7_pretrial_acquisition import validate_loaded_walk_policy
from scripts.p8_02_final_batch import probe_final_sim_state
from scripts.p8_02_r1_batch import (append_audit, atomic_json, emergency_stop,
                                    inventory, now, run_child)
from scripts.p8_03_score import manifest_check, planned, score_batch
from scripts.p8_03_local_reference import acquire_local_reference


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_head(path: Path) -> str:
    return subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"],
                                   text=True).strip()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def checkpoint(root: Path, journal: dict) -> None:
    journal["checkpoint_utc"] = now()
    journal["checkpoint_monotonic_ns"] = time.monotonic_ns()
    atomic_json(root / "batch-journal.json", journal)
    atomic_json(root / "raw-manifest.json", {
        "schema_version": "p8-03-local-raw-manifest-v1", "stage": journal["stage"],
        "source_head": journal["source_head"], "files": inventory(root)})


def recover_only(root: Path) -> dict:
    """Read-only conservative recovery; ambiguous child starts are UNKNOWN_ARM."""
    journal = json.loads((root / "batch-journal.json").read_text())
    states = []
    for item in journal["ids"]:
        for attempt in item["attempts"]:
            folder = root / item["reset_id"] / attempt["name"]
            marker = folder / "armed.json"
            summary = folder / "summary.json"
            if attempt.get("status") == "TRIAL_EXITED" and summary.is_file():
                state = "COMPLETED"
            elif marker.is_file():
                state = "ARMED"
            elif attempt.get("status") in ("TRIAL_CHILD_STARTED", "NEURAL_OBSERVATION_ARMED",
                                            "INTERRUPTED_UNKNOWN_ARM"):
                state = "UNKNOWN_ARM"
            else:
                state = "PRE_ARM"
            states.append({"reset_id": item["reset_id"], "attempt": attempt["name"],
                           "state": state})
    return {"schema_version": "p8-03-local-recovery-audit-v1", "result": "AUDIT_ONLY",
            "source_journal_sha256": sha(root / "batch-journal.json"),
            "manifest": manifest_check(root), "attempt_states": states,
            "in_flight_unknown_arm": [r["reset_id"] + "/" + r["attempt"]
                                      for r in states if r["state"] == "UNKNOWN_ARM"],
            "files": inventory(root)}


def preflight(args) -> tuple[dict, dict, list[dict], dict]:
    root = args.root.resolve()
    config_path = root / "config/p8_03_local_reference_v1.json"
    master_path = root / "config/p8_v2_final_protocol_v1.json"
    config = json.loads(config_path.read_text())
    master = json.loads(master_path.read_text())
    package_root = Path(config["development_output"]).parent
    package_root.mkdir(parents=True, exist_ok=True)
    package_config = package_root / "source-config.json"
    if not package_config.exists() and args.stage == "D":
        with package_config.open("xb") as stream:
            stream.write(config_path.read_bytes())
            stream.flush()
            os.fsync(stream.fileno())
    require(package_config.read_bytes() == config_path.read_bytes(),
            "packaged source config does not match reviewed config")
    audit = Path(config["preflight_audit"])
    record = {"schema_version": "p8-03-local-preflight-v1", "at_utc": now(),
              "result": "FAIL", "assigned_ids": 0, "stage": args.stage,
              "python": platform.python_version(), "host": socket.gethostname(),
              "source_head": args.reviewed_head, "checks": [], "hashes": {}}
    try:
        require(socket.gethostname().startswith("jetsonthor") and
                platform.python_version_tuple()[:2] == ("3", "12"),
                "official Thor Python 3.12 required")
        require(root == Path(config["source_path"]).resolve(), "frozen source path mismatch")
        require(git_head(root) == args.reviewed_head and len(args.reviewed_head) == 40,
                "source HEAD differs from independently reviewed HEAD")
        require(not subprocess.check_output(["git", "-C", str(root), "status", "--porcelain"],
                                            text=True).strip(), "source checkout is not clean")
        require(args.microduck.resolve() == Path(config["microduck_path"]).resolve() and
                args.microduck_rl.resolve() == Path(config["microduck_rl_path"]).resolve(),
                "upstream operator path mismatch")
        require(git_head(args.microduck) == config["microduck_commit"] and
                git_head(args.microduck_rl) == config["microduck_rl_commit"],
                "upstream commit mismatch")
        require(args.graph.resolve() == Path(config["graph_path"]).resolve() and
                sha(args.graph) == config["graph_sha256"], "graph path/hash mismatch")
        require(args.policy.resolve() == Path(config["walking_policy_path"]).resolve() and
                sha(args.policy) == config["walking_policy_sha256"], "policy path/hash mismatch")
        require(args.sim_executable.resolve() == Path(config["sim_executable"]).resolve() and
                os.access(args.sim_executable, os.X_OK), "sim executable mismatch")
        target = config[{"D": "development_output", "S": "static_output",
                         "R": "receding_output"}[args.stage]]
        require(args.output.resolve() == Path(target).resolve() and not args.output.exists(),
                "output must be unused frozen S/R root")
        require(args.audit.resolve() == audit.resolve() and
                args.sim_state.resolve() == Path(config["state_dir"]).resolve() and
                args.body_port == config["body_port"], "audit/state/port mismatch")
        require(config["schema_version"] == "p8-03-local-reference-v1" and
                master["schema_version"] == "p8-v2-final-protocol-v1",
                "protocol schema mismatch")
        require(config["scored_window_ms"] == 1000 and config["visual_hz"] == 20 and
                config["neural_hz"] == 50 and config["control_hz"] == 50 and
                config["freshness_ttl_ms"] == 100 and
                config["max_false_stops_per_set"] == 1 and
                config["max_false_stops_pooled"] == 2,
                "P8-03 frozen timing/acceptance mismatch")
        moving = master["scenario"]["moving_precondition"]
        controls = master["scenario"]["controls"]
        require(config["moving_gate"]["duration_s"] == moving["duration_s"] and
                config["moving_gate"]["command_period_ms"] ==
                moving["command_period_ms"] and
                config["moving_gate"]["minimum_trunk_displacement_m"] ==
                moving["minimum_trunk_displacement_m"] and
                config["static_distance_m"] ==
                controls["static_relative_center_distance_m"] and
                config["receding_speed_mps"] ==
                controls["receding_relative_distance_rate_mps"] and
                config["static_tolerance_m"] ==
                controls["static_distance_tolerance_m"] and
                config["receding_max_negative_frame_step_m"] ==
                abs(controls["receding_min_increment_tolerance_m"]),
                "P8-V2 moving/geometry contract changed")
        for rel in ("config/p8_03_local_reference_v1.json", "config/p8_v2_final_protocol_v1.json",
                    "scripts/p8_03_batch.py", "scripts/p8_03_trial.py", "scripts/p8_03_score.py",
                    "scripts/p8_03_finalize.py", "scripts/p8_03_local_reference.py",
                    "microduck_connectome/p8_03_geometry.py"):
            require((root / rel).read_bytes() == subprocess.check_output(
                ["git", "-C", str(root), "show", f"HEAD:{rel}"]),
                f"uncommitted source bytes: {rel}")
            record["hashes"][rel] = sha(root / rel)
        selected = master["selected_pipeline"]
        require(selected == config["selected_pipeline"] and
                selected["graph_v2_sha256"] == config["graph_sha256"] and
                selected["walking_policy_sha256"] == config["walking_policy_sha256"] and
                selected["microduck_commit"] == config["microduck_commit"] and
                selected["microduck_rl_commit"] == config["microduck_rl_commit"],
                "execution differs from master selected materials")
        require(len(planned(config, args.stage)) == (10 if args.stage == "D" else 20),
                "fixed local-reference matrix mismatch")
        if args.stage in ("S", "R"):
            development_root = Path(config["development_output"])
            development_journal = json.loads(
                (development_root / "batch-journal.json").read_text())
            require(development_journal.get("result") == "PASS" and
                    development_journal.get("source_head") == args.reviewed_head and
                    score_batch(development_root, config, "D")["result"] == "PASS" and
                    manifest_check(development_root)["result"] == "PASS",
                    "same-head development gate must PASS before final IDs")
        if args.stage == "R":
            static_root = Path(config["static_output"])
            static_journal = json.loads((static_root / "batch-journal.json").read_text())
            static_score = score_batch(static_root, config, "S")
            require(static_journal.get("result") == "PASS" and
                    static_journal.get("source_head") == args.reviewed_head and
                    static_score["result"] == "PASS" and
                    manifest_check(static_root)["result"] == "PASS" and
                    static_journal.get("final_sim_down", {}).get("state_probe_result") == "PASS",
                    "S stage must be durable PASS before R begins")
        require(probe_final_sim_state(args.sim_state, args.body_port,
                                      phase="preflight")["result"] == "PASS",
                "isolated port/state occupied")
        record["checks"] = ["clean_reviewed_source", "committed_source_bytes", "upstream_heads",
                            "graph_policy_hash", "fixed_matrix", "unused_output", "port_state_probe"]
        record["hashes"].update({"graph": sha(args.graph), "policy": sha(args.policy)})
        record["result"] = "PASS"
        return master, config, planned(config, args.stage), record
    except BaseException as error:
        record["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        append_audit(audit, record)


def run(args) -> dict:
    if args.recover_only:
        report = recover_only(args.output)
        append_audit(args.audit, report)
        return report
    master, config, rows, preflight_record = preflight(args)
    output = args.output
    output.mkdir(parents=True, exist_ok=False)
    journal = {"schema_version": "p8-03-local-batch-journal-v1", "stage": args.stage,
               "source_head": args.reviewed_head, "source_path": str(args.root.resolve()),
               "config_sha256": sha(args.root / "config/p8_03_local_reference_v1.json"),
               "result": "RUNNING", "preflight": preflight_record,
               "ids": [{"reset_id": r["reset_id"], "ordinal": r["ordinal"],
                        "status": "PENDING", "attempts": []} for r in rows],
               "final_sim_down": None, "reset_id_semantics": "UNIQUE_LABEL_ONLY",
               "simulator_rng_seeded": False}
    checkpoint(output, journal)
    env = dict(os.environ)
    env.update({"DUCK_SIM_VIEWER": "0", "DUCK_SIM_STATE": str(args.sim_state),
                "DUCK_SIM_RL": str(args.microduck_rl), "DUCK_SIM_PORT": str(args.body_port),
                "PYTHONPATH": str(args.root),
                "PATH": str(args.microduck.parent / "rustup/toolchains/stable-aarch64-unknown-linux-gnu/bin")
                        + os.pathsep + env["PATH"]})
    interrupted = False
    error = None
    try:
        for index, row in enumerate(rows):
            item = journal["ids"][index]
            for number in range(1, config["max_prearm_attempts"] + 1):
                folder = output / row["reset_id"] / f"attempt-{number:02d}"
                folder.mkdir(parents=True, exist_ok=False)
                attempt = {"name": folder.name, "status": "ACQUIRING", "armed": False,
                           "started_utc": now(), "steps": []}
                item["attempts"].append(attempt)
                item["status"] = "ACQUIRING"
                checkpoint(output, journal)
                retry_up = False
                for name, command in (("down", [str(args.sim_executable), "down"]),
                                      ("up", [str(args.sim_executable), "up"]),
                                      ("policy_load", [str(args.sim_executable), "ctl", "policy",
                                                       "load", "walk", str(args.policy)]),
                                      ("policy_readback", [str(args.sim_executable), "ctl", "policy",
                                                           "list", "--json"])):
                    log = folder / ("policy-readback.json" if name == "policy_readback" else name + ".log")
                    code, was_interrupted = run_child(command, log, env)
                    attempt["steps"].append({"name": name, "command": command,
                                              "exit": code, "sha256": sha(log),
                                              "bytes": log.stat().st_size,
                                              "completed_monotonic_ns": time.monotonic_ns()})
                    attempt["status"] = "ACQUIRED_" + name.upper() if code == 0 else "PREARM_FAILED"
                    checkpoint(output, journal)
                    if was_interrupted:
                        raise KeyboardInterrupt("prearm acquisition interrupted")
                    if code:
                        if name == "up":
                            attempt["retry_cause_code"] = "OFFICIAL_UP_PROCESS_FAILURE"
                            retry_up = True
                            break
                        raise RuntimeError(f"nonretryable prearm {name} failed")
                    if name == "policy_readback":
                        validate_loaded_walk_policy(json.loads(log.read_text()), args.policy,
                                                    config["walking_policy_sha256"])
                if retry_up:
                    if number == config["max_prearm_attempts"]:
                        item["status"] = "PREARM_FAILED"
                    checkpoint(output, journal)
                    continue
                up_step = next(s for s in attempt["steps"] if s["name"] == "up")
                probe = acquire_local_reference(
                    str(args.sim_state / "duck-a.sock"), args.body_port,
                    config["settled_gate"], up_step["completed_monotonic_ns"])
                probe["reset_id"] = row["reset_id"]
                probe["attempt"] = number
                atomic_json(folder / "local-reference.json", probe)
                attempt["local_reference_sha256"] = sha(folder / "local-reference.json")
                checkpoint(output, journal)
                if probe["result"] != "PASS":
                    attempt["status"] = "PREARM_LOCAL_REFERENCE_INVALID"
                    item["status"] = "PREARM_LOCAL_REFERENCE_INVALID"
                    checkpoint(output, journal)
                    raise RuntimeError("official startup did not satisfy local settled gate")
                command = [sys.executable, str(args.root / "scripts/p8_03_trial.py"),
                           "--root", str(args.root), "--stage", args.stage,
                           "--trial-index", str(index), "--attempt", str(number),
                           "--socket", str(args.sim_state / "duck-a.sock"),
                           "--body-port", str(args.body_port),
                           "--microduck", str(args.microduck),
                           "--microduck-rl", str(args.microduck_rl),
                           "--source-head", args.reviewed_head,
                           "--policy-readback", str(folder / "policy-readback.json"),
                           "--local-reference", str(folder / "local-reference.json"),
                           "--armed-marker", str(folder / "armed.json"),
                           "--progress", str(folder / "progress.jsonl"),
                           "--events", str(folder / "events.jsonl"),
                           "--ledger", str(folder / "neural-ledger.jsonl"),
                           "--visual", str(folder / "visual-frames.jsonl"),
                           "--summary", str(folder / "summary.json")]
                attempt["command"] = command
                attempt["status"] = "TRIAL_CHILD_STARTED"
                checkpoint(output, journal)

                def progress():
                    marker = folder / "armed.json"
                    armed = marker.is_file()
                    if armed != attempt["armed"]:
                        attempt["armed"] = armed
                        attempt["status"] = "NEURAL_OBSERVATION_ARMED" if armed else "TRIAL_CHILD_STARTED"
                        checkpoint(output, journal)

                code, was_interrupted = run_child(command, folder / "trial.log", env, progress=progress)
                attempt["armed"] = (folder / "armed.json").is_file()
                attempt["trial_exit"] = code
                attempt["status"] = "INTERRUPTED_UNKNOWN_ARM" if was_interrupted else "TRIAL_EXITED"
                if (folder / "summary.json").is_file():
                    attempt["summary_sha256"] = sha(folder / "summary.json")
                checkpoint(output, journal)
                if was_interrupted:
                    interrupted = True
                    item["status"] = "INTERRUPTED_UNKNOWN_ARM"
                else:
                    item["status"] = "ARMED_COMPLETE" if attempt["armed"] else "PREARM_UNCLASSIFIED"
                checkpoint(output, journal)
                break
            if interrupted or item["status"] != "ARMED_COMPLETE":
                break
    except BaseException as exc:
        interrupted = True
        error = f"{type(exc).__name__}: {exc}"
        for item in journal["ids"]:
            if item["status"] in ("ACQUIRING", "NEURAL_OBSERVATION_ARMED"):
                item["status"] = "INTERRUPTED_UNKNOWN_ARM"
        checkpoint(output, journal)
    finally:
        if interrupted:
            journal["interrupt_stop"] = emergency_stop(args.sim_state / "duck-a.sock")
            checkpoint(output, journal)
        final = {}
        try:
            code, was_interrupted = run_child([str(args.sim_executable), "down"],
                                              output / "final-down.log", env)
            final.update({"exit": code, "interrupted": was_interrupted,
                          "sha256": sha(output / "final-down.log")})
        except BaseException as exc:
            final["error"] = f"{type(exc).__name__}: {exc}"
        try:
            probe = probe_final_sim_state(args.sim_state, args.body_port, phase="final_down")
        except BaseException as exc:
            probe = {"result": "FAIL", "error": f"{type(exc).__name__}: {exc}"}
        atomic_json(output / "final-state-probe.json", probe)
        final["state_probe_result"] = probe["result"]
        final["state_probe_sha256"] = sha(output / "final-state-probe.json")
        journal["final_sim_down"] = final
        journal["error"] = error
        checkpoint(output, journal)
    try:
        score = score_batch(output, config, args.stage)
    except BaseException as exc:
        score = {"result": "FAIL", "error": f"{type(exc).__name__}: {exc}"}
    score["final_down"] = final
    atomic_json(output / "score.json", score)
    journal["result"] = "PASS" if (not interrupted and score["result"] == "PASS"
                                      and final.get("exit") == 0
                                      and final.get("state_probe_result") == "PASS") else "FAIL"
    checkpoint(output, journal)
    atomic_json(output / "batch-summary.json", {
        "schema_version": "p8-03-local-batch-summary-v1", "stage": args.stage,
        "result": journal["result"], "source_head": args.reviewed_head,
        "false_neural_stops": score.get("false_neural_stops"), "error": error})
    checkpoint(output, journal)
    integrity = manifest_check(output)
    if integrity["result"] != "PASS":
        journal["result"] = "FAIL"
        journal["manifest_error"] = integrity["errors"]
        checkpoint(output, journal)
    return {"result": journal["result"], "stage": args.stage, "score": score}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stage", choices=("D", "S", "R"), required=True)
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--reviewed-head", required=True)
    ap.add_argument("--microduck", type=Path, required=True)
    ap.add_argument("--microduck-rl", type=Path, required=True)
    ap.add_argument("--graph", type=Path, required=True)
    ap.add_argument("--policy", type=Path, required=True)
    ap.add_argument("--sim-executable", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--audit", type=Path, required=True)
    ap.add_argument("--sim-state", type=Path, required=True)
    ap.add_argument("--body-port", type=int, required=True)
    ap.add_argument("--recover-only", action="store_true")
    args = ap.parse_args()
    result = run(args)
    print(json.dumps({"result": result["result"], "stage": args.stage}))
    if result["result"] not in ("PASS", "AUDIT_ONLY"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
