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
from scripts.p8_03_r1_durability import (
    checkpoint as r1_checkpoint, load_protocol, reconcile,
    run_child as r1_run_child, atomic_json as r1_atomic_json,
    stop_orphan_children, process_start_ticks, supervisor_liveness,
    durable_directory)
from scripts.p8_looming_scenario_smoke import OfficialPoseReader


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_head(path: Path) -> str:
    return subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"],
                                   text=True).strip()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def final_gate_pass(interrupted: bool, score: dict, final: dict) -> bool:
    return (not interrupted and score.get("result") == "PASS" and
            final.get("exit") == 0 and final.get("state_probe_result") == "PASS")


def checkpoint(root: Path, journal: dict) -> None:
    if journal.get("schema_version") == "p8-03-r1-batch-journal-v1":
        r1_checkpoint(root, journal, artifact_state=journal.get("result", "RUNNING"))
        return
    journal["checkpoint_utc"] = now()
    journal["checkpoint_monotonic_ns"] = time.monotonic_ns()
    atomic_json(root / "batch-journal.json", journal)
    atomic_json(root / "raw-manifest.json", {
        "schema_version": "p8-03-raw-manifest-v1", "stage": journal["stage"],
        "source_head": journal["source_head"], "files": inventory(root)})


def r1_final_cleanup(output: Path, journal: dict, sim_executable: Path,
                     sim_state: Path, body_port: int, env: dict,
                     *, interrupted: bool, error: str | None = None) -> dict:
    """Shared production/development stop, down, probe and checkpoints."""
    if interrupted:
        journal["interrupt_stop"] = emergency_stop(sim_state / "duck-a.sock")
        checkpoint(output, journal)
    final = {}
    try:
        code, was_interrupted = r1_run_child(
            [str(sim_executable), "down"], output / "final-down.log", env,
            created=lambda: checkpoint(output, journal))
        final.update({"exit": code, "interrupted": was_interrupted,
                      "sha256": sha(output / "final-down.log")})
    except BaseException as exc:
        final["error"] = f"{type(exc).__name__}: {exc}"
    try:
        probe = probe_final_sim_state(sim_state, body_port, phase="final_down")
    except BaseException as exc:
        probe = {"result": "FAIL", "error": f"{type(exc).__name__}: {exc}"}
    r1_atomic_json(output / "final-state-probe.json", probe)
    final["state_probe_result"] = probe["result"]
    final["state_probe_sha256"] = sha(output / "final-state-probe.json")
    journal["final_sim_down"] = final
    journal["error"] = error
    checkpoint(output, journal)
    return final


def recover_only(root: Path) -> dict:
    """Never rewrite an interrupted journal or guess whether a trial was armed."""
    journal = json.loads((root / "batch-journal.json").read_text())
    if journal.get("schema_version") == "p8-03-r1-batch-journal-v1":
        liveness = supervisor_liveness(journal.get("supervisor_pid"),
                                       journal.get("supervisor_start_ticks"))
        if liveness != "ABSENT":
            return {"schema_version": "p8-03-r1-recovery-v1",
                    "result": "REFUSED_" + liveness + "_SUPERVISOR",
                    "supervisor_pid": journal.get("supervisor_pid")}
        if (root / "recovery-report.json").exists():
            return {"schema_version": "p8-03-r1-recovery-v1",
                    "result": "REFUSED_ALREADY_RECOVERED"}
        report = reconcile(root, journal)
        if journal.get("result") == "RUNNING" or journal.get("final_sim_down") is None:
            source = Path(journal["source_path"])
            config = json.loads((source / "config/p8_03_r1_execution_v1.json").read_text())
            cleanup = {"emergency_stop": emergency_stop(
                Path(config["state_dir"]) / "duck-a.sock")}
            cleanup["children"] = stop_orphan_children(root)
            if any(r["state"] in ("ACTIVE_PARENT_REFUSED", "STILL_ACTIVE")
                   for r in cleanup["children"]):
                cleanup["result"] = "FAIL_ACTIVE_PROCESS"
            else:
                env = dict(os.environ, DUCK_SIM_STATE=config["state_dir"],
                           DUCK_SIM_PORT=str(config["body_port"]),
                           DUCK_SIM_RL=config["microduck_rl_path"],
                           DUCK_SIM_VIEWER="0")
                try:
                    code, _ = r1_run_child([config["sim_executable"], "down"],
                                           root / "recovery-final-down.log", env,
                                           created=lambda: checkpoint(root, journal))
                    cleanup["down_exit"] = code
                except BaseException as exc:
                    cleanup["down_error"] = f"{type(exc).__name__}: {exc}"
                cleanup["probe"] = probe_final_sim_state(
                    Path(config["state_dir"]), config["body_port"],
                    phase="r1_recovery_final_down")
                cleanup["result"] = "PASS" if not any(
                    r["state"] == "UNKNOWN_IDENTITY" for r in cleanup["children"]
                ) and cleanup["emergency_stop"].get(
                    "result") == "PASS" and cleanup.get("down_exit") == 0 and (
                    cleanup["probe"].get("result") == "PASS") else "FAIL"
            report["cleanup"] = cleanup
            report["post_cleanup_states"] = reconcile(root, journal)["states"]
        report["result"] = "FAIL"
        r1_atomic_json(root / "recovery-report.json", report)
        journal["result"] = "FAIL"
        checkpoint(root, journal)
        report["manifest"] = manifest_check(root)
        return report
    in_flight = []
    for item in journal["ids"]:
        for attempt in item["attempts"]:
            if attempt.get("status") not in ("TRIAL_EXITED", "PREARM_FAILED", "CLEANED"):
                in_flight.append(item["trial_id"] + "/" + attempt["name"])
    return {"schema_version": "p8-03-recovery-audit-v1", "result": "AUDIT_ONLY",
            "source_journal_sha256": sha(root / "batch-journal.json"),
            "manifest": manifest_check(root), "in_flight_unknown_arm": in_flight,
            "files": inventory(root)}


