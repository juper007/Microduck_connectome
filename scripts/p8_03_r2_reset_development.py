"""Thor-only P8-03-R2 pose preparation pilot and held-out reset gate.

Never arms a trial or assigns a final seed. Every fresh reset is counted.
"""
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

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from microduck_connectome.p8_03_r2_reset import (
    REFERENCE, alignment_eligible, pose_deltas, qualification,
)
from microduck_connectome.robotd_client import RobotdClient
from scripts.p6_motion_fixture import JsonLines
from scripts.p8_02_final_batch import probe_final_sim_state
from scripts.p8_02_r1_batch import emergency_stop
from scripts.p8_03_r1_durability import atomic_json, durable_directory, process_start_ticks
from scripts.p8_03_r2_diagnose import TimedPoseReader, captured
from scripts.p8_02_r1_trial import acknowledged_precondition_move
from scripts.p7_pretrial_acquisition import validate_loaded_walk_policy

PARENT = Path("/home/juper007/projects/microduck-connectome-thor/evidence/p8-v2-final")
STATE = Path("/tmp/p8-03-r2-reset-development-state")
PORT = 7898


class PreparationFailure(RuntimeError):
    def __init__(self, trace: dict, reason: str):
        super().__init__(reason)
        self.trace = trace


def pose_row(reader: TimedPoseReader, previous: dict | None) -> dict:
    row = reader.read()
    if not alignment_eligible(row, previous):
        raise RuntimeError("pre-command pose freshness/bounds failure")
    return row


def prepare(reader: TimedPoseReader, sock: Path) -> dict:
    stop = emergency_stop(sock)
    if stop["result"] != "PASS":
        raise RuntimeError("acknowledged stop path unavailable")
    client = RobotdClient(str(sock), timeout_s=2)
    client.connect()
    command = JsonLines(str(sock))
    trace = {"initial_stop": stop, "moves": []}
    try:
        health = client.health()
        if health.get("healthy") is not True or health.get("degraded") is True:
            raise RuntimeError("robotd unhealthy before alignment")
        first = pose_row(reader, None)
        time.sleep(.05)
        second = pose_row(reader, first)
        trace["before"] = [first, second]
        origin = first["pose"]
        previous = second
        initial_error = abs(pose_deltas(second["pose"])["heading_rad"])
        start = time.monotonic()
        last_ack = None
        while abs(pose_deltas(previous["pose"])["heading_rad"]) > .03:
            error = pose_deltas(previous["pose"])["heading_rad"]
            if abs(error) <= .06 and not trace["moves"]:
                break
            if time.monotonic() - start >= 3.0:
                raise TimeoutError("three-second yaw alignment deadline")
            if math.hypot(previous["pose"]["x_m"] - origin["x_m"],
                          previous["pose"]["y_m"] - origin["y_m"]) > .03:
                raise RuntimeError("alignment translation bound exceeded")
            health = client.health()
            if health.get("healthy") is not True or health.get("degraded") is True:
                raise RuntimeError("robotd health lost during alignment")
            vyaw = max(-.2, min(.2, -2.0 * error))
            tick = time.monotonic_ns()
            if last_ack is not None and tick - last_ack > 100_000_000:
                raise RuntimeError("100 ms command TTL elapsed before refresh")
            ack, call_ns, write_ns, ack_ns = acknowledged_precondition_move(
                command, vx=0.0, vy=0.0, vyaw=vyaw)
            move = {"requested_vyaw_radps": vyaw, "ack": ack,
                    "call_ns": call_ns, "write_ns": write_ns, "ack_ns": ack_ns}
            trace["moves"].append(move)
            if ack_ns - tick > 100_000_000:
                raise RuntimeError("command ACK exceeded 100 ms TTL")
            if last_ack is not None and ack_ns - last_ack > 100_000_000:
                raise RuntimeError("100 ms command TTL refresh exceeded")
            last_ack = ack_ns
            current = pose_row(reader, previous)
            move["pose"] = current
            current_error = abs(pose_deltas(current["pose"])["heading_rad"])
            if current_error > initial_error + .015:
                raise RuntimeError("alignment response moved away from reference")
            if time.monotonic() - start > .35 and current_error > initial_error - .005:
                raise RuntimeError("alignment response stuck or wrong sign")
            previous = current
            if time.monotonic_ns() - tick < 50_000_000:
                time.sleep((50_000_000 - (time.monotonic_ns() - tick)) / 1e9)
        trace["alignment_duration_s"] = time.monotonic() - start
        trace["aligned_pose"] = previous
    except BaseException as error:
        trace["error"] = f"{type(error).__name__}: {error}"
        raise PreparationFailure(trace, trace["error"]) from error
    finally:
        command.close()
        client.close()
        trace["final_stop"] = emergency_stop(sock)
    if trace["final_stop"]["result"] != "PASS":
        raise RuntimeError("post-alignment stop was not acknowledged")
    # Fixed post-stop settling is separate from the subsequent qualification dwell.
    stop_ns = time.monotonic_ns()
    time.sleep(1.0)
    rows = []
    client = RobotdClient(str(sock), timeout_s=2)
    try:
        client.connect()
        states = []
        dwell_start = time.monotonic()
        for i in range(21):
            time.sleep(max(0, dwell_start + i * .05 - time.monotonic()))
            rows.append(reader.read())
            if i in (0, 10, 20):
                states.append(client.state(hz=50))
        trace["dwell_rows"] = rows
        health = client.health()
    except BaseException as error:
        trace["dwell_rows"] = rows
        trace["error"] = f"{type(error).__name__}: {error}"
        raise PreparationFailure(trace, trace["error"]) from error
    finally:
        client.close()
    trace["health"] = health
    trace["post_stop_states"] = states
    state_times = [state.get("t_ns") for state in states]
    if (any(type(t) is not int for t in state_times) or
            not all(a < b for a, b in zip(state_times, state_times[1:]))):
        trace["error"] = "nonadvancing robot.state clock"
        raise PreparationFailure(trace, trace["error"])
    applied = [v for state in states for v in state["move"]["applied"]]
    trace["gate"] = qualification(rows, stop_ack_ns=stop_ns,
                                  health=health, applied_velocity=applied)
    return trace


