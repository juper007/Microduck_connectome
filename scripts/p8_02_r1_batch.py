"""Prospective P8-02 R1 D/B supervisor with pre-output provenance and durable attempts."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import signal
import socket
import subprocess
import sys
import time

from microduck_connectome.robotd_client import RobotdClient
from scripts.p7_pretrial_acquisition import validate_loaded_walk_policy
from scripts.p8_02_final_batch import probe_final_sim_state
from scripts.p8_02_r1_score import score_batch
from scripts.p8_02_r1_trial import validate_r1_material, validate_r1_selection

FROZEN_PREFLIGHT_AUDIT = Path(
    "/home/juper007/projects/microduck-connectome-thor/evidence/p8-v2-final/"
    "p8-02-r1-preflight-audit.jsonl")
FROZEN_NO_SEED_GATE = FROZEN_PREFLIGHT_AUDIT.parent / "p8-02-r1-no-seed-gate-v1/gate.json"
NO_SEED_CASES = {
    "wrong_operator_path": "test_wrong_operator_path_aborts_before_output_or_ids_and_audits",
    "wrong_audit_path": "test_correct_source_wrong_audit_inside_output_aborts_zero_ids",
    "sigint_checkpoint": "test_sigint_checkpoints_stop_then_down_and_probe_without_next_id",
    "sigkill_audit_only": "test_checkpoint_manifest_and_recovery_never_modify_raw",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def fsync_directory(path: Path) -> None:
    """Linux/Thor directory durability; Windows cannot open directories as files."""
    if os.name == "nt":
        return
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_json(path: Path, data: dict) -> None:
    """Durably replace one checkpoint; a process kill leaves old or new bytes."""
    payload = (json.dumps(data, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("xb") as out:
        out.write(payload)
        out.flush()
        os.fsync(out.fileno())
    os.replace(tmp, path)
    fsync_directory(path.parent)


def append_audit(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as out:
        out.write((json.dumps(record, sort_keys=True, allow_nan=False) + "\n").encode())
        out.flush()
        os.fsync(out.fileno())
    fsync_directory(path.parent)


def inventory(root: Path) -> list[dict]:
    files = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name in ("raw-manifest.json", "raw-manifest.json.tmp"):
            continue
        payload = path.read_bytes()
        files.append({"path": path.relative_to(root).as_posix(), "sha256": hashlib.sha256(payload).hexdigest(),
                      "bytes": len(payload), "record_count": len(payload.splitlines()) if payload else 0})
    return files


def checkpoint(root: Path, journal: dict) -> None:
    journal["checkpoint_utc"] = now()
    journal["checkpoint_monotonic_ns"] = time.monotonic_ns()
    atomic_json(root / "batch-journal.json", journal)
    atomic_json(root / "raw-manifest.json", {
        "schema_version": "p8-02-r1-raw-manifest-v1", "stage": journal["stage"],
        "source_head": journal["source_head"], "files": inventory(root)})


def git_head(path: Path) -> str:
    return subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def planned_rows(r1: dict, stage: str) -> list[dict]:
    rows = r1["development_gate"]["ordered_runs"] if stage == "D" else r1["ordered_official_runs"]
    expected = [(f"D{i:02d}", 886020 + i) for i in range(3)] if stage == "D" else [
        (f"B{i:02d}", 880020 + i) for i in range(20)]
    require([(r["trial_id"], r["seed"]) for r in rows] == expected, "R1 fixed ID/seed matrix mismatch")
    require(all(r["scenario_motion"] == "approaching" for r in rows), "R1 motion mismatch")
    return rows


def require_development_gate(dev: Path, r1: dict, expected_head: str,
                             expected_execution_sha: str,
                             expected_no_seed_gate_sha: str) -> None:
    journal = json.loads((dev / "batch-journal.json").read_text())
    summary = json.loads((dev / "batch-summary.json").read_text())
    require(journal.get("stage") == "D" and summary.get("stage") == "D",
            "development stage identity mismatch")
    require(summary.get("result") == "PASS" and journal.get("result") == "PASS",
            "D 3/3 gate not PASS")
    require(journal["source_head"] == expected_head and
            journal["execution_sha256"] == expected_execution_sha,
            "D gate source/config changed before B")
    require(journal.get("preflight_hashes", {}).get("no_seed_gate_artifact") ==
            expected_no_seed_gate_sha and
            summary.get("no_seed_gate_artifact_sha256") == expected_no_seed_gate_sha,
            "D gate no-seed demonstration hash changed before B")
    official = r1["official_execution"]
    require(journal.get("preflight_hashes", {}).get("graph") == official["graph_artifact_sha256"]
            and journal.get("preflight_hashes", {}).get("policy") == official["walking_policy_sha256"]
            and journal.get("preflight_commits", {}).get("microduck") == official["microduck_commit"]
            and journal.get("preflight_commits", {}).get("microduck_rl") == official["microduck_rl_commit"],
            "D gate selected upstream material differs before B")
    rescored = score_batch(dev, r1, journal)
    require(rescored["result"] == "PASS" and rescored["successes"] == 3 and
            rescored == summary["score"], "D gate retained raw differs from score")
    require(summary["final_sim_down"]["state_probe_result"] == "PASS", "D cleanup invalid")
    require(verify_manifest(dev), "D manifest differs from retained bytes")


def validate_no_seed_gate(path: Path, root: Path, reviewed_head: str,
                          protocol_sha256: str) -> str:
    """Recheck every preregistered demonstration and retained log before B00."""
    require(path.resolve() == FROZEN_NO_SEED_GATE, "no-seed gate artifact path mismatch")
    gate = json.loads(path.read_text())
    require(gate.get("schema_version") == "p8-02-r1-no-seed-gate-v1"
            and gate.get("result") == "PASS" and gate.get("source_head") == reviewed_head
            and gate.get("source_path") == str(root.resolve())
            and str(gate.get("host", "")).startswith("jetsonthor")
            and str(gate.get("python", "")).startswith("3.12."),
            "no-seed gate identity, source, or host mismatch")
    expected_files = ("config/p8_02_r1_protocol_v1.json", "scripts/p8_02_r1_batch.py",
        "scripts/p8_02_r1_trial.py", "scripts/p8_02_r1_score.py",
        "scripts/p8_02_r1_no_seed_gate.py", "tests/test_p8_02_r1_harness.py")
    expected_hashes = {relative: hashlib.sha256(subprocess.check_output([
        "git", "-C", str(root), "show", f"HEAD:{relative}"])).hexdigest()
        for relative in expected_files}
    require(gate.get("committed_sha256") == expected_hashes
            and expected_hashes[expected_files[0]] == protocol_sha256,
            "no-seed gate committed source/protocol hash mismatch")
    cases = gate.get("cases")
    require(isinstance(cases, list) and len(cases) == len(NO_SEED_CASES),
            "no-seed gate case count mismatch")
    for row, (name, method) in zip(cases, NO_SEED_CASES.items()):
        testcase = f"tests.test_p8_02_r1_harness.R1HarnessTests.{method}"
        command = [gate.get("python_executable"), "-m", "unittest", testcase, "-v"]
        log = path.parent / f"{name}.log"
        require(row.get("name") == name and row.get("testcase") == testcase
                and row.get("command") == command and row.get("exit") == 0
                and row.get("result") == "PASS" and row.get("log") == log.name
                and log.is_file(), f"no-seed {name} result/log mismatch")
        payload = log.read_bytes()
        require(row.get("log_sha256") == hashlib.sha256(payload).hexdigest()
                and row.get("log_bytes") == len(payload)
                and b"Ran 1 test" in payload and b"OK" in payload
                and b"FAILED" not in payload,
                f"no-seed {name} retained log hash/result mismatch")
    return sha(path)


def preflight(args) -> tuple[dict, dict, dict]:
    """All operator/upstream checks finish before any output root or ID row exists."""
    record = {"schema_version": "p8-02-r1-preflight-audit-v1", "at_utc": now(),
              "at_monotonic_ns":time.monotonic_ns(),
              "stage": args.stage, "argv": sys.argv, "result": "FAIL", "assigned_ids": 0,
              "python": platform.python_version(), "hostname": socket.gethostname(),
              "requested": {k: str(getattr(args, k)) for k in ("root", "protocol", "execution",
                  "microduck", "microduck_rl", "graph", "policy", "sim_executable",
                  "output", "audit", "sim_state", "body_port", "reviewed_head")},
              "resolved": {}, "hashes": {}, "commits": {}, "checks": []}
    # The audit destination is frozen independently of operator arguments so
    # even an early bad source/CLI path cannot create the unassigned output root.
    audit = FROZEN_PREFLIGHT_AUDIT
    try:
        root = args.root.resolve(strict=True)
        protocol_path = args.protocol.resolve(strict=True)
        execution_path = args.execution.resolve(strict=True)
        upstream = args.microduck.resolve(strict=True)
        upstream_rl = args.microduck_rl.resolve(strict=True)
        output = args.output.resolve()
        state = args.sim_state.resolve()
        record["resolved"].update({k: str(v) for k, v in {
            "source": root, "protocol": protocol_path, "execution": execution_path,
            "microduck": upstream, "microduck_rl": upstream_rl,
            "output": output, "state": state, "audit_requested": args.audit.resolve()}.items()})
        require(socket.gethostname().startswith("jetsonthor") and
                platform.python_version_tuple()[:2] == ("3", "12"), "Thor Python 3.12 required")
        require(len(args.reviewed_head) == 40 and all(c in "0123456789abcdef" for c in args.reviewed_head),
                "reviewed head must be exact lowercase SHA")
        require(git_head(root) == args.reviewed_head, "source head differs from reviewed head")
        require(not subprocess.check_output(["git", "-C", str(root), "status", "--porcelain"],
                                             text=True).strip(), "source checkout not clean")
        r1 = json.loads(protocol_path.read_text())
        execution = json.loads(execution_path.read_text())
        official = r1["official_execution"]
        require(audit == Path(official["preflight_audit_log_path"]).resolve(),
                "frozen preflight audit path differs from prospective protocol")
        require(r1.get("schema_version") == "p8-02-r1-remediation-protocol-v1", "R1 protocol schema mismatch")
        require(protocol_path == root / "config/p8_02_r1_protocol_v1.json", "R1 protocol source path mismatch")
        require(execution_path == root / f"config/p8_02_r1_{args.stage.lower()}_execution_v1.json",
                "R1 execution source path mismatch")
        require(root == Path(official["source_path"]).resolve(), "operator source path mismatch")
        require(upstream == Path(official["microduck_path"]).resolve(), "operator microduck path mismatch")
        require(upstream_rl == Path(official["microduck_rl_path"]).resolve(), "operator microduck_rl path mismatch")
        require(output == Path(official["development_output_dir"] if args.stage == "D" else
                               official["output_dir"]).resolve(), "operator output path mismatch")
        require(state == Path(official["isolated_sim_state"]).resolve() and
                args.body_port == official["isolated_body_port"], "operator state/port mismatch")
        require(args.audit.resolve() == audit, "operator audit path mismatch")
        require(Path(__file__).resolve() == root / "scripts/p8_02_r1_batch.py",
                "R1 batch script is outside reviewed source")
        require(not output.exists(), "R1 output root already exists; never overwrite")
        require(git_head(upstream) == official["microduck_commit"], "microduck upstream commit mismatch")
        require(git_head(upstream_rl) == official["microduck_rl_commit"], "microduck_rl upstream commit mismatch")
        graph = args.graph.resolve(strict=True)
        policy = args.policy.resolve(strict=True)
        sim = args.sim_executable.resolve(strict=True)
        record["resolved"].update({"graph":str(graph),"policy":str(policy),"sim":str(sim),
                                   "audit_frozen":str(audit)})
        require(graph == Path(official["graph_artifact_path"]) and
                sha(graph) == official["graph_artifact_sha256"], "graph path/hash mismatch")
        graph_manifest = json.loads((root / "data/manifests/controller-graph-v2.json").read_text())
        require(Path(graph_manifest["thor_artifact"]).resolve() == graph and
                graph_manifest["graph_sha256"] == sha(graph), "graph manifest path/hash mismatch")
        require(policy == Path(official["walking_policy_path"]) and
                sha(policy) == official["walking_policy_sha256"], "policy path/hash mismatch")
        require(sim == Path(official["sim_executable_path"]) and
                sim == upstream / "scripts/duck-sim" and sim.is_file(), "sim executable path mismatch")
        require(os.access(sim, os.X_OK), "sim executable is not executable")
        params_source = (upstream / "robotd-params/src/lib.rs").read_text()
        require(f"deadman_ms: {execution['deadman_timeout_ms']}" in params_source,
                "upstream robotd deadman default mismatch")
        require(execution["r1_stage"] == args.stage, "execution stage mismatch")
        require(execution["frozen_output_dir"] == str(output), "execution output mismatch")
        require(execution["walking_policy_path"] == str(policy) and
                execution["walking_policy_sha256"] == sha(policy), "execution policy mismatch")
        require(execution["graph_sha256"] == sha(graph), "execution graph mismatch")
        require(execution["microduck_commit"] == git_head(upstream) and
                execution["microduck_rl_commit"] == git_head(upstream_rl), "execution upstream mismatch")
        require(execution_path.read_bytes() == subprocess.check_output([
            "git", "-C", str(root), "show", f"HEAD:{execution_path.relative_to(root).as_posix()}"]),
            "execution bytes not committed")
        require(protocol_path.read_bytes() == subprocess.check_output([
            "git", "-C", str(root), "show", f"HEAD:{protocol_path.relative_to(root).as_posix()}"]),
            "protocol bytes not committed")
        validate_r1_selection(execution)
        validate_r1_material(root, execution)
        rows = planned_rows(r1, args.stage)
        require([(r["run_id"], r["seed"], r["arm_elapsed_s"]) for r in execution["ordered_official_runs"]]
                == [(r["trial_id"], r["seed"], r["arm_elapsed_s"]) for r in rows],
                "execution run matrix mismatch")
        probe = probe_final_sim_state(state, args.body_port, phase="preflight")
        require(probe["result"] == "PASS", "isolated socket or body port occupied")
        gate_sha = validate_no_seed_gate(Path(execution["no_seed_gate_artifact_path"]),
                                         root, args.reviewed_head,
                                         execution["r1_protocol_sha256"])
        if args.stage == "B":
            dev = Path(official["development_output_dir"]).resolve(strict=True)
            require(dev != output, "D/B roots must differ")
            require_development_gate(dev, r1, args.reviewed_head,
                                     sha(root / "config/p8_02_r1_d_execution_v1.json"), gate_sha)
        record["resolved"] = {k: str(v) for k, v in {"source":root,"protocol":protocol_path,
            "execution":execution_path,"microduck":upstream,"microduck_rl":upstream_rl,
            "graph":graph,"policy":policy,"sim":sim,"output":output,"state":state,"audit":audit}.items()}
        record["hashes"] = {"protocol":sha(protocol_path),"execution":sha(execution_path),
                            "graph":sha(graph),"policy":sha(policy),"sim":sha(sim),
                            "batch_script":sha(root/"scripts/p8_02_r1_batch.py"),
                            "trial_script":sha(root/"scripts/p8_02_r1_trial.py"),
                            "score_script":sha(root/"scripts/p8_02_r1_score.py")}
        record["hashes"]["no_seed_gate_artifact"] = gate_sha
        record["commits"] = {"source":git_head(root),"microduck":git_head(upstream),
                             "microduck_rl":git_head(upstream_rl)}
        record["checks"] = ["host_python", "reviewed_clean_source", "resolved_paths", "upstream_heads",
                            "graph_policy_hash", "committed_execution", "selected_material",
                            "fixed_seed_matrix", "isolated_state_probe", "no_seed_gate_raw_logs"] + (
                            ["development_gate"] if args.stage == "B" else [])
        record["result"] = "PASS"
        return r1, execution, record
    except BaseException as error:
        record["failure"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        append_audit(audit, record)


def verify_manifest(root: Path) -> bool:
    try:
        stored = json.loads((root / "raw-manifest.json").read_text())["files"]
        return stored == inventory(root)
    except (OSError, ValueError, KeyError):
        return False


def recover_only(root: Path) -> dict:
    """SIGKILL/power recovery inventories untouched raw; it never resumes trials."""
    journal = json.loads((root / "batch-journal.json").read_text())
    before = inventory(root)
    in_flight = []
    for item in journal["ids"]:
        for attempt in item["attempts"]:
            if attempt.get("status") not in ("TRIAL_EXITED", "PREARM_FAILED", "CLEANED"):
                attempt["status"] = "INTERRUPTED_UNKNOWN_ARM"
                attempt["armed"] = True
                in_flight.append(f"{item['trial_id']}/{attempt['name']}")
    return {"schema_version":"p8-02-r1-recovery-audit-v1","at_utc":now(),
            "result":"AUDIT_ONLY",
            "mode":"AUDIT_ONLY_NO_RETRY","source_journal_sha256":sha(root / "batch-journal.json"),
            "manifest_agreed_before_recovery":verify_manifest(root),
            "files":before,"in_flight_unknown_arm":in_flight,"journal_projection":journal}


def emergency_stop(socket_path: Path) -> dict:
    result = {"method":"robot.stop","at_utc":now(),"result":"FAIL"}
    try:
        client = RobotdClient(str(socket_path), timeout_s=2.0)
        client.connect()
        result["ack"] = client.stop()
        result["result"] = "PASS"
        client.close()
    except BaseException as error:
        result["error"] = f"{type(error).__name__}: {error}"
    return result


def batch_pass(journal: dict, score: dict, final: dict, interrupted: bool) -> bool:
    """D is 3/3; B permits one fully audited safe armed causal failure."""
    stage = journal["stage"]
    ids = journal["ids"]
    planned = 3 if stage == "D" else 20 if stage == "B" else 0
    if (interrupted or len(ids) != planned or score.get("result") != "PASS"
            or not isinstance(journal.get("preflight_hashes", {}).get("no_seed_gate_artifact"), str)
            or score.get("stage") != stage or score.get("planned") != planned
            or score.get("successes", -1) < (3 if stage == "D" else 19)
            or score.get("all_raw_accounted") is not True
            or score.get("zero_safety_limit_violations") is not True
            or final.get("exit") != 0 or final.get("interrupted") is not False
            or final.get("state_probe_result") != "PASS"):
        return False
    trials = score.get("trials", [])
    if len(trials) != planned or sum(t.get("success") is True for t in trials) != score["successes"]:
        return False
    for item, trial in zip(ids, trials):
        attempts = item.get("attempts", [])
        if (item.get("status") != "ARMED_COMPLETE" or not 1 <= len(attempts) <= 3
                or attempts[-1].get("armed") is not True
                or type(attempts[-1].get("trial_exit")) is not int
                or item.get("trial_id") != trial.get("trial_id")
                or item.get("seed") != trial.get("seed")
                or trial.get("raw_accounted") is not True
                or trial.get("safety_limit_violations") != 0):
            return False
        if stage == "D" and (trial.get("success") is not True
                             or attempts[-1]["trial_exit"] != 0):
            return False
        if stage == "B" and trial.get("success") is True and attempts[-1]["trial_exit"] != 0:
            return False
    return True


def run_child(command: list[str], log: Path, env: dict, progress=None) -> tuple[int, bool]:
    with log.open("wb") as out:
        child = subprocess.Popen(command, stdout=out, stderr=subprocess.STDOUT, env=env)
        try:
            while True:
                try:
                    code = child.wait(timeout=0.05)
                    if progress is not None:
                        progress()
                    return code, False
                except subprocess.TimeoutExpired:
                    if progress is not None:
                        progress()
        except KeyboardInterrupt:
            child.send_signal(signal.SIGINT)
            try:
                child.wait(timeout=8)
            except subprocess.TimeoutExpired:
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
            if progress is not None:
                progress()
            return child.returncode, True
        except BaseException:
            if child.poll() is None:
                child.send_signal(signal.SIGINT)
                try:
                    child.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    child.terminate()
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait()
            raise
        finally:
            out.flush()
            os.fsync(out.fileno())


def run(args) -> dict:
    if args.recover_only:
        require(args.audit.resolve() == FROZEN_PREFLIGHT_AUDIT,
                "recovery audit must use frozen external path")
        root = args.output.resolve(strict=True)
        report = recover_only(root)
        append_audit(FROZEN_PREFLIGHT_AUDIT, report)
        return report
    r1, execution, preflight_record = preflight(args)
    root = args.root.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    rows = planned_rows(r1, args.stage)
    journal = {"schema_version":"p8-02-r1-batch-journal-v1","stage":args.stage,
               "result":"RUNNING","source_path":str(root),"source_head":args.reviewed_head,
               "protocol_sha256":preflight_record["hashes"]["protocol"],
               "execution_sha256":preflight_record["hashes"]["execution"],
               "preflight_audit_sha256":sha(FROZEN_PREFLIGHT_AUDIT),
               "preflight_hashes":preflight_record["hashes"],
               "preflight_commits":preflight_record["commits"],
               "preflight_resolved_paths":preflight_record["resolved"],
               "ids":[{"trial_id":r["trial_id"],"seed":r["seed"],"status":"PENDING","attempts":[]}
                      for r in rows],"final_sim_down":None}
    checkpoint(output,journal)
    env=dict(os.environ)
    env.update({"DUCK_SIM_VIEWER":"0","DUCK_SIM_STATE":str(args.sim_state),
                "DUCK_SIM_RL":str(args.microduck_rl),"DUCK_SIM_PORT":str(args.body_port),
                "PYTHONPATH":str(root),"PATH":str(args.microduck.parent/
                    "rustup/toolchains/stable-aarch64-unknown-linux-gnu/bin")+os.pathsep+env["PATH"]})
    sim = args.microduck / "scripts/duck-sim"
    interrupted=False
    error=None
    try:
        for index, planned in enumerate(rows):
            item=journal["ids"][index]
            # Retries are limited to externally evidenced pre-arm acquisition failures.
            for number in range(1,4):
                folder=output/planned["trial_id"]/f"attempt-{number:02d}"
                folder.mkdir(parents=True,exist_ok=False)
                attempt={"name":folder.name,"status":"ACQUIRING","armed":False,"steps":[],
                         "started_utc":now(),"started_monotonic_ns":time.monotonic_ns()}
                item["attempts"].append(attempt)
                item["status"]="ACQUIRING"
                checkpoint(output,journal)
                prearm_failed=False
                for name,command in (("down",[str(sim),"down"]),("up",[str(sim),"up"]),
                    ("policy_load",[str(sim),"ctl","policy","load","walk",execution["walking_policy_path"]]),
                    ("policy_readback",[str(sim),"ctl","policy","list","--json"])):
                    log=folder/("policy-readback.json" if name=="policy_readback" else f"{name}.log")
                    exit_code,step_interrupted=run_child(command,log,env)
                    step={"name":name,"command":command,"exit":exit_code,"sha256":sha(log),
                          "bytes":log.stat().st_size,"at_utc":now(),
                          "at_monotonic_ns":time.monotonic_ns()}
                    attempt["steps"].append(step)
                    attempt["status"]=f"ACQUIRED_{name.upper()}" if exit_code==0 else "PREARM_FAILED"
                    checkpoint(output,journal)
                    if step_interrupted:
                        attempt["status"]="INTERRUPTED_UNKNOWN_ARM"
                        checkpoint(output,journal)
                        raise KeyboardInterrupt("prearm acquisition interrupted")
                    if exit_code:
                        # Only simulator startup is an exogenous, retryable
                        # pre-arm acquisition here. A failed down/policy step
                        # needs operator diagnosis before consuming another ID.
                        if name != "up":
                            attempt["status"]="PREARM_UNCLASSIFIED"
                            checkpoint(output,journal)
                            raise RuntimeError(f"nonretryable prearm {name} failed")
                        prearm_failed=True
                        break
                    if name=="policy_readback":
                        try:
                            validate_loaded_walk_policy(json.loads(log.read_text()),
                                Path(execution["walking_policy_path"]),execution["walking_policy_sha256"])
                        except (ValueError,KeyError,TypeError,OSError) as exc:
                            attempt["status"]="OPERATOR_OR_CONFIG_FAILURE"
                            attempt["error"]=f"policy_readback:{exc}"
                            checkpoint(output,journal)
                            raise RuntimeError(attempt["error"])
                if prearm_failed:
                    if number==3:
                        item["status"]="PREARM_FAILED"
                    checkpoint(output,journal)
                    continue
                time.sleep(1)
                command=[sys.executable,str(root/"scripts/p8_02_r1_trial.py"),
                         "--root",str(root),"--protocol",str(args.execution.relative_to(root)),
                         "--trial-index",str(index),"--attempt",str(number),
                         "--armed-marker",str(folder/"armed.json"),
                         "--progress",str(folder/"progress.jsonl"),
                         "--socket",str(args.sim_state/"duck-a.sock"),"--body-port",str(args.body_port),
                         "--microduck",str(args.microduck),"--microduck-rl",str(args.microduck_rl),
                         "--source-head",args.reviewed_head,"--policy-readback",str(folder/"policy-readback.json"),
                         "--raw",str(folder/"trace.jsonl"),"--events",str(folder/"events.jsonl"),
                         "--ledger",str(folder/"neural-ledger.jsonl"),"--visual",str(folder/"visual-frames.jsonl"),
                         "--summary",str(folder/"summary.json")]
                attempt["status"]="TRIAL_CHILD_STARTED"
                attempt["command"]=command
                checkpoint(output,journal)
                progress_path=folder/"progress.jsonl"
                def checkpoint_child_progress():
                    data=progress_path.read_bytes() if progress_path.is_file() else b""
                    entries=[json.loads(line) for line in data.split(b"\n")[:-1]]
                    armed_now=(folder/"armed.json").is_file()
                    if (entries != attempt.get("progress",[]) or armed_now != attempt["armed"]):
                        attempt["progress"]=entries
                        attempt["armed"]=armed_now
                        attempt["status"]=("NEURAL_OBSERVATION_ARMED" if armed_now else
                                           entries[-1]["state"] if entries else "TRIAL_CHILD_STARTED")
                        checkpoint(output,journal)
                exit_code,was_interrupted=run_child(command,folder/"trial.log",env,
                                                    progress=checkpoint_child_progress)
                attempt["armed"]=(folder/"armed.json").is_file()
                attempt["trial_exit"]=exit_code
                attempt["status"]="INTERRUPTED_UNKNOWN_ARM" if was_interrupted else "TRIAL_EXITED"
                if (folder/"summary.json").is_file():
                    attempt["summary_sha256"]=sha(folder/"summary.json")
                    attempt["summary"]=json.loads((folder/"summary.json").read_text())
                checkpoint(output,journal)
                if was_interrupted:
                    interrupted=True
                    item["status"]="INTERRUPTED_UNKNOWN_ARM"
                    break
                if not attempt["armed"]:
                    # A child may exit just before a durable arm marker; never infer
                    # that an unclassified harness failure is exogenous or retry it.
                    item["status"]="PREARM_UNCLASSIFIED"
                else:
                    item["status"]="ARMED_COMPLETE"
                checkpoint(output,journal)
                break
            if interrupted or item["status"] not in ("ARMED_COMPLETE",):
                break
    except BaseException as exc:
        error=f"{type(exc).__name__}: {exc}"
        interrupted=True
        if "item" in locals() and item.get("status") not in ("ARMED_COMPLETE", "PREARM_FAILED"):
            item["status"]="INTERRUPTED_UNKNOWN_ARM"
            if "attempt" in locals() and attempt.get("status") not in ("TRIAL_EXITED", "PREARM_FAILED"):
                attempt["status"]="INTERRUPTED_UNKNOWN_ARM"
            checkpoint(output,journal)
    finally:
        if interrupted:
            journal["interrupt_stop"]=emergency_stop(args.sim_state/"duck-a.sock")
            checkpoint(output,journal)
        final={}
        down_log=output/"final-down.log"
        try:
            final["exit"],final["interrupted"]=run_child([str(sim),"down"],down_log,env)
            final["sha256"]=sha(down_log)
        except BaseException as exc:
            final["error"]=f"{type(exc).__name__}: {exc}"
        journal["final_sim_down"]=dict(final)
        checkpoint(output,journal)
        try:
            probe=probe_final_sim_state(args.sim_state,args.body_port,phase="final_down")
        except BaseException as exc:
            probe={"result":"FAIL","error":f"{type(exc).__name__}: {exc}"}
        atomic_json(output/"final-state-probe.json",probe)
        final["state_probe_result"]=probe["result"]
        final["state_probe_sha256"]=sha(output/"final-state-probe.json")
        journal["final_sim_down"]=final
        journal["error"]=error
        checkpoint(output,journal)
    try:
        score=score_batch(output,r1,journal)
    except BaseException as exc:
        score={"schema_version":"p8-02-r1-score-v1","result":"FAIL",
               "error":f"{type(exc).__name__}: {exc}"}
    atomic_json(output/"score.json",score)
    try:
        final_gate_sha=validate_no_seed_gate(Path(execution["no_seed_gate_artifact_path"]),
            root,args.reviewed_head,execution["r1_protocol_sha256"])
        gate_integrity=(final_gate_sha==journal["preflight_hashes"]["no_seed_gate_artifact"])
    except BaseException as exc:
        gate_integrity=False
        journal["no_seed_gate_error"]=f"{type(exc).__name__}: {exc}"
    journal["result"]="PASS" if (gate_integrity and
        batch_pass(journal,score,final,interrupted)) else "FAIL"
    checkpoint(output,journal)
    summary={"schema_version":"p8-02-r1-batch-summary-v1","stage":args.stage,
             "result":journal["result"],"source_head":args.reviewed_head,
             "no_seed_gate_artifact_sha256":journal["preflight_hashes"].get("no_seed_gate_artifact"),
             "score":score,"final_sim_down":final,"error":error}
    atomic_json(output/"batch-summary.json",summary)
    checkpoint(output,journal)
    if not verify_manifest(output):
        journal["result"]="FAIL"
        journal["manifest_error"]="final manifest differs from retained files"
        summary["result"]="FAIL"
        summary["manifest_error"]=journal["manifest_error"]
        atomic_json(output/"batch-summary.json",summary)
        checkpoint(output,journal)
    return summary


def main() -> None:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stage",choices=("D","B"),required=True)
    ap.add_argument("--root",type=Path,required=True)
    ap.add_argument("--protocol",type=Path,required=True)
    ap.add_argument("--execution",type=Path,required=True)
    ap.add_argument("--reviewed-head",required=True)
    ap.add_argument("--microduck",type=Path,required=True)
    ap.add_argument("--microduck-rl",type=Path,required=True)
    ap.add_argument("--graph",type=Path,required=True)
    ap.add_argument("--policy",type=Path,required=True)
    ap.add_argument("--sim-executable",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--audit",type=Path,required=True)
    ap.add_argument("--sim-state",type=Path,required=True)
    ap.add_argument("--body-port",type=int,required=True)
    ap.add_argument("--recover-only",action="store_true")
    args=ap.parse_args()
    result=run(args)
    if args.recover_only:
        print(json.dumps({"result":"AUDIT_ONLY","in_flight_unknown_arm":result["in_flight_unknown_arm"]},
                         sort_keys=True))
        return
    print(json.dumps({"result":result["result"],"stage":args.stage},sort_keys=True))
    if result["result"]!="PASS":
        raise SystemExit(1)


if __name__=="__main__":
    main()