def pose_reset_probe(port: int, *, reference: dict | None,
                     tolerance: dict) -> dict:
    """Audit a fresh duck-sim up against the fixed first-reset pose."""
    reader = OfficialPoseReader(port)
    try:
        first = reader.read()
        time.sleep(.1)
        second = reader.read()
    finally:
        reader.close()
    expected = reference or first

    def delta(key: str, value: float) -> float:
        difference = value - expected[key]
        return abs((difference + math.pi) % (2 * math.pi) - math.pi) if key == "heading_rad" else abs(difference)

    spread = {key: delta(key, second[key]) for key in tolerance}
    stable = {key: (abs((second[key] - first[key] + math.pi) % (2 * math.pi) - math.pi)
                    if key == "heading_rad" else abs(second[key] - first[key]))
              for key in tolerance}
    result = (all(spread[key] <= tolerance[key] and stable[key] <= tolerance[key]
                  for key in tolerance) and all(math.isfinite(v) for v in second.values()))
    return {"schema_version": "p8-03-pose-reset-v1", "result": "PASS" if result else "FAIL",
            "reference": expected, "first_pose": first, "second_pose": second,
            "delta_from_reference": spread, "within_reset_stability": stable,
            "tolerance": tolerance, "source": "official MuJoCo trunk pose after fresh duck-sim down/up"}


