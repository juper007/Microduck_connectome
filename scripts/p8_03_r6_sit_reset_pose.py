"""Passive, one-attempt official SIT reset pose diagnostic for P8-03-R6.

The only robot command sent here is the discrete, acknowledged robot.stop.
Development reset IDs are labels; duck-sim has no RNG seed input.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time

from microduck_connectome.robotd_client import RobotdClient
from scripts.p7_pretrial_acquisition import validate_loaded_walk_policy
from scripts.p8_02_final_batch import probe_final_sim_state
from scripts.p8_03_r6_score import checkpoint_metrics, expected_matrix, score_root, stage_views

PINS = {"MicroDuck": "344925c9f8fa031f85428a305b1e8ec2eaae29c1",
        "microduck_rl": "cb70b792312d559a4da09064d92009079671815f",
        "python": "3.12.3",
        "walk_policy_sha256": "98c3ea73fa6bb196bcf16586cf38b9fffb782787447d638fa1c1028df9082c1a",
        "graph_sha256": "c4160c42941163079b6b569d117bf67afcf8b45eaa128c444f7c96c2567593cc"}


def quaternion_yaw(wxyz) -> float:
    w, x, y, z = wxyz
    return math.atan2(2 * (w*z + x*y), 1 - 2 * (y*y + z*z))


class StateStream:
    """Read-only official robot.state subscription; no command dispatch API."""

    def __init__(self, path: str):
        self.latest = None
        self.received_ns = None
        self.error = None
        self.stop_event = threading.Event()
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(2.0)
        self.sock.connect(path)
        self.stream = self.sock.makefile("rwb")
        self.stream.write(b'{"jsonrpc":"2.0","id":1,"method":"robot.subscribe","params":{"hz":50}}\n')
        self.stream.flush()
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def _read(self):
        try:
            while not self.stop_event.is_set():
                raw = self.stream.readline()
                if not raw:
                    raise RuntimeError("robot.state stream closed")
                message = json.loads(raw)
                if message.get("method") == "robot.state":
                    self.latest = message["params"]
                    self.received_ns = time.monotonic_ns()
        except BaseException as error:
            if not self.stop_event.is_set():
                self.error = repr(error)

    def state(self):
        deadline = time.monotonic() + 2
        while self.latest is None and self.error is None and time.monotonic() < deadline:
            time.sleep(.01)
        if self.error or self.latest is None:
            raise RuntimeError(self.error or "robot.state not received")
        return self.latest

    def close(self):
        self.stop_event.set()
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.stream.close()
        self.sock.close()
        self.thread.join(timeout=.5)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)


class Journal:
    def __init__(self, path: Path):
        self.file = path.open("x", encoding="utf-8")
        self.index = 0

    def add(self, kind: str, **fields) -> dict:
        row = {"sample_index": self.index, "kind": kind,
               "host_monotonic_ns": time.monotonic_ns(),
               "host_utc_ns": time.time_ns(), **fields}
        self.file.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
        self.file.flush()
        os.fsync(self.file.fileno())
        self.index += 1
        return row

    def close(self) -> None:
        self.file.close()


class TimedPoseReader:
    def __init__(self, port: int):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=.2)
        self.sock.settimeout(.2)
        self.stream = self.sock.makefile("rwb")
        self.stream.write(b'{"op":"hello","protocol":1,"joints":15}\n')
        self.stream.flush()
        if json.loads(self.stream.readline()) != {"protocol": 1}:
            raise RuntimeError("official body hello mismatch")

    def read(self) -> dict:
        request_ns = time.monotonic_ns()
        self.stream.write(b'{"op":"read"}\n')
        self.stream.flush()
        raw = self.stream.readline()
        response_ns = time.monotonic_ns()
        packet = json.loads(raw)
        trunk, imu = packet.get("trunk"), packet.get("imu")
        quat = imu.get("quat") if isinstance(imu, dict) else None
        sim_time = packet.get("sim_time")
        valid = (isinstance(trunk, list) and len(trunk) == 3 and
                 isinstance(quat, list) and len(quat) == 4 and
                 all(type(v) in (int, float) and math.isfinite(v)
                     for v in trunk + quat + [sim_time]))
        if valid:
            w, x, y, z = quat
            roll = math.atan2(2 * (w*x + y*z), 1 - 2 * (x*x + y*y))
            pitch = math.asin(max(-1., min(1., 2 * (w*y - z*x))))
            heading = quaternion_yaw(quat)
        else:
            roll = pitch = heading = None
        return {"request_ns": request_ns, "response_ns": response_ns,
                "raw_body_packet": raw.decode("utf-8", errors="replace").rstrip("\n"),
                "sim_time_s": float(sim_time) if valid else None,
                "x_m": trunk[0] if valid else None,
                "y_m": trunk[1] if valid else None,
                "trunk_z_m": trunk[2] if valid else None,
                "heading_rad": heading, "roll_rad": roll, "pitch_rad": pitch,
                "imu_quat_wxyz": quat if valid else None}

    def close(self) -> None:
        self.stream.close()
        self.sock.close()


def bounded_stop(sock: Path) -> dict:
    result = {"result": "FAIL", "started_ns": time.monotonic_ns()}
    client = RobotdClient(str(sock), timeout_s=.1)
    try:
        client.connect()
        result["ack"] = client.stop()
        result["result"] = "PASS"
    except BaseException as error:
        result["error"] = f"{type(error).__name__}: {error}"
    finally:
        client.disconnect()
        result["completed_ns"] = time.monotonic_ns()
        result["latency_s"] = (result["completed_ns"] - result["started_ns"]) / 1e9
        if result["latency_s"] > .2:
            result["result"] = "FAIL"
    return result


def captured(command: list[str], env: dict, path: Path, timeout=120) -> int:
    with path.open("x", encoding="utf-8") as output:
        result = subprocess.run(command, env=env, stdout=output,
                                stderr=subprocess.STDOUT, timeout=timeout)
        output.flush()
        os.fsync(output.fileno())
    return result.returncode


def check_sample(row: dict, previous: dict | None, protocol: dict) -> tuple[str, str] | None:
    pose = row["pose"]
    keys = ("request_ns", "response_ns", "sim_time_s", "x_m", "y_m",
            "trunk_z_m", "heading_rad", "roll_rad", "pitch_rad")
    if any(type(pose.get(k)) not in (int, float) or not math.isfinite(pose[k])
           for k in keys):
        return "DATA_INTEGRITY_FAIL", "malformed_pose"
    if not isinstance(pose.get("imu_quat_wxyz"), list) or len(pose["imu_quat_wxyz"]) != 4:
        return "DATA_INTEGRITY_FAIL", "malformed_quaternion"
    age = (pose["response_ns"] - pose["request_ns"]) / 1e9
    if not 0 <= age <= protocol["max_pose_response_age_s"]:
        return "DATA_INTEGRITY_FAIL", "stale_pose_response"
    if previous and pose["sim_time_s"] <= previous["sim_time_s"]:
        return "DATA_INTEGRITY_FAIL", "simulator_clock_not_advancing"
    if max(abs(pose["roll_rad"]), abs(pose["pitch_rad"])) > protocol["genuine_safety"]["max_abs_roll_pitch_rad"]:
        return "SAFETY_FAIL", "body_attitude_exceeded"
    state = row.get("robotd_state")
    if row["checkpoint"] != "B_BODY_REACHABLE":
        if not isinstance(state, dict) or not isinstance(row.get("health"), dict):
            return "DATA_INTEGRITY_FAIL", "missing_robotd_state_or_health"
        if state.get("safety", {}).get("fallen") or state.get("safety", {}).get("limp"):
            return "SAFETY_FAIL", "robotd_safety_fault"
        if row["health"].get("healthy") is not True or row["health"].get("degraded"):
            return "SAFETY_FAIL", "robotd_unhealthy"
        if (pose["response_ns"] - row["state_received_ns"]) / 1e9 > protocol["max_state_age_s"]:
            return "DATA_INTEGRITY_FAIL", "stale_robotd_state"
        applied = state.get("move", {}).get("applied", {})
        for key, bound in (("vx", "max_abs_vx_mps"), ("vy", "max_abs_vy_mps"),
                           ("vyaw", "max_abs_vyaw_radps")):
            value = applied.get(key)
            if type(value) in (int, float) and abs(value) > protocol["genuine_safety"][bound]:
                return "SAFETY_FAIL", "unexpected_applied_motion"
    return None


def capture(reader: TimedPoseReader, stream: StateStream | None,
            client: RobotdClient | None, journal: Journal, checkpoint: str,
            index: int, previous: dict | None, protocol: dict) -> tuple[dict, tuple[str, str] | None]:
    if previous:
        delay = .025 - (time.monotonic_ns() - previous["response_ns"]) / 1e9
        if delay > 0:
            time.sleep(delay)
    # Keep fallen/limp state in raw evidence before the safety gate acts.
    if stream and (stream.error or stream.latest is None):
        raise RuntimeError(stream.error or "robotd state not received")
    state = stream.latest if stream else None
    received_ns = stream.received_ns if stream else None
    health = client.health() if client else None
    pose = reader.read()
    row = journal.add("pose", checkpoint=checkpoint, checkpoint_index=index,
                      pose=pose, robotd_state=state,
                      robotd_t_ns=state.get("t_ns") if state else None,
                      state_received_ns=received_ns, health=health,
                      requested=state.get("move", {}).get("requested") if state else None,
                      applied=state.get("move", {}).get("applied") if state else None,
                      limited_by=state.get("move", {}).get("limited_by") if state else None,
                      policy=state.get("policy") if state else None)
    return pose, check_sample(row, previous, protocol)


def wait_body(port: int, deadline: float) -> TimedPoseReader:
    while time.monotonic() < deadline:
        try:
            return TimedPoseReader(port)
        except (OSError, TimeoutError, ValueError, json.JSONDecodeError):
            time.sleep(.02)
    raise TimeoutError("body server not reachable during official up")


def wait_robotd(sock: Path, deadline: float) -> tuple[RobotdClient, StateStream]:
    while time.monotonic() < deadline:
        client = RobotdClient(str(sock), timeout_s=.2)
        try:
            client.connect()
            stream = StateStream(str(sock))
            stream.state()
            return client, stream
        except (OSError, RuntimeError):
            client.disconnect()
            time.sleep(.02)
    raise TimeoutError("robotd not reachable during official up")


def run_one(expected: dict, root: Path, protocol: dict, sim: Path,
            state_dir: Path, policy: Path, env: dict, port: int) -> dict:
    folder = root / expected["id"]
    folder.mkdir()
    journal = Journal(folder / "samples.jsonl")
    row = {**expected, "result": "RUNNING", "move_count": 0,
           "started_utc_ns": time.time_ns(), "single_attempt": True}
    atomic_json(folder / "trace.json", row)
    reader = client = stream = None
    up = None
    previous = None
    sock = state_dir / "duck-a.sock"
    try:
        journal.add("reset_start", development_reset_id=expected["development_reset_id"])
        row["down_before_exit"] = captured([str(sim), "down"], env, folder / "down-before.log")
        if row["down_before_exit"]:
            raise RuntimeError("official down failed")
        with (folder / "up.log").open("x", encoding="utf-8") as output:
            up = subprocess.Popen([str(sim), "up"], env=env, stdout=output,
                                  stderr=subprocess.STDOUT)
            journal.add("official_up_started", pid=up.pid)
            deadline = time.monotonic() + 120
            reader = wait_body(port, deadline)
            previous, failure = capture(reader, None, None, journal,
                                        "B_BODY_REACHABLE", 0, previous, protocol)
            if failure:
                row["result"], reason = failure
                raise RuntimeError(reason)
            client, stream = wait_robotd(sock, deadline)
            previous, failure = capture(reader, stream, client, journal,
                                        "C_ROBOTD_REACHABLE", 0, previous, protocol)
            if failure:
                row["result"], reason = failure
                raise RuntimeError(reason)
            row["up_exit"] = up.wait(timeout=max(1, deadline - time.monotonic()))
            row["up_completed_ns"] = time.monotonic_ns()
            output.flush()
            os.fsync(output.fileno())
        journal.add("up_complete", exit=row["up_exit"], completed_ns=row["up_completed_ns"])
        if row["up_exit"]:
            raise RuntimeError("official up failed")
        previous, failure = capture(reader, stream, client, journal,
                                    "A_UP_COMPLETE", 0, previous, protocol)
        if failure:
            row["result"], reason = failure
            raise RuntimeError(reason)
        row["policy_load_exit"] = captured(
            [str(sim), "ctl", "policy", "load", "walk", str(policy)],
            env, folder / "policy-load.log")
        row["policy_readback_exit"] = captured(
            [str(sim), "ctl", "policy", "list", "--json"],
            env, folder / "policy-readback.json")
        if row["policy_load_exit"] or row["policy_readback_exit"]:
            raise RuntimeError("policy load/readback failed")
        row["policy_verified"] = validate_loaded_walk_policy(
            json.loads((folder / "policy-readback.json").read_text()),
            policy, PINS["walk_policy_sha256"])
        journal.add("policy_verified", value=row["policy_verified"])
        previous, failure = capture(reader, stream, client, journal,
                                    "D_POLICY_LOADED", 0, previous, protocol)
        if failure:
            row["result"], reason = failure
            raise RuntimeError(reason)
        row["initial_stop"] = bounded_stop(sock)
        journal.add("stop_ack", **row["initial_stop"])
        if row["initial_stop"]["result"] != "PASS":
            raise RuntimeError("initial stop ACK failed")
        previous, failure = capture(reader, stream, client, journal,
                                    "E_STOP_ACK", 0, previous, protocol)
        if failure:
            row["result"], reason = failure
            raise RuntimeError(reason)
        time.sleep(protocol["short_settle_s"])
        previous, failure = capture(reader, stream, client, journal,
                                    "F_SHORT_SETTLE", 0, previous, protocol)
        if failure:
            row["result"], reason = failure
            raise RuntimeError(reason)
        for i in range(protocol["plateau_samples"]):
            if i:
                time.sleep(protocol["plateau_sample_s"])
            previous, failure = capture(reader, stream, client, journal,
                                        "G_FINAL_PLATEAU", i, previous, protocol)
            if failure:
                row["result"], reason = failure
                raise RuntimeError(reason)
        journal.file.flush()
        rows = [json.loads(line) for line in (folder / "samples.jsonl").read_text().splitlines()]
        row["checkpoint_metrics"] = checkpoint_metrics(stage_views(rows, protocol), protocol)
        row["result"] = "OBSERVED"
    except BaseException as error:
        row["error"] = f"{type(error).__name__}: {error}"
        if row["result"] == "RUNNING":
            row["result"] = "INFRA_FAIL"
        if row["result"] == "SAFETY_FAIL":
            pose_rows = [json.loads(line) for line in (folder / "samples.jsonl").read_text().splitlines()
                         if '"kind": "pose"' in line]
            trigger = {"reason": str(error), "pose_sample_index": pose_rows[-1]["sample_index"]}
            row["trigger"] = trigger
            journal.add("safety_event", trigger=trigger)
            journal.add("safety_stop_ack", **bounded_stop(sock))
    finally:
        for resource in (stream, reader, client):
            if resource is not None:
                try:
                    resource.close() if hasattr(resource, "close") else resource.disconnect()
                except BaseException as error:
                    row.setdefault("close_errors", []).append(repr(error))
        if up is not None and up.poll() is None:
            up.terminate()
            try:
                up.wait(timeout=5)
            except subprocess.TimeoutExpired:
                up.kill()
                up.wait(timeout=5)
        row["cleanup_stop"] = bounded_stop(sock)
        try:
            row["down_after_exit"] = captured([str(sim), "down"], env, folder / "down-after.log")
        except BaseException as error:
            row["down_after_exit"] = None
            row["down_after_error"] = repr(error)
        row["final_probe"] = probe_final_sim_state(state_dir, port)
        if (row["cleanup_stop"]["result"] != "PASS" or
                row["down_after_exit"] != 0 or row["final_probe"]["result"] != "PASS" or
                row.get("close_errors")):
            row["result"] = "INFRA_FAIL" if row["result"] != "SAFETY_FAIL" else row["result"]
        row["completed_utc_ns"] = time.time_ns()
        journal.add("cleanup", cleanup_stop=row["cleanup_stop"],
                    down_after_exit=row["down_after_exit"], final_probe=row["final_probe"])
        journal.close()
        atomic_json(folder / "trace.json", row)
    return row


def build_manifest(root: Path) -> dict:
    files = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name not in ("manifest.json", "gate.json", "run.json"):
            raw = path.read_bytes()
            files.append({"path": path.relative_to(root).as_posix(),
                          "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                          "record_count": len(raw.splitlines())})
    return {"schema_version": "p8-03-r6-manifest-v1", "files": files}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--microduck", type=Path, required=True)
    parser.add_argument("--microduck-rl", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--sim-state", type=Path, required=True)
    parser.add_argument("--body-port", type=int, default=7900)
    parser.add_argument("--reviewed-head", required=True)
    args = parser.parse_args()
    source_root = Path(__file__).resolve().parents[1]
    if (subprocess.check_output(["git", "-C", str(source_root), "rev-parse", "HEAD"],
                                text=True).strip() != args.reviewed_head or
            subprocess.check_output(["git", "-C", str(source_root), "status", "--porcelain"],
                                    text=True).strip()):
        raise RuntimeError("R6 source checkout is not clean at reviewed exact head")
    protocol = json.loads(args.protocol.read_text())
    matrix = expected_matrix(protocol)
    if args.evidence_root.exists():
        raise RuntimeError("evidence root already exists; one attempt only")
    if (subprocess.check_output(["git", "-C", str(args.microduck), "rev-parse", "HEAD"],
                                text=True).strip() != PINS["MicroDuck"] or
            subprocess.check_output(["git", "-C", str(args.microduck_rl), "rev-parse", "HEAD"],
                                    text=True).strip() != PINS["microduck_rl"] or
            sha(args.policy) != PINS["walk_policy_sha256"] or
            sha(args.graph) != PINS["graph_sha256"] or
            not sys.version.startswith(PINS["python"])):
        raise RuntimeError("frozen material pin mismatch")
    if probe_final_sim_state(args.sim_state, args.body_port, phase="preflight")["result"] != "PASS":
        raise RuntimeError("official simulator not fully down at preflight")
    args.evidence_root.mkdir(parents=True)
    for name, source in (("protocol.json", args.protocol),
                         ("runner.py", Path(__file__)),
                         ("scorer.py", Path(__file__).with_name("p8_03_r6_score.py"))):
        shutil.copyfile(source, args.evidence_root / name)
    env = os.environ.copy()
    env.update(DUCK_SIM_VIEWER="0", DUCK_SIM_STATE=str(args.sim_state),
               DUCK_SIM_KEYFRAME="SIT", DUCK_SIM_RL=str(args.microduck_rl),
               DUCK_SIM_PORT=str(args.body_port),
               PYTHONPATH=str(source_root))
    env["PATH"] = (str(args.microduck.parent /
                       "rustup/toolchains/stable-aarch64-unknown-linux-gnu/bin") +
                   os.pathsep + env["PATH"])
    sim = args.microduck / "scripts/duck-sim"
    records = []
    for expected in matrix:
        row = run_one(expected, args.evidence_root, protocol, sim,
                      args.sim_state, args.policy, env, args.body_port)
        records.append(row)
        atomic_json(args.evidence_root / "run.json", {"attempted": len(records),
                    "last_result": row["result"], "planned": len(matrix)})
        if row["result"] != "OBSERVED":
            break
    atomic_json(args.evidence_root / "manifest.json", build_manifest(args.evidence_root))
    gate = score_root(args.evidence_root, args.evidence_root / "protocol.json")
    atomic_json(args.evidence_root / "gate.json", gate)
    print(json.dumps({"result": gate["result"], "attempted": gate["attempted"],
                      "valid_resets": gate["valid_resets"]}))
    return 0 if gate["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
