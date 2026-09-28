"""Retained Thor-only, no-final-seed P8-03-R1 interruption development gate.

Run prepare, d-start, d-finish (in a new SSH session), then finalize.
The independent reviewer, not this program, supplies gate.json on PASS.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.p8_02_final_batch import probe_final_sim_state
from scripts.p8_02_r1_batch import emergency_stop, fsync_directory
from scripts.p8_03_batch import final_gate_pass, r1_final_cleanup
from scripts.p8_03_r1_durability import (
    atomic_json, checkpoint, classify_attempt, create_arm_marker,
    durable_directory, load_protocol, process_start_ticks, reconcile, run_child,
    supervisor_liveness)
from scripts.p8_03_r1_remote import start, status
from scripts.p8_03_score import manifest_check


def check_source(head: str) -> dict:
    actual = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                                     text=True).strip()
    dirty = subprocess.check_output(["git", "-C", str(ROOT), "status", "--porcelain"],
                                    text=True).strip()
    if (actual != head or dirty or not socket.gethostname().startswith("jetsonthor")
            or sys.version_info[:2] != (3, 12)):
        raise RuntimeError("clean reviewed Thor Python 3.12 source required")
    _, protocol, hashes = load_protocol(ROOT)
    execution = json.loads((ROOT / "config/p8_03_r1_execution_v1.json").read_text())
    for path_key, commit_key in (("microduck_path", "microduck_commit"),
                                 ("microduck_rl_path", "microduck_rl_commit")):
        upstream = subprocess.check_output(
            ["git", "-C", execution[path_key], "rev-parse", "HEAD"],
            text=True).strip()
        if upstream != execution[commit_key]:
            raise RuntimeError(f"pinned upstream mismatch: {path_key}")
    for path_key, hash_key in (("graph_path", "graph_sha256"),
                               ("walking_policy_path", "walking_policy_sha256")):
        if hashlib.sha256(Path(execution[path_key]).read_bytes()).hexdigest() != execution[hash_key]:
            raise RuntimeError(f"pinned material mismatch: {path_key}")
    return {"head": head, "protocol_sha256": hashes["r1"],
            "master_sha256": hashes["master"],
            "development_seeds": protocol["development_seeds"]}


def identity(head: str, seed: int, trial_id: str) -> dict:
    execution = ROOT / "config/p8_03_r1_execution_v1.json"
    return {"task": "P8-03-R1", "trial_id": trial_id, "seed": seed,
            "attempt": 1, "source_head": head,
            "config_sha256": hashlib.sha256(execution.read_bytes()).hexdigest()}


def case_root(output: Path, letter: str) -> Path:
    path = output / letter
    durable_directory(path)
    return path


def save_case(path: Path, letter: str, seed: int, passed: bool, details: dict) -> None:
    atomic_json(path / "result.json", {"case": letter, "development_seed": seed,
                                       "result": "PASS" if passed else "FAIL",
                                       "details": details})


def snapshot_file(source: Path, target: Path) -> str:
    """Retain checkpoint bytes before a later checkpoint overwrites the path."""
    payload = source.read_bytes()
    with target.open("xb") as out:
        out.write(payload)
        out.flush()
        os.fsync(out.fileno())
    fsync_directory(target.parent)
    return hashlib.sha256(payload).hexdigest()


def ssh_session_observation() -> dict:
    connection = os.environ.get("SSH_CONNECTION")
    if not connection:
        raise RuntimeError("development reconnect case requires SSH_CONNECTION")
    parent_pid = os.getppid()
    parent_start_ticks = process_start_ticks(parent_pid)
    if parent_start_ticks is None:
        raise RuntimeError("cannot prove first SSH session process identity")
    session_id = os.getsid(0) if hasattr(os, "getsid") else None
    return {"ssh_connection_sha256": hashlib.sha256(connection.encode()).hexdigest(),
            "session_id": session_id, "parent_pid": parent_pid,
            "parent_start_ticks": parent_start_ticks}


def prepare(output: Path, head: str) -> None:
    source = check_source(head)
    if output.exists():
        raise FileExistsError(output)
    durable_directory(output)
    atomic_json(output / "source.json", source)
    config = json.loads((ROOT / "config/p8_03_r1_execution_v1.json").read_text())
    if any(Path(config[key]).exists() for key in ("static_output", "receding_output")):
        raise RuntimeError("R1 final output root already exists")

    # A: no child and no marker; exact R1 source proves PRE_ARM.
    a = case_root(output, "A")
    attempt_dir = a / "DA00"
    durable_directory(attempt_dir)
    attempt_dir = attempt_dir / "attempt-01"
    durable_directory(attempt_dir)
    ia = identity(head, 887100, "DA00")
    attempt = {"name": "attempt-01", "status": "ACQUIRING", "armed": False}
    journal = {"schema_version": "p8-03-r1-batch-journal-v1", "stage": "D",
               "source_head": head, "config_sha256": ia["config_sha256"],
               "result": "RUNNING", "ids": [{"trial_id": "DA00",
               "seed": 887100, "attempts": [attempt]}]}
    checkpoint(a, journal, artifact_state="ACQUIRING")
    a_source_hash = snapshot_file(a / "batch-journal.json",
                                  a / "source-batch-journal.json")
    report = reconcile(a, journal)
    atomic_json(a / "recovery-report.json", report)
    checkpoint(a, journal, artifact_state="RECOVERED")
    save_case(a, "A", 887100, a_source_hash == report["source_journal_sha256"]
              and report["states"]["DA00/attempt-01"] == "PRE_ARM"
              and manifest_check(a)["result"] == "PASS", report)
    checkpoint(a, journal, artifact_state="RECOVERED")

    # B: marker survives a stale journal and makes retry impossible.
    b = case_root(output, "B")
    b_trial = b / "DB00"
    durable_directory(b_trial)
    b_folder = b_trial / "attempt-01"
    durable_directory(b_folder)
    ib = identity(head, 887101, "DB00")
    b_attempt = {"name": "attempt-01", "status": "TRIAL_CHILD_STARTED", "armed": False}
    b_journal = dict(journal, ids=[{"trial_id": "DB00", "seed": 887101,
                                    "attempts": [b_attempt]}])
    checkpoint(b, b_journal, artifact_state="TRIAL_CHILD_STARTED")
    b_source_hash = snapshot_file(b / "batch-journal.json",
                                  b / "source-batch-journal.json")
    create_arm_marker(b_folder / "armed.json", task=ib["task"],
                      trial_id=ib["trial_id"], seed=ib["seed"],
                      attempt=1, source_head=head,
                      config_hash=ib["config_sha256"], arm_ns=time.monotonic_ns())
    b_report = reconcile(b, b_journal)
    atomic_json(b / "recovery-report.json", b_report)
    checkpoint(b, b_journal, artifact_state="RECOVERED")
    save_case(b, "B", 887101,
              b_source_hash == b_report["source_journal_sha256"] and
              b_report["states"]["DB00/attempt-01"] == "ARMED" and
              "DB00/attempt-01" in b_report["retry_prohibited"] and
              manifest_check(b)["result"] == "PASS", b_report)
    checkpoint(b, b_journal, artifact_state="RECOVERED")

    # C: SIGINT during synthetic acquisition, authentic stop, down and probe.
    c = case_root(output, "C")
    c_trial = c / "DC00"
    durable_directory(c_trial)
    c_folder = c_trial / "attempt-01"
    durable_directory(c_folder)
    sim_state = Path("/tmp/p8-03-r1-development-state")
    port = 7896
    env = dict(os.environ, DUCK_SIM_VIEWER="0", DUCK_SIM_STATE=str(sim_state),
               DUCK_SIM_RL=config["microduck_rl_path"], DUCK_SIM_PORT=str(port),
               PYTHONPATH=str(ROOT))
    env["PATH"] = (str(Path(config["microduck_path"]).parent /
                       "rustup/toolchains/stable-aarch64-unknown-linux-gnu/bin") +
                   os.pathsep + env["PATH"])
    c_journal = dict(journal, ids=[{"trial_id": "DC00", "seed": 887102,
                                    "attempts": [{"name": "attempt-01",
                                    "status": "ACQUIRING", "armed": False}]}])
    checkpoint(c, c_journal, artifact_state="ACQUIRING")
    preprobe = probe_final_sim_state(sim_state, port, phase="development_preflight")
    atomic_json(c / "preflight-probe.json", preprobe)
    checkpoint(c, c_journal, artifact_state="PREFLIGHT")
    if preprobe["result"] != "PASS":
        save_case(c, "C", 887102, False, {"preprobe": preprobe,
                                         "up_started": False})
        checkpoint(c, c_journal, artifact_state="PREFLIGHT_FAIL")
        raise RuntimeError("development simulator state/port occupied; no up attempted")
    up_exit = None
    up_error = None
    interrupted = False
    timer = None
    try:
        try:
            up = subprocess.run([config["sim_executable"], "up"], env=env,
                                capture_output=True, timeout=120, check=False)
            up_exit = up.returncode
            (c / "sim-up.log").write_bytes(up.stdout + up.stderr)
        except BaseException as exc:
            up_error = f"{type(exc).__name__}: {exc}"
            retained = (getattr(exc, "stdout", None) or b"") + (
                getattr(exc, "stderr", None) or b"")
            (c / "sim-up.log").write_bytes(retained)
        checkpoint(c, c_journal, artifact_state="UP_EXITED" if up_exit is not None
                   else "UP_INTERRUPTED")
        if up_exit == 0:
            timer = threading.Timer(.4, lambda: os.kill(os.getpid(), signal.SIGINT))
            timer.start()
            try:
                run_child([sys.executable, "-B", "-c",
                           "import time; time.sleep(30)"],
                          c_folder / "acquisition.log", env,
                          created=lambda: checkpoint(c, c_journal,
                                                     artifact_state="ACQUIRING"))
            except KeyboardInterrupt:
                interrupted = True
    finally:
        if timer is not None:
            timer.cancel()
        final = r1_final_cleanup(c, c_journal, Path(config["sim_executable"]),
                                 sim_state, port, env, interrupted=True,
                                 error=up_error)
    c_journal["result"] = "FAIL"
    checkpoint(c, c_journal, artifact_state="INTERRUPTED")
    c_details = {"preprobe": preprobe, "up_exit": up_exit,
                 "up_error": up_error, "interrupted": interrupted,
                 "stop": c_journal["interrupt_stop"], "final": final}
    save_case(c, "C", 887102, up_exit == 0 and interrupted and
              c_journal["interrupt_stop"]["result"] == "PASS" and
              final.get("exit") == 0 and final["state_probe_result"] == "PASS"
              and manifest_check(c)["result"] == "PASS", c_details)
    checkpoint(c, c_journal, artifact_state="INTERRUPTED")

    # E: zero-byte and partial logs are explicitly inventoried.
    e = case_root(output, "E")
    e_trial = e / "DE00"
    durable_directory(e_trial)
    e_folder = e_trial / "attempt-01"
    durable_directory(e_folder)
    e_journal = dict(journal, ids=[{"trial_id": "DE00", "seed": 887104,
                                    "attempts": [{"name": "attempt-01",
                                    "status": "ACQUIRING", "armed": False}]}])
    log = e_folder / "down.log"
    log.touch()
    checkpoint(e, e_journal, artifact_state="ACQUIRING")
    zero = manifest_check(e)["result"]
    zero_log_hash = snapshot_file(log, e / "zero-stage-down.log")
    zero_manifest_hash = snapshot_file(e / "raw-manifest.json",
                                       e / "zero-stage-raw-manifest.json")
    snapshot_file(e / "batch-journal.json", e / "zero-stage-batch-journal.json")
    zero_rows = json.loads((e / "zero-stage-raw-manifest.json").read_text())["files"]
    zero_recorded = any(row["path"] == "DE00/attempt-01/down.log" and
                        row["bytes"] == 0 and row["sha256"] == zero_log_hash
                        for row in zero_rows)
    log.write_bytes(b"partial")
    before = manifest_check(e)["result"]
    checkpoint(e, e_journal, artifact_state="RECOVERED_PARTIAL")
    after = manifest_check(e)["result"]
    save_case(e, "E", 887104, zero_recorded and (zero, before, after) ==
              ("PASS", "FAIL", "PASS"),
              {"zero_manifest": zero, "uncheckpointed_partial": before,
               "reconciled_partial": after,
               "zero_log_sha256": zero_log_hash,
               "zero_manifest_sha256": zero_manifest_hash,
               "zero_recorded": zero_recorded})
    checkpoint(e, e_journal, artifact_state="RECOVERED_PARTIAL")

    # F: the production cleanup path observes a nonzero final down.
    f = case_root(output, "F")
    fake_down = f / "synthetic-down-failure"
    fake_down.write_text("#!/usr/bin/env python3\nimport sys\n"
                         "print('synthetic final-down failure')\nsys.exit(3)\n")
    fake_down.chmod(0o755)
    f_journal = dict(journal, result="RUNNING", ids=[
        {"trial_id": "DF00", "seed": 887105, "attempts": []}])
    checkpoint(f, f_journal, artifact_state="FINAL_DOWN")
    f_final = r1_final_cleanup(f, f_journal, fake_down, sim_state, port, env,
                               interrupted=False)
    f_pass = final_gate_pass(False, {"result": "PASS"}, f_final)
    f_journal["result"] = "PASS" if f_pass else "FAIL"
    checkpoint(f, f_journal, artifact_state="FINAL_DOWN_FAILED")
    save_case(f, "F", 887105, f_final.get("exit") == 3 and not f_pass
              and f_journal["result"] == "FAIL" and
              manifest_check(f)["result"] == "PASS",
              {"final_down": f_final, "batch_result": f_journal["result"]})
    checkpoint(f, f_journal, artifact_state="FINAL_DOWN_FAILED")
    atomic_json(output / "preliminary.json", {"source_head": head,
                "completed_cases": ["A", "B", "C", "E", "F"]})


def d_start(output: Path, head: str) -> None:
    check_source(head)
    session = ssh_session_observation()
    d = case_root(output, "D")
    command = [sys.executable, "-B", "-c", "import time; time.sleep(60)",
               "--r1", "--output", str(d / "synthetic-output"),
               "--reviewed-head", head]
    launch = start(d / "launch", command)
    atomic_json(d / "start-observation.json", {"launch": launch, **session})


def d_finish(output: Path, head: str) -> None:
    check_source(head)
    second = ssh_session_observation()
    d = output / "D"
    first = json.loads((d / "start-observation.json").read_text())
    distinct_connection = (first["ssh_connection_sha256"] !=
                           second["ssh_connection_sha256"])
    first_session_liveness = supervisor_liveness(first["parent_pid"],
                                                 first["parent_start_ticks"])
    launch_root = d / "launch"
    before = status(launch_root)
    duplicate_refused = False
    try:
        start(launch_root, ["python3.12", "--r1", "--output", "x",
                            "--reviewed-head", head])
    except FileExistsError:
        duplicate_refused = True
    if before.get("same_process_alive"):
        os.kill(before["pid"], signal.SIGKILL)
    time.sleep(.5)
    after = status(launch_root)
    passed = (distinct_connection and first_session_liveness == "ABSENT" and
              before["state"] == "RUNNING" and duplicate_refused and
              after["state"] == "LOST_REQUIRES_RECOVERY")
    save_case(d, "D", 887103, passed,
              {"start_session": first, "finish_session": second,
               "distinct_ssh_connection": distinct_connection,
               "first_session_liveness": first_session_liveness,
               "reconnected_before": before, "duplicate_refused": duplicate_refused,
               "after_forced_termination": after})


def finalize(output: Path, head: str) -> None:
    source = check_source(head)
    cases = {letter: json.loads((output / letter / "result.json").read_text())
             for letter in "ABCDEF"}
    passed = all(row["result"] == "PASS" for row in cases.values())
    atomic_json(output / "development-result.json", {
        "schema_version": "p8-03-r1-development-v1",
        "source_head": head, "source": source,
        "cases": {key: value["result"] for key, value in cases.items()},
        "result": "PASS" if passed else "FAIL",
        "independent_review": "PENDING"})
    files = []
    for path in sorted(output.rglob("*")):
        if not path.is_file() or path == output / "development-manifest.json":
            continue
        payload = path.read_bytes()
        files.append({"path": path.relative_to(output).as_posix(),
                      "sha256": hashlib.sha256(payload).hexdigest(),
                      "bytes": len(payload),
                      "record_count": len(payload.splitlines()) if payload else 0})
    atomic_json(output / "development-manifest.json", {
        "schema_version": "p8-03-r1-development-manifest-v1",
        "source_head": head, "files": files})


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action", choices=("prepare", "d-start", "d-finish", "finalize"))
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--reviewed-head", required=True)
    args = ap.parse_args()
    {"prepare": prepare, "d-start": d_start, "d-finish": d_finish,
     "finalize": finalize}[args.action](args.output, args.reviewed_head)
    print(json.dumps({"action": args.action, "result": "COMPLETED",
                      "output": str(args.output)}))


if __name__ == "__main__":
    main()
