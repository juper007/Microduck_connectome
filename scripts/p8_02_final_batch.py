"""Twenty independent official Thor P8-02 final approaching resets."""
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
from scripts.p8_02_final_trial import (
    validate_frozen_material, validate_frozen_output_dir,
    validate_frozen_selection,
)
from scripts.p8_02_final_score import score_batch


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def exception_label(error: Exception) -> str:
    """Keep a compact failure in the batch manifest without discarding raw files."""
    return f"{type(error).__name__}: {error}"


def probe_final_sim_state(sim_state: Path, body_port: int, *, phase: str = "final_down") -> dict:
    """Retain listener evidence before launch or after final duck-sim down."""
    socket_path = sim_state / "duck-a.sock"
    unix_connectable = False
    if socket_path.exists() and hasattr(socket, "AF_UNIX"):
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                probe.settimeout(.25)
                unix_connectable = probe.connect_ex(str(socket_path)) == 0
        except OSError:
            unix_connectable = False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(.25)
        body_port_connectable = probe.connect_ex(("127.0.0.1", body_port)) == 0
    return {"schema_version": "p8-02-final-sim-state-probe-v1", "phase": phase,
            "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "robotd_socket_path": str(socket_path),
            "robotd_socket_path_exists": socket_path.exists(),
            "robotd_socket_connectable": unix_connectable,
            "body_port": body_port, "body_port_connectable": body_port_connectable,
            "result": "PASS" if not socket_path.exists()
            and not unix_connectable and not body_port_connectable else "FAIL"}


