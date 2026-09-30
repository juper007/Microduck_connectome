"""P8-03 Thor S/R supervisor with pre-output audit and durable attempt journal."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import signal
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
from microduck_connectome.p8_03_upstream_source import verify_reconstructed_source


PROBE_CONFIGS = {"v1": "config/p8_03_timing_probe_v1.json",
                 "v2": "config/p8_03_timing_probe_v2.json",
                 "v3": "config/p8_03_timing_probe_v3.json"}
R1_CONFIG = "config/p8_03_local_reference_v1_r1.json"
PROBE_IDS = {"v1": ("TPR2-001", "TPR2-002", "TPR2-003"),
             "v2": ("TPR2A-001", "TPR2A-002", "TPR2A-003"),
             "v3": ("CTP3-001", "CTP3-002", "CTP3-003")}
PROBE_TASKS = {"v1": "P8-03-R2-TIMING-ARCHITECTURE-AND-PROBE",
               "v2": "P8-03-R2-PREARM-MOTION-ACK-REMEDIATION",
               "v3": "P8-03-R3-CAUSAL-50HZ-TIMING-PROBE"}


def probe_config(args) -> str:
    return PROBE_CONFIGS[getattr(args, "timing_probe_version", "v1")]


def probe_rows(config: dict) -> list[dict]:
    """Validate the independent development-only timing probe allocation."""
    rows = config.get("development_gate", {}).get("ids", [])
    schema = config.get("schema_version")
    version = (schema.removeprefix("p8-03-timing-probe-")
               if isinstance(schema, str) else None)
    ids = PROBE_IDS.get(version)
    if (ids is None or config.get("schema_version") != f"p8-03-timing-probe-{version}" or
            config.get("task_id") != PROBE_TASKS[version] or
            config.get("reset_id_semantics") != "UNIQUE_LABEL_ONLY" or
            config.get("simulator_rng_seeded") is not False or
            len(rows) != len(ids) or
            [r.get("reset_id") for r in rows] != list(ids) or
            [r.get("ordinal") for r in rows] != list(range(len(ids))) or
            any(r.get("mode") not in ("static", "receding") or
                r.get("arm_elapsed_s") not in (2.0, 2.6, 3.0) for r in rows)):
        raise ValueError("timing probe ID allocation mismatch")
    return [{"reset_id": r["reset_id"], "ordinal": r["ordinal"],
             "motion": r["mode"], "arm_elapsed_s": r["arm_elapsed_s"]}
            for r in rows]


def validate_probe_config(config: dict, baseline: dict) -> list[dict]:
    rows = probe_rows(config)
    v3 = config["schema_version"] == "p8-03-timing-probe-v3"
    allowed = {"schema_version", "task_id", "status", "state_dir", "body_port",
               "preflight_audit", "development_output", "static_output",
               "receding_output", "package_output", "development_gate",
               "release_tag", "parent_implementation_pr"}
    if v3:
        allowed.update({"decision_pr", "decision_reviewed_head",
                        "reference_semantic_change", "causal_pr96_head",
                        "microduck_candidate_sha", "microduck_patch_sha256",
                        "source_path", "microduck_path", "sim_executable"})
        require(set(config) == set(baseline) | {
            "causal_pr96_head", "microduck_candidate_sha", "microduck_patch_sha256"},
            "causal timing config field set changed")
        require(config["causal_pr96_head"] ==
                "9fe4a2345606d993fb40511a9b06822aa4f30c91" and
                config["microduck_candidate_sha"] ==
                "c47085a57770c52ed4cd00d5960b17598df2d7af" and
                config["microduck_patch_sha256"] ==
                "828ff2619ee378d4fe49fe358944dcc9b5aa9b6583e7aef1afe43a353411655a" and
                config["decision_pr"] == 96 and
                config["decision_reviewed_head"] == config["causal_pr96_head"] and
                config["reference_semantic_change"] is False and
                config["parent_implementation_pr"] == 96,
                "causal timing provenance mismatch")
    else:
        require(set(config) == set(baseline), "timing probe config field set changed")
    for key in set(config) - allowed:
        require(config[key] == baseline[key], f"frozen probe material changed: {key}")
    require(config["body_port"] != baseline["body_port"] and
            (not v3 or config["source_path"] != baseline["source_path"]) and
            config["state_dir"] != baseline["state_dir"] and
            config["package_output"] != baseline["package_output"] and
            config["development_output"] != baseline["development_output"] and
            Path(config["development_output"]).parent == Path(config["package_output"]) and
            Path(config["preflight_audit"]).parent == Path(config["package_output"]),
            "timing probe isolation mismatch")
    return rows


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



def run_trial_child(command: list[str], log: Path, env: dict, *, progress,
                    timeout_s: float) -> tuple[int, bool, bool]:
    """Bound a trial process; the batch performs stop/down/probe on timeout."""
    if timeout_s <= 0:
        raise ValueError("trial timeout must be positive")
    with log.open("wb") as out:
        child = subprocess.Popen(command, stdout=out, stderr=subprocess.STDOUT, env=env)
        deadline = time.monotonic() + timeout_s
        timed_out = False
        interrupted = False
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    break
                try:
                    code = child.wait(timeout=min(.05, remaining))
                    progress()
                    return code, False, False
                except subprocess.TimeoutExpired:
                    progress()
        except KeyboardInterrupt:
            interrupted = True
        finally:
            if child.poll() is None:
                child.send_signal(signal.SIGINT)
                try:
                    child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    child.terminate()
                    try:
                        child.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait(timeout=2)
            progress()
            out.flush()
            os.fsync(out.fileno())
        return child.returncode, timed_out or interrupted, timed_out


def preflight(args) -> tuple[dict, dict, list[dict], dict]:
    root = args.root.resolve()
    timing_probe = getattr(args, "timing_probe", False)
    if timing_probe:
        require(args.stage == "D", "timing probe permits development stage D only")
    config_rel = probe_config(args) if timing_probe else R1_CONFIG
    config_path = root / config_rel
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
        causal_v3 = timing_probe and getattr(args, "timing_probe_version", "v1") == "v3"
        require(git_head(args.microduck_rl) == config["microduck_rl_commit"],
                "MicroDuck RL commit mismatch")
        if causal_v3:
            upstream_identity = verify_reconstructed_source(
                args.microduck,
                root / "patches/microduck/p8-03-robotd-diagnostic-metadata.patch",
                run_tests=True)
        else:
            require(git_head(args.microduck) == config["microduck_commit"],
                    "upstream MicroDuck commit mismatch")
        require(args.graph.resolve() == Path(config["graph_path"]).resolve() and
                sha(args.graph) == config["graph_sha256"], "graph path/hash mismatch")
        require(args.policy.resolve() == Path(config["walking_policy_path"]).resolve() and
                sha(args.policy) == config["walking_policy_sha256"], "policy path/hash mismatch")
        require(args.sim_executable.resolve() == Path(config["sim_executable"]).resolve() and
                os.access(args.sim_executable, os.X_OK), "sim executable mismatch")
        target = config[{"D": "development_output", "S": "static_output",
                         "R": "receding_output"}[args.stage]]
        require(args.output.resolve() == Path(target).resolve() and not args.output.exists(),
                "output must be unused frozen stage root")
        require(args.audit.resolve() == audit.resolve() and
                args.sim_state.resolve() == Path(config["state_dir"]).resolve() and
                args.body_port == config["body_port"], "audit/state/port mismatch")
        require(config["schema_version"] == ("p8-03-timing-probe-" +
                                               getattr(args, "timing_probe_version", "v1")
                                               if timing_probe
                                               else "p8-03-local-reference-v1") and
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
        source_files = [config_rel, "config/p8_v2_final_protocol_v1.json",
                        "scripts/p8_03_batch.py", "scripts/p8_03_trial.py", "scripts/p8_03_score.py",
                        "scripts/p8_03_finalize.py", "scripts/p8_03_local_reference.py",
                        "microduck_connectome/p8_03_geometry.py"]
        if timing_probe and getattr(args, "timing_probe_version", "v1") == "v3":
            source_files.extend(("scripts/p8_03_timing_score.py",
                                 "scripts/p8_02_r1_trial.py",
                                 "microduck_connectome/p8_03_causal_timing.py",
                                 "microduck_connectome/robotd_diagnostic.py"))
        for rel in source_files:
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
        rows = (validate_probe_config(config, json.loads((root / R1_CONFIG).read_text()))
                if timing_probe else planned(config, args.stage))
        require(len(rows) == (3 if timing_probe else 10 if args.stage == "D" else 20),
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
        if timing_probe and getattr(args, "timing_probe_version", "v1") == "v3":
            record["provenance"] = {
                "connectome_source_head": args.reviewed_head,
                "origin_main_base": config["fetched_origin_main_base"],
                "microduck_original_sha": config["microduck_commit"],
                "microduck_candidate_sha": config["microduck_candidate_sha"],
                "microduck_patch_sha256": config["microduck_patch_sha256"],
                "graph_sha256": config["graph_sha256"],
                "policy_sha256": config["walking_policy_sha256"],
                "config_sha256": sha(config_path),
                "simulator_rng_seeded": False}
            record["provenance"].update(upstream_identity)
        record["result"] = "PASS"
        return master, config, rows, record
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
    timing_probe = getattr(args, "timing_probe", False)
    output = args.output
    output.mkdir(parents=True, exist_ok=False)
    journal = {"schema_version": "p8-03-local-batch-journal-v1", "stage": args.stage,
               "source_head": args.reviewed_head, "source_path": str(args.root.resolve()),
               "config_sha256": sha(args.root / (probe_config(args) if timing_probe else R1_CONFIG)),
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
    stop_remaining = False
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
                if timing_probe:
                    command.extend(("--timing-probe", "--timing-ledger",
                                     str(folder / "timing-ledger.jsonl")))
                    command.extend(("--timing-probe-version",
                                    getattr(args, "timing_probe_version", "v1")))
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

                code, was_interrupted, timed_out = run_trial_child(
                    command, folder / "trial.log", env, progress=progress,
                    timeout_s=config["trial_child_timeout_s"])
                attempt["child_timeout"] = timed_out
                attempt["armed"] = (folder / "armed.json").is_file()
                attempt["trial_exit"] = code
                attempt["status"] = ("INTERRUPTED_UNKNOWN_ARM"
                                     if was_interrupted or code != 0 else "TRIAL_EXITED")
                if (folder / "summary.json").is_file():
                    attempt["summary_sha256"] = sha(folder / "summary.json")
                checkpoint(output, journal)
                if was_interrupted or code != 0:
                    interrupted = True
                    item["status"] = "INTERRUPTED_UNKNOWN_ARM"
                else:
                    item["status"] = "ARMED_COMPLETE" if attempt["armed"] else "PREARM_UNCLASSIFIED"
                checkpoint(output, journal)
                if (timing_probe and getattr(args, "timing_probe_version", "v1") == "v3"
                        and item["status"] == "ARMED_COMPLETE"):
                    from scripts.p8_03_timing_score import _score_trial
                    provisional = _score_trial(folder, row, config)
                    atomic_json(folder / "provisional-timing-score.json", provisional)
                    if provisional["result"] != "PASS":
                        item["status"] = "TIMING_FAIL"
                        stop_remaining = True
                        checkpoint(output, journal)
                break
            if interrupted or stop_remaining or item["status"] != "ARMED_COMPLETE":
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
        if timing_probe:
            from scripts.p8_03_timing_score import score_batch as score_timing_batch
            score = score_timing_batch(output, config)
        else:
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
    ap.add_argument("--timing-probe", action="store_true",
                     help="run only the preregistered three-ID timing feasibility probe")
    ap.add_argument("--timing-probe-version", choices=tuple(PROBE_CONFIGS), default="v1",
                    help="v1 replays historical R2; v2 uses fresh prearm ACK probe IDs")
    ap.add_argument("--recover-only", action="store_true")
    ap.add_argument("--preflight-only", action="store_true",
                    help="audit frozen inputs and exit before assigning any reset ID")
    args = ap.parse_args()
    if args.timing_probe and args.stage != "D":
        ap.error("--timing-probe requires --stage D")
    if not args.timing_probe and args.timing_probe_version != "v1":
        ap.error("--timing-probe-version v2 requires --timing-probe")
    if args.preflight_only:
        if args.recover_only:
            ap.error("preflight-only and recover-only are mutually exclusive")
        _, _, _, record = preflight(args)
        print(json.dumps({"result": record["result"], "stage": args.stage,
                          "ids_assigned": 0}))
        return
    result = run(args)
    print(json.dumps({"result": result["result"], "stage": args.stage}))
    if result["result"] not in ("PASS", "AUDIT_ONLY"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