def preflight(args) -> tuple[dict, dict, list[dict], dict]:
    root = args.root.resolve()
    config_path = root / ("config/p8_03_r1_execution_v1.json" if args.r1 else
                          "config/p8_03_execution_v1.json")
    master_path = root / "config/p8_v2_final_protocol_v1.json"
    config = json.loads(config_path.read_text())
    master = load_protocol(root)[0] if args.r1 else json.loads(master_path.read_text())
    audit = Path(config["preflight_audit"])
    record = {"schema_version": "p8-03-preflight-v1", "at_utc": now(),
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
        target = config["static_output" if args.stage == "S" else "receding_output"]
        require(args.output.resolve() == Path(target).resolve() and not args.output.exists(),
                "output must be unused frozen S/R root")
        require(args.audit.resolve() == audit.resolve() and
                args.sim_state.resolve() == Path(config["state_dir"]).resolve() and
                args.body_port == config["body_port"], "audit/state/port mismatch")
        require(config["schema_version"] == ("p8-03-r1-execution-v1" if args.r1 else
                                           "p8-03-execution-v1") and
                master["schema_version"] == "p8-v2-final-protocol-v1",
                "protocol schema mismatch")
        if args.r1:
            r1_protocol = load_protocol(root)[1]
            require(config["max_prearm_attempts"] ==
                    r1_protocol["max_prearm_attempts"] == 1 and
                    config["static_distance_m"] == .85 and
                    config["static_tolerance_m"] == .005 and
                    config["receding_speed_mps"] == .20 and
                    config["receding_max_negative_frame_step_m"] == .005,
                    "R1 frozen attempts/geometry mismatch")
            gate = json.loads(Path(config["development_gate"]).read_text())
            require(gate.get("result") == "PASS" and
                    gate.get("review_result") == "PASS" and
                    gate.get("source_head") == args.reviewed_head and
                    set(gate.get("cases", {})) == set("ABCDEF") and
                    all(v == "PASS" for v in gate["cases"].values()),
                    "R1 interruption development gate/review incomplete")
        require(config["scored_window_ms"] == 1000 and config["visual_hz"] == 20 and
                config["neural_hz"] == 50 and config["control_hz"] == 50 and
                config["freshness_ttl_ms"] == 100 and
                config["max_false_stops_per_set"] == 1 and
                config["max_false_stops_pooled"] == 2,
                "P8-03 frozen timing/acceptance mismatch")
        for rel in (("config/p8_03_r1_execution_v1.json" if args.r1 else
                     "config/p8_03_execution_v1.json"), "config/p8_v2_final_protocol_v1.json",
                    "scripts/p8_03_batch.py", "scripts/p8_03_trial.py", "scripts/p8_03_score.py",
                    "scripts/p8_03_finalize.py",
                    "microduck_connectome/p8_03_geometry.py"):
            require((root / rel).read_bytes() == subprocess.check_output(
                ["git", "-C", str(root), "show", f"HEAD:{rel}"]),
                f"uncommitted source bytes: {rel}")
            record["hashes"][rel] = sha(root / rel)
        if args.r1:
            for rel in ("config/p8_03_r1_protocol_v1.json",
                        "scripts/p8_03_r1_durability.py",
                        "scripts/p8_03_r1_child.py",
                        "scripts/p8_03_r1_remote.py"):
                require((root / rel).read_bytes() == subprocess.check_output(
                    ["git", "-C", str(root), "show", f"HEAD:{rel}"]),
                    f"uncommitted R1 source bytes: {rel}")
                record["hashes"][rel] = sha(root / rel)
        selected = master["selected_pipeline"]
        require(selected["graph_v2_sha256"] == config["graph_sha256"] and
                selected["walking_policy_sha256"] == config["walking_policy_sha256"] and
                selected["microduck_commit"] == config["microduck_commit"] and
                selected["microduck_rl_commit"] == config["microduck_rl_commit"],
                "execution differs from master selected materials")
        require(len(planned(master, args.stage)) == 20, "fixed matrix mismatch")
        if args.stage == "R":
            static_root = Path(config["static_output"])
            static_journal = json.loads((static_root / "batch-journal.json").read_text())
            static_score = score_batch(static_root, master, "S")
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
        return master, config, planned(master, args.stage), record
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
    supervisor_ticks = process_start_ticks(os.getpid()) if args.r1 else None
    if args.r1:
        require(supervisor_ticks is not None,
                "cannot durably identify R1 supervisor")
    output = args.output
    if args.r1:
        durable_directory(output)
    else:
        output.mkdir(parents=True, exist_ok=False)
    journal = {"schema_version": "p8-03-r1-batch-journal-v1" if args.r1 else
               "p8-03-batch-journal-v1", "stage": args.stage,
               "source_head": args.reviewed_head, "source_path": str(args.root.resolve()),
               "result": "RUNNING", "preflight": preflight_record,
               "ids": [{"trial_id": r["trial_id"], "seed": r["seed"],
                        "status": "PENDING", "attempts": []} for r in rows],
               "final_sim_down": None, "reset_reference": None}
    if args.r1:
        journal["config_sha256"] = sha(args.root / "config/p8_03_r1_execution_v1.json")
        journal["protocol_sha256"] = sha(args.root / "config/p8_03_r1_protocol_v1.json")
        journal["supervisor_pid"] = os.getpid()
        journal["supervisor_start_ticks"] = supervisor_ticks
    scenario = json.loads((args.root / "config/looming_scenario_v1.json").read_text())
    tolerance = scenario["initial_pose_tolerance"]
    if args.stage == "R":
        static_root = Path(config["static_output"])
        journal["reset_reference"] = json.loads(
            (static_root / "batch-journal.json").read_text())["reset_reference"]
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
                row_root = output / row["trial_id"]
                folder = row_root / f"attempt-{number:02d}"
                if args.r1:
                    if not row_root.exists():
                        durable_directory(row_root)
                    durable_directory(folder)
                else:
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
                    runner = r1_run_child if args.r1 else run_child
                    extra = {"created": lambda: checkpoint(output, journal)} if args.r1 else {}
                    code, was_interrupted = runner(command, log, env, **extra)
                    attempt["steps"].append({"name": name, "command": command,
                                              "exit": code, "sha256": sha(log),
                                              "bytes": log.stat().st_size})
                    attempt["status"] = "ACQUIRED_" + name.upper() if code == 0 else "PREARM_FAILED"
                    checkpoint(output, journal)
                    if was_interrupted:
                        raise KeyboardInterrupt("prearm acquisition interrupted")
                    if code:
                        if name == "up" and not args.r1:
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
                probe = pose_reset_probe(args.body_port,
                    reference=journal["reset_reference"], tolerance=tolerance)
                atomic_json(folder / "pose-reset.json", probe)
                attempt["pose_reset"] = probe
                checkpoint(output, journal)
                if probe["result"] != "PASS":
                    attempt["status"] = "PREARM_POSE_RESET_INVALID"
                    item["status"] = "PREARM_POSE_RESET_INVALID"
                    checkpoint(output, journal)
                    raise RuntimeError("official fresh reset pose outside frozen tolerance")
                if journal["reset_reference"] is None:
                    journal["reset_reference"] = probe["reference"]
                    checkpoint(output, journal)
                time.sleep(1)
                command = [sys.executable, str(args.root / "scripts/p8_03_trial.py"),
                           "--root", str(args.root), "--stage", args.stage,
                           "--trial-index", str(index), "--attempt", str(number),
                           "--socket", str(args.sim_state / "duck-a.sock"),
                           "--body-port", str(args.body_port),
                           "--microduck", str(args.microduck),
                           "--microduck-rl", str(args.microduck_rl),
                           "--source-head", args.reviewed_head,
                           "--policy-readback", str(folder / "policy-readback.json"),
                           "--pose-reset", str(folder / "pose-reset.json"),
                           "--armed-marker", str(folder / "armed.json"),
                           "--progress", str(folder / "progress.jsonl"),
                           "--events", str(folder / "events.jsonl"),
                           "--ledger", str(folder / "neural-ledger.jsonl"),
                           "--visual", str(folder / "visual-frames.jsonl"),
                           "--summary", str(folder / "summary.json")]
                if args.r1:
                    command.append("--r1")
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

                runner = r1_run_child if args.r1 else run_child
                extra = {"created": lambda: checkpoint(output, journal)} if args.r1 else {}
                code, was_interrupted = runner(command, folder / "trial.log", env,
                                               progress=progress, **extra)
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
        if args.r1:
            final = r1_final_cleanup(output, journal, args.sim_executable,
                                     args.sim_state, args.body_port, env,
                                     interrupted=interrupted, error=error)
        else:
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
        score = score_batch(output, master, args.stage)
    except BaseException as exc:
        score = {"result": "FAIL", "error": f"{type(exc).__name__}: {exc}"}
    score["final_down"] = final
    atomic_json(output / "score.json", score)
    journal["result"] = "PASS" if final_gate_pass(interrupted, score, final) else "FAIL"
    checkpoint(output, journal)
    atomic_json(output / "batch-summary.json", {
        "schema_version": "p8-03-batch-summary-v1", "stage": args.stage,
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
    ap.add_argument("--stage", choices=("S", "R"), required=True)
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
    ap.add_argument("--r1", action="store_true")
    args = ap.parse_args()
    exit_code = 1
    try:
        result = run(args)
        print(json.dumps({"result": result["result"], "stage": args.stage}))
        exit_code = 0 if result["result"] in ("PASS", "AUDIT_ONLY") else 1
    finally:
        launch_root = os.environ.get("P8_03_R1_LAUNCH_ROOT")
        if args.r1 and launch_root:
            r1_atomic_json(Path(launch_root) / "exit-status.json", {
                "schema_version": "p8-03-r1-supervisor-exit-v1",
                "exit_code": exit_code, "at_utc": now(),
                "stage": args.stage, "output": str(args.output)})
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