def run(output: Path, head: str, kind: str) -> None:
    expected = PARENT / ("p8-03-r2-reset-pilot-v1" if kind == "pilot" else
                         "p8-03-r2-reset-qualification-v1")
    if output != expected or output.exists():
        raise ValueError("dedicated unused R2 development output required")
    if (socket.gethostname().startswith("jetsonthor") is False or
            platform.python_version_tuple()[:2] != ("3", "12") or
            subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                                    text=True).strip() != head or
            subprocess.check_output(["git", "-C", str(ROOT), "status", "--porcelain"],
                                    text=True).strip()):
        raise RuntimeError("clean exact-head Thor Python 3.12 required")
    protocol = json.loads((ROOT / "config/p8_03_r2_protocol_v1.json").read_text())
    config = json.loads((ROOT / "config/p8_03_r1_execution_v1.json").read_text())
    for path_key, commit_key in (("microduck_path", "microduck_commit"),
                                 ("microduck_rl_path", "microduck_rl_commit")):
        if subprocess.check_output(["git", "-C", config[path_key], "rev-parse", "HEAD"],
                                   text=True).strip() != config[commit_key]:
            raise RuntimeError("upstream commit mismatch")
    for path_key, sha_key in (("graph_path", "graph_sha256"),
                              ("walking_policy_path", "walking_policy_sha256")):
        if hashlib.sha256(Path(config[path_key]).read_bytes()).hexdigest() != config[sha_key]:
            raise RuntimeError("pinned material mismatch")
    preflight = probe_final_sim_state(STATE, PORT, phase="r2_dev_reset_preflight")
    if preflight["result"] != "PASS":
        raise RuntimeError("development simulator state occupied")
    start_ticks = process_start_ticks(os.getpid())
    if start_ticks is None:
        raise RuntimeError("cannot identify Thor development process")
    durable_directory(output)
    atomic_json(output / "run.json", {
        "schema_version": "p8-03-r2-development-run-v1", "status": "RUNNING",
        "source_head": head, "kind": kind, "pid": os.getpid(),
        "process_start_ticks": start_ticks,
        "started_monotonic_ns": time.monotonic_ns(),
        "rule": "never relaunch into this output; inspect process identity after disconnect"})
    atomic_json(output / "preflight.json", preflight)
    env = dict(os.environ, DUCK_SIM_VIEWER="0", DUCK_SIM_STATE=str(STATE),
               DUCK_SIM_KEYFRAME="SIT", DUCK_SIM_RL=config["microduck_rl_path"],
               DUCK_SIM_PORT=str(PORT), PYTHONPATH=str(ROOT))
    env["PATH"] = (str(Path(config["microduck_path"]).parent /
                       "rustup/toolchains/stable-aarch64-unknown-linux-gnu/bin") +
                   os.pathsep + env["PATH"])
    count = 3 if kind == "pilot" else 60
    records = []
    for i in range(count):
        folder = output / f"D{i:02d}"
        durable_directory(folder)
        row = {"index": i, "development_seed": None if kind == "pilot" else
               protocol["development_reset_seeds"][i], "source_head": head,
               "result": "RUNNING", "process_start_ticks": start_ticks}
        # This durable marker accounts for the reset even after SIGKILL or SSH loss.
        atomic_json(folder / "cycle-start.json", row)
        atomic_json(folder / "trace.json", row)
        try:
            row["down_before_exit"] = captured([config["sim_executable"], "down"],
                                                env, folder / "down-before.log")
            atomic_json(folder / "trace.json", row)
            if row["down_before_exit"]:
                raise RuntimeError("fresh down failed")
            row["up_exit"] = captured([config["sim_executable"], "up"], env, folder / "up.log")
            atomic_json(folder / "trace.json", row)
            if row["up_exit"]:
                raise RuntimeError("official up failed")
            row["policy_load_exit"] = captured(
                [config["sim_executable"], "ctl", "policy", "load", "walk",
                 config["walking_policy_path"]], env, folder / "policy-load.log")
            row["policy_readback_exit"] = captured(
                [config["sim_executable"], "ctl", "policy", "list", "--json"],
                env, folder / "policy-readback.json")
            atomic_json(folder / "trace.json", row)
            if row["policy_load_exit"] or row["policy_readback_exit"]:
                raise RuntimeError("policy load/readback failed")
            validate_loaded_walk_policy(
                json.loads((folder / "policy-readback.json").read_text()),
                Path(config["walking_policy_path"]), config["walking_policy_sha256"])
            reader = TimedPoseReader(PORT)
            try:
                row["preparation"] = prepare(reader, STATE / "duck-a.sock")
            finally:
                reader.close()
            row["result"] = row["preparation"]["gate"]["result"]
        except BaseException as error:
            if isinstance(error, PreparationFailure):
                row["preparation"] = error.trace
            row["error"] = f"{type(error).__name__}: {error}"
        finally:
            row["cleanup_stop"] = emergency_stop(STATE / "duck-a.sock")
            try:
                row["down_after_exit"] = captured([config["sim_executable"], "down"],
                                                  env, folder / "down-after.log")
            except BaseException as error:
                row["down_after_exit"] = None
                row["down_after_error"] = f"{type(error).__name__}: {error}"
            try:
                row["final_probe"] = probe_final_sim_state(
                    STATE, PORT, phase="r2_dev_reset_down")
            except BaseException as error:
                row["final_probe"] = {"result": "FAIL", "error":
                                      f"{type(error).__name__}: {error}"}
            if (row["cleanup_stop"]["result"] != "PASS" or row["down_after_exit"] != 0
                    or row["final_probe"]["result"] != "PASS"):
                row["result"] = "CLEANUP_FAIL"
            atomic_json(folder / "trace.json", row)
            records.append({"index": i, "result": row["result"]})
        if row["result"] != "PASS":
            break
    result = {"schema_version": "p8-03-r2-reset-development-v1", "kind": kind,
              "source_head": head, "planned": count, "observed": len(records),
              "result": "PASS" if len(records) == count and
              all(x["result"] == "PASS" for x in records) else "FAIL",
              "records": records, "not_final_evidence": True}
    files = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name not in ("manifest.json", "gate.json", "run.json"):
            data = path.read_bytes()
            files.append({"path": path.relative_to(output).as_posix(),
                          "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
                          "record_count": len(data.splitlines())})
    atomic_json(output / "manifest.json", {
        "schema_version": "p8-03-r2-development-manifest-v1",
        "source_head": head, "excluded_metadata": ["manifest.json", "gate.json", "run.json"],
        "files": files})
    result["raw_manifest_sha256"] = hashlib.sha256(
        (output / "manifest.json").read_bytes()).hexdigest()
    atomic_json(output / "gate.json", result)
    atomic_json(output / "run.json", {
        "schema_version": "p8-03-r2-development-run-v1", "status": result["result"],
        "source_head": head, "kind": kind, "pid": os.getpid(),
        "process_start_ticks": start_ticks,
        "completed_monotonic_ns": time.monotonic_ns(), "observed": len(records),
        "gate_sha256": hashlib.sha256((output / "gate.json").read_bytes()).hexdigest()})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reviewed-head", required=True)
    parser.add_argument("--kind", choices=("pilot", "qualification"), required=True)
    args = parser.parse_args()
    run(args.output, args.reviewed_head, args.kind)
