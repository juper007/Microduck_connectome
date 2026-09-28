"""Development-only Thor fresh-reset pose traces; never assigns final IDs.

This is exploratory diagnosis, not the R2 qualification or final gate.
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

from microduck_connectome.looming_scenario import validate_pose
from scripts.p6_telemetry_runtime_fixture import quaternion_yaw
from scripts.p8_02_final_batch import probe_final_sim_state
from scripts.p8_02_r1_batch import emergency_stop, fsync_directory
from scripts.p8_03_r1_durability import atomic_json, durable_directory
from scripts.p7_pretrial_acquisition import validate_loaded_walk_policy


class TimedPoseReader:
    """Read official body packets, retaining their simulator clock."""

    def __init__(self, port: int):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=2)
        self.sock.settimeout(2)
        self.stream = self.sock.makefile("rwb")
        self.stream.write(b'{"op":"hello","protocol":1,"joints":15}\n')
        self.stream.flush()
        if json.loads(self.stream.readline()) != {"protocol": 1}:
            raise RuntimeError("official body protocol mismatch")

    def read(self) -> dict:
        before = time.monotonic_ns()
        self.stream.write(b'{"op":"read"}\n')
        self.stream.flush()
        packet = json.loads(self.stream.readline())
        after = time.monotonic_ns()
        trunk = packet.get("trunk")
        quat = packet.get("imu", {}).get("quat")
        sim_time = packet.get("sim_time")
        if (not isinstance(trunk, list) or len(trunk) != 3 or
                not isinstance(quat, list) or len(quat) != 4 or
                not isinstance(sim_time, (int, float)) or
                not math.isfinite(sim_time)):
            raise RuntimeError("official pose or simulator clock unavailable")
        pose = validate_pose({"x_m": trunk[0], "y_m": trunk[1],
                              "heading_rad": quaternion_yaw(quat),
                              "trunk_z_m": trunk[2]})
        w, x, y, z = quat
        roll = math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y))
        pitch = math.asin(max(-1.0, min(1.0, 2 * (w * y - z * x))))
        return {"request_ns": before, "response_ns": after,
                "sim_time_s": float(sim_time), "pose": pose,
                "imu_quat_wxyz": quat, "roll_rad": roll, "pitch_rad": pitch}

    def close(self) -> None:
        self.stream.close()
        self.sock.close()


def sample(port: int, duration_s: float, period_s: float = .05) -> list[dict]:
    reader = TimedPoseReader(port)
    rows = []
    try:
        start = time.monotonic()
        count = round(duration_s / period_s) + 1
        for index in range(count):
            time.sleep(max(0, start + index * period_s - time.monotonic()))
            rows.append(reader.read())
    finally:
        reader.close()
    return rows


def captured(command: list[str], env: dict, path: Path, timeout: int = 120) -> int:
    result = subprocess.run(command, env=env, capture_output=True,
                            timeout=timeout, check=False)
    with path.open("xb") as out:
        out.write(result.stdout + result.stderr)
        out.flush()
        os.fsync(out.fileno())
    fsync_directory(path.parent)
    return result.returncode


def run(output: Path, head: str, cycles: int, preload_s: float,
        keyframe: str) -> None:
    actual = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                                     text=True).strip()
    dirty = subprocess.check_output(["git", "-C", str(ROOT), "status", "--porcelain"],
                                    text=True).strip()
    if (actual != head or dirty or not socket.gethostname().startswith("jetsonthor")
            or platform.python_version_tuple()[:2] != ("3", "12")):
        raise RuntimeError("clean exact-head Thor Python 3.12 source required")
    if cycles < 1 or cycles > 20 or preload_s not in (0.0, 1.0) or keyframe not in ("SIT", "HOME", "STAND"):
        raise ValueError("exploratory count or pre-load interval outside frozen choices")
    if keyframe != "SIT" and preload_s != 0.0:
        raise ValueError("alternate keyframe diagnosis uses R1 policy cadence")
    expected_name = ("p8-03-r2-diagnosis-stand-v1" if keyframe == "STAND" else
                     "p8-03-r2-diagnosis-home-v1" if keyframe == "HOME" else
                     "p8-03-r2-diagnosis-r1cadence-v1" if preload_s == 0.0 else
                     "p8-03-r2-diagnosis-deferred-policy-v1")
    expected_parent = Path("/home/juper007/projects/microduck-connectome-thor/evidence/p8-v2-final")
    if output != expected_parent / expected_name:
        raise ValueError("diagnosis output must use its dedicated development root")
    config = json.loads((ROOT / "config/p8_03_r1_execution_v1.json").read_text())
    for key, version in (("microduck_path", "microduck_commit"),
                         ("microduck_rl_path", "microduck_rl_commit")):
        if subprocess.check_output(["git", "-C", config[key], "rev-parse", "HEAD"],
                                   text=True).strip() != config[version]:
            raise RuntimeError(f"pinned upstream mismatch: {key}")
    for path_key, hash_key in (("graph_path", "graph_sha256"),
                               ("walking_policy_path", "walking_policy_sha256")):
        if hashlib.sha256(Path(config[path_key]).read_bytes()).hexdigest() != config[hash_key]:
            raise RuntimeError(f"pinned material mismatch: {path_key}")
    state = Path("/tmp/p8-03-r2-diagnosis-state")
    port = 7897
    preprobe = probe_final_sim_state(state, port, phase="r2_diagnosis_preflight")
    if preprobe["result"] != "PASS" or output.exists():
        raise RuntimeError("diagnosis state occupied or output root already used")
    durable_directory(output)
    atomic_json(output / "preflight.json", preprobe)
    env = dict(os.environ, DUCK_SIM_VIEWER="0", DUCK_SIM_STATE=str(state),
               DUCK_SIM_KEYFRAME=keyframe,
               DUCK_SIM_RL=config["microduck_rl_path"], DUCK_SIM_PORT=str(port),
               PYTHONPATH=str(ROOT))
    env["PATH"] = (str(Path(config["microduck_path"]).parent /
                       "rustup/toolchains/stable-aarch64-unknown-linux-gnu/bin") +
                   os.pathsep + env["PATH"])
    sim = config["sim_executable"]
    records = []
    for index in range(cycles):
        folder = output / f"D{index:02d}"
        durable_directory(folder)
        record = {"index": index, "source_head": head, "preload_s": preload_s,
                  "keyframe": keyframe,
                  "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        try:
            record["down_before_exit"] = captured([sim, "down"], env,
                                                   folder / "down-before.log")
            if record["down_before_exit"] != 0:
                raise RuntimeError("official simulator down failed before fresh reset")
            record["up_exit"] = captured([sim, "up"], env, folder / "up.log")
            if record["up_exit"] != 0:
                raise RuntimeError("official simulator up failed")
            record["up_completed_ns"] = time.monotonic_ns()
            if preload_s:
                record["before_policy"] = sample(port, preload_s)
            record["policy_load_exit"] = captured(
                [sim, "ctl", "policy", "load", "walk", config["walking_policy_path"]],
                env, folder / "policy-load.log")
            record["policy_readback_exit"] = captured(
                [sim, "ctl", "policy", "list", "--json"],
                env, folder / "policy-readback.json")
            if record["policy_load_exit"] or record["policy_readback_exit"]:
                raise RuntimeError("policy load/readback failed")
            validate_loaded_walk_policy(
                json.loads((folder / "policy-readback.json").read_text()),
                Path(config["walking_policy_path"]), config["walking_policy_sha256"])
            record["policy_readback_ns"] = time.monotonic_ns()
            record["after_policy"] = sample(port, 2.0)
            record["health_exit"] = captured([sim, "ctl", "health"], env,
                                              folder / "health.log", timeout=10)
            if record["health_exit"]:
                raise RuntimeError("robotd health failed")
            record["result"] = "OBSERVED"
        except BaseException as error:
            record["result"] = "ERROR"
            record["error"] = f"{type(error).__name__}: {error}"
        finally:
            try:
                record["stop"] = emergency_stop(state / "duck-a.sock")
            except BaseException as error:
                record["stop"] = {"result": "FAIL",
                                  "error": f"{type(error).__name__}: {error}"}
            try:
                record["down_after_exit"] = captured([sim, "down"], env,
                                                      folder / "down-after.log")
            except BaseException as error:
                record["down_after_exit"] = None
                record["down_after_error"] = f"{type(error).__name__}: {error}"
            try:
                record["final_probe"] = probe_final_sim_state(
                    state, port, phase="r2_diagnosis_down")
            except BaseException as error:
                record["final_probe"] = {"result": "FAIL",
                                         "error": f"{type(error).__name__}: {error}"}
            if (record["stop"]["result"] != "PASS" or record["down_after_exit"] != 0
                    or record["final_probe"]["result"] != "PASS"):
                record["result"] = "CLEANUP_FAIL"
            atomic_json(folder / "trace.json", record)
            records.append({"index": index, "result": record["result"],
                            "stop": record["stop"]["result"],
                            "down": record["down_after_exit"],
                            "probe": record["final_probe"]["result"]})
        if (record["result"] != "OBSERVED" or record["stop"]["result"] != "PASS"
                or record["down_after_exit"] != 0 or
                record["final_probe"]["result"] != "PASS"):
            break
    rows = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name != "diagnosis-manifest.json":
            payload = path.read_bytes()
            rows.append({"path": path.relative_to(output).as_posix(),
                         "sha256": hashlib.sha256(payload).hexdigest(),
                         "bytes": len(payload),
                         "record_count": len(payload.splitlines()) if payload else 0})
    atomic_json(output / "diagnosis-result.json", {"schema_version": "p8-03-r2-diagnosis-v1",
                                                  "source_head": head, "cycles": records,
                                                  "exploratory_only": True})
    # Include the result file after writing it.
    payload = (output / "diagnosis-result.json").read_bytes()
    rows.append({"path": "diagnosis-result.json",
                 "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload),
                 "record_count": len(payload.splitlines())})
    atomic_json(output / "diagnosis-manifest.json", {
        "schema_version": "p8-03-r2-diagnosis-manifest-v1",
        "source_head": head, "files": sorted(rows, key=lambda row: row["path"])})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reviewed-head", required=True)
    parser.add_argument("--cycles", type=int, required=True)
    parser.add_argument("--preload-s", type=float, choices=(0.0, 1.0), required=True)
    parser.add_argument("--keyframe", choices=("SIT", "HOME", "STAND"), default="SIT")
    args = parser.parse_args()
    run(args.output, args.reviewed_head, args.cycles, args.preload_s, args.keyframe)


if __name__ == "__main__":
    main()