def validate_trial_artifacts(summary: dict, folder: Path) -> None:
    """A PASS summary must name the retained, hashed raw evidence in this trial."""
    for key in ("trace_artifact", "events_artifact", "neural_ledger_artifact", "visual_frame_artifact"):
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
    ap.add_argument("--protocol", type=Path, required=True,
                    help="repo-relative frozen P8-R3 development protocol")
    ap.add_argument("--microduck", type=Path, required=True)
    ap.add_argument("--microduck-rl", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--sim-state", type=Path, required=True)
    ap.add_argument("--body-port", type=int, required=True)
    a = ap.parse_args()
    if not socket.gethostname().startswith("jetsonthor") or platform.python_version_tuple()[:2] != ("3", "12"):
        raise RuntimeError("official Thor Python 3.12 required")
    root = a.root.resolve()
    head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    if subprocess.check_output(
            ["git", "-C", str(root), "status", "--porcelain"], text=True).strip():
        raise RuntimeError("batch requires clean committed source")
    protocol_path = (root / a.protocol).resolve()
    if not protocol_path.is_relative_to(root / "config"):
        raise RuntimeError("official protocol path must be inside source config")
    protocol = json.loads(protocol_path.read_text())
    validate_frozen_selection(protocol)
    if protocol.get("schema_version") != "p8-02-final-approach-v1":
        raise RuntimeError("P8-02 final batch requires final approach execution config")
    if protocol_path.read_bytes() != subprocess.check_output([
        "git", "-C", str(root), "show", f"HEAD:{protocol_path.relative_to(root).as_posix()}"]):
        raise RuntimeError("uncommitted protocol bytes")
    validate_frozen_material(root, protocol)
    validate_frozen_output_dir(protocol, a.output)
    if (a.sim_state != Path(protocol["isolated_sim_state"])
            or a.body_port != protocol["isolated_body_port"]):
        raise RuntimeError("P8-02 final simulator state/port differs from frozen isolation")
    a.output.mkdir(parents=True, exist_ok=False)
    preflight_probe = probe_final_sim_state(a.sim_state, a.body_port, phase="preflight")
    preflight_path = a.output / "preflight-state-probe.json"
    preflight_path.write_text(json.dumps(preflight_probe, sort_keys=True, indent=2,
                                         allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    if preflight_probe["result"] != "PASS":
        raise RuntimeError("P8-02 final isolated simulator state/port already occupied")
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
    planned = protocol["ordered_official_runs"]
    try:
        if len(planned) != 20 or [r["seed"] for r in planned] != protocol["scenario_seeds"]:
            raise ValueError("frozen twenty-reset seed matrix mismatch")
        for index, planned_row in enumerate(planned):
            seed = planned_row["seed"]
            folder = a.output / planned_row["run_id"]
            row = {"trial_index": index, "seed": seed,
                   "run_id": planned_row["run_id"],
                   "selected_v2": protocol["selected_v2"],
                   "visual_representation": protocol["visual_representation"],
                   "visual_hz": protocol["visual_hz"],
                   "scenario_sha256": protocol["scenario_config_sha256"],
                   "trial_started": False,
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
                        row["validity_class"] = "PRE_ARM_REVIEW"
                        break
                    if name == "policy_readback":
                        try:
                            validate_loaded_walk_policy(json.loads(log.read_text()),
                                                        Path(protocol["walking_policy_path"]),
                                                        protocol["walking_policy_sha256"])
                        except (ValueError, KeyError, TypeError, OSError) as error:
                            row["failure"] = f"policy_readback_mismatch: {error}"
                            row["validity_class"] = "PRE_ARM_REVIEW"
                            break
                if "failure" in row:
                    break
                time.sleep(1.0)
                row["trial_started"] = True
                command = [
                    sys.executable, str(root / "scripts/p8_02_final_trial.py"),
                    "--root", str(root), "--trial-index", str(index),
                    "--protocol", str(protocol_path.relative_to(root)),
                    "--socket", str(a.sim_state / "duck-a.sock"),
                    "--body-port", str(a.body_port),
                    "--microduck", str(a.microduck), "--microduck-rl", str(a.microduck_rl),
                    "--source-head", head,
                    "--policy-readback", str(folder / "policy-readback.json"),
                    "--raw", str(folder / "trace.jsonl"),
                    "--events", str(folder / "events.jsonl"),
                    "--ledger", str(folder / "neural-ledger.jsonl"),
                    "--visual", str(folder / "visual-frames.jsonl"),
                    "--summary", str(folder / "summary.json"),
                ]
                row["trial_exit"] = run_logged(command, folder / "trial.log", env=env, cwd=root)
                row["trial_log_sha256"] = sha(folder / "trial.log")
                if (folder / "summary.json").exists():
                    row["summary_sha256"] = sha(folder / "summary.json")
                    row["summary"] = json.loads((folder / "summary.json").read_text())
                    if not isinstance(row["summary"], dict):
                        raise ValueError("trial summary is not an object")
                    row["validity_class"] = row["summary"].get("validity_class")
                    if row["summary"].get("result") == "PASS":
                        validate_trial_artifacts(row["summary"], folder)
                else:
                    row["failure"] = "trial_exited_without_summary"
            except Exception as error:
                row["failure"] = f"trial_exception: {exception_label(error)}"
            # Every final ID retains its own outcome and fresh simulator reset.
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
        try:
            probe = probe_final_sim_state(a.sim_state, a.body_port)
        except Exception as error:
            probe = {"schema_version": "p8-02-final-sim-state-probe-v1",
                     "result": "FAIL", "error": exception_label(error)}
        probe_path = a.output / "final-state-probe.json"
        probe_path.write_text(json.dumps(probe, sort_keys=True, indent=2,
                                         allow_nan=False) + "\n", encoding="utf-8", newline="\n")
        final_down["state_probe_result"] = probe["result"]
        final_down["state_probe_sha256"] = sha(probe_path)
    for unstarted in planned[len(rows):]:
        rows.append({"run_id": unstarted["run_id"], "seed": unstarted["seed"],
                     "selected_v2": protocol["selected_v2"],
                     "visual_representation": protocol["visual_representation"],
                     "visual_hz": protocol["visual_hz"],
                     "scenario_sha256": protocol["scenario_config_sha256"],
                     "trial_started": False, "failure": "unstarted_after_prior_failure"})
    official_passes = sum(
        row.get("summary", {}).get("r3_official_screen_result") == "PASS"
        and row.get("summary", {}).get("result") == "PASS"
        for row in rows)
    try:
        final_protocol = json.loads((root / protocol["final_protocol_path"]).read_text())
        score = score_batch(a.output, final_protocol)
    except Exception as error:
        score = {"schema_version": "p8-02-final-approach-score-v1",
                 "result": "FAIL", "error": exception_label(error)}
    score_path = a.output / "score.json"
    score_path.write_text(json.dumps(score, sort_keys=True, indent=2,
                                     allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    result = "PASS" if (batch_error is None
                            and len(rows) == len(protocol["ordered_official_runs"])
                            and len(rows) == 20
                            and official_passes >= 19
                            and score["result"] == "PASS"
                            and all("failure" not in row and "summary" in row for row in rows)
                            and final_down.get("exit") == 0
                            and final_down.get("state_probe_result") == "PASS"
                            and "failure" not in final_down
                            and "sha256" in final_down) else "FAIL"
    report = {
        "schema_version": "p8-02-final-approach-batch-v1",
        "evidence_role": "final_phase8_approach",
        "result": result, "execution_target": "Thor",
        "source_head": head, "protocol_sha256": sha(protocol_path),
        "protocol_schema_version": protocol["schema_version"],
        "started_utc": started_utc, "ended_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "planned_trials": len(protocol["ordered_official_runs"]),
        "started_trials": sum(row["trial_started"] for row in rows),
        "completed_trials": sum("summary" in row for row in rows),
        "trials": rows, "final_sim_down": final_down,
        "preflight_state_probe_sha256": sha(preflight_path),
        "official_passes": official_passes,
        "raw_score_result": score["result"], "raw_score_sha256": sha(score_path),
        "official_passes_planned": 20,
        "batch_error": batch_error,
        "historical_failed_pr_66_untouched": True,
        "historical_failed_pr_68_untouched": True,
    }
    summary_path = a.output / "batch-summary.json"
    summary_path.write_text(json.dumps(report, sort_keys=True, indent=2,
                                       allow_nan=False) + "\n", encoding="utf-8")
    files = []
    for path in sorted(a.output.rglob("*")):
        if not path.is_file() or path.name == "raw-manifest.json":
            continue
        payload = path.read_bytes()
        files.append({
            "path": path.relative_to(a.output).as_posix(),
            "bytes": len(payload),
            "record_count": len(payload.splitlines()) if payload else 0,
            "sha256": hashlib.sha256(payload).hexdigest(),
        })
    manifest_path = a.output / "raw-manifest.json"
    manifest_path.write_text(json.dumps({
        "schema_version": "p8-02-final-approach-raw-manifest-v1", "source_head": head,
        "protocol_sha256": sha(protocol_path),
        "protocol_schema_version": protocol["schema_version"], "files": files,
    }, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"result": result, "completed_trials": len(rows),
                      "trial_results": [r.get("summary", {}).get("result", r.get("failure"))
                                        for r in rows],
                      "batch_summary_sha256": sha(summary_path),
                      "raw_manifest_sha256": sha(manifest_path)}, sort_keys=True))
    if result != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
