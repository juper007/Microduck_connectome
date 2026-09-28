"""Frozen, development-only Thor yaw-sign diagnostic; never arms P8 trials."""
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
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from microduck_connectome.robotd_client import RobotdClient
from scripts.p6_motion_fixture import JsonLines, StateStream, quaternion_yaw, wrapped_delta
from scripts.p8_02_final_batch import probe_final_sim_state
from scripts.p8_02_r1_trial import acknowledged_precondition_move
from scripts.p7_pretrial_acquisition import validate_loaded_walk_policy

PARENT = Path("/home/juper007/projects/microduck-connectome-thor/evidence/p8-v2-final")
OUTPUT = PARENT / "p8-03-r3-yaw-diagnostic-v1"
STATE = Path("/tmp/p8-03-r3-yaw-state")
PORT = 7899
REFERENCE = {"x_m": .03457887954384973, "y_m": .0010909211238251523,
             "heading_rad": .11693358424258107, "trunk_z_m": .11587609862790209}
R1_CONFIG = {
    "microduck_path": "/home/juper007/projects/microduck-connectome-thor/microduck",
    "microduck_commit": "344925c9f8fa031f85428a305b1e8ec2eaae29c1",
    "microduck_rl_path": "/home/juper007/projects/microduck-connectome-thor/microduck_rl",
    "microduck_rl_commit": "cb70b792312d559a4da09064d92009079671815f",
    "walking_policy_path": "/home/juper007/projects/microduck-connectome-thor/evidence/p7-02/policy-development-6012390-20260924/checkpoint1250-diagnostic/model1250.onnx",
    "walking_policy_sha256": "98c3ea73fa6bb196bcf16586cf38b9fffb782787447d638fa1c1028df9082c1a",
    "graph_path": "/home/juper007/projects/microduck-connectome-thor/evidence/g8-r1/graph-v2/c4160c42941163079b6b569d117bf67afcf8b45eaa128c444f7c96c2567593cc.json",
    "graph_sha256": "c4160c42941163079b6b569d117bf67afcf8b45eaa128c444f7c96c2567593cc",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bounded_stop(sock: Path) -> dict:
    result = {"result": "FAIL", "started_ns": time.monotonic_ns()}
    client = RobotdClient(str(sock), timeout_s=.2)
    try:
        client.connect()
        result["ack"] = client.stop()
        result["result"] = "PASS"
    except BaseException as error:
        result["error"] = f"{type(error).__name__}: {error}"
    finally:
        try:
            client.close()
        except BaseException as error:
            result["close_error"] = repr(error)
            result["result"] = "FAIL"
        result["completed_ns"] = time.monotonic_ns()
    return result


def atomic_json(path: Path, data: dict) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def matrix(protocol: dict) -> list[dict]:
    assert protocol["trial_count"] == 50
    pattern = protocol["block_order"]
    assert pattern == ["positive", "negative", "sham", "negative", "positive"]
    assert protocol["block_count"] == 10 and protocol["alternate_block_reversal"]
    rows = []
    for block in range(10):
        conditions = pattern if block % 2 == 0 else [
            {"positive": "negative", "negative": "positive", "sham": "sham"}[x]
            for x in pattern]
        for condition in conditions:
            index = len(rows)
            rows.append({"id": f"D{index:02d}", "seed": 887700 + index,
                         "block": block, "condition": condition})
    assert len(rows) == 50 and rows[-1]["seed"] == protocol["seed_last"]
    return rows


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
        packet = json.loads(self.stream.readline())
        response_ns = time.monotonic_ns()
        trunk, quat, sim_time = packet.get("trunk"), packet.get("imu", {}).get("quat"), packet.get("sim_time")
        if (not isinstance(trunk, list) or len(trunk) != 3 or
                not isinstance(quat, list) or len(quat) != 4 or
                not isinstance(sim_time, (float, int)) or
                any(not isinstance(v, (float, int)) or not math.isfinite(v)
                    for v in trunk + quat + [sim_time])):
            raise RuntimeError("nonfinite or missing official body pose")
        w, x, y, z = quat
        roll = math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y))
        pitch = math.asin(max(-1., min(1., 2 * (w * y - z * x))))
        return {"request_ns": request_ns, "response_ns": response_ns,
                "sim_time_s": float(sim_time), "x_m": trunk[0], "y_m": trunk[1],
                "trunk_z_m": trunk[2], "heading_rad": quaternion_yaw(quat),
                "roll_rad": roll, "pitch_rad": pitch, "imu_quat_wxyz": quat}

    def close(self):
        self.stream.close()
        self.sock.close()


def validate_pose(row: dict, previous: dict | None, first: dict | None, *, moving: bool) -> None:
    age = (row["response_ns"] - row["request_ns"]) / 1e9
    if age > .1 or age < 0:
        raise RuntimeError("pose response stale")
    if previous is not None:
        interval = (row["response_ns"] - previous["response_ns"]) / 1e9
        if not 0 < row["sim_time_s"] - previous["sim_time_s"] or not .01 <= interval <= .25:
            raise RuntimeError("pose or simulator clock did not advance")
    if abs(row["roll_rad"]) > .5 or abs(row["pitch_rad"]) > .5:
        raise RuntimeError("body attitude safety bound exceeded")
    if first is None:
        if (abs(row["x_m"] - REFERENCE["x_m"]) > .03 or
                abs(row["y_m"] - REFERENCE["y_m"]) > .03 or
                abs(row["trunk_z_m"] - REFERENCE["trunk_z_m"]) > .025 or
                abs(wrapped_delta(row["heading_rad"], REFERENCE["heading_rad"])) > .35):
            raise RuntimeError("fresh reset outside diagnostic inclusion envelope")
    elif moving and math.hypot(row["x_m"] - first["x_m"], row["y_m"] - first["y_m"]) > .01:
        raise RuntimeError("command-induced translation bound exceeded")


def sampled(reader: TimedPoseReader, stream: StateStream, previous: dict | None,
            first: dict | None, *, moving: bool, require_walk: bool = False) -> dict:
    deadline = time.monotonic() + .05
    while True:
        pose = reader.read()
        if (previous is None or
                (pose["sim_time_s"] > previous["sim_time_s"] and
                 pose["response_ns"] - previous["response_ns"] >= 10_000_000)):
            break
        if time.monotonic() >= deadline:
            raise RuntimeError("bounded fresh-pose wait expired")
        time.sleep(.002)
    validate_pose(pose, previous, first, moving=moving)
    state = stream.state()
    if state["safety"]["fallen"] or state["safety"]["limp"]:
        raise RuntimeError("robotd safety fault")
    if state["policy"] not in ("stand", "walk"):
        raise RuntimeError("unexpected robotd policy state")
    if require_walk and state["policy"] != "walk":
        raise RuntimeError("walk policy not active during yaw pulse")
    return {"pose": pose, "robot_t_ns": state["t_ns"],
            "requested": state["move"]["requested"],
            "applied": state["move"]["applied"],
            "limited_by": state["move"].get("limited_by", []),
            "policy": state["policy"], "safety": state["safety"]}


def plateau(reader, stream, previous, first, label: str) -> list[dict]:
    rows = []
    start = time.monotonic() + (.05 if previous is not None else 0.)
    for i in range(21):
        time.sleep(max(0, start + i * .05 - time.monotonic()))
        row = sampled(reader, stream, previous, first, moving=first is not None)
        row["label"] = f"{label}:{i}"
        if previous is not None and row["robot_t_ns"] <= previous["robot_t_ns"]:
            raise RuntimeError("robotd clock did not advance")
        rows.append(row)
        previous = row["pose"] | {"robot_t_ns": row["robot_t_ns"]}
    headings = [r["pose"]["heading_rad"] for r in rows]
    if abs(wrapped_delta(headings[-1], headings[0])) > .005:
        raise RuntimeError("plateau heading drift exceeded")
    for row in rows:
        if any(abs(v) > .005 for v in row["applied"]):
            raise RuntimeError("stopped applied velocity exceeded")
    return rows


def heading_median(rows: list[dict]) -> float:
    anchor = rows[0]["pose"]["heading_rad"]
    return anchor + statistics.median(
        wrapped_delta(r["pose"]["heading_rad"], anchor) for r in rows[-5:])


def pulse(reader, stream, command, first, previous, condition: str, number: int,
          trace: dict) -> None:
    vyaw = .2 if condition == "positive" else -.2 if condition == "negative" else 0.
    trace.update({"number": number, "vyaw_radps": vyaw, "duration_s": .2,
                  "requests": [], "trajectory": []})
    started = time.monotonic()
    trace["started_ns"] = time.monotonic_ns()
    last_ack_ns = None
    try:
        for tick in range(10):
            due = started + tick * .02
            time.sleep(max(0, due - time.monotonic()))
            if time.monotonic() - due > .01:
                raise RuntimeError("50 Hz command refresh deadline exceeded")
            ack, call_ns, write_ns, ack_ns = acknowledged_precondition_move(
                command, vx=0., vy=0., vyaw=vyaw)
            if (ack_ns - call_ns > 100_000_000 or
                    last_ack_ns is not None and ack_ns - last_ack_ns > 100_000_000):
                raise RuntimeError("command ACK or TTL exceeded")
            trace["requests"].append({"tick": tick, "ack": ack, "call_ns": call_ns,
                                      "write_ns": write_ns, "ack_ns": ack_ns})
            last_ack_ns = ack_ns
            time.sleep(max(0, due + .015 - time.monotonic()))
            row = sampled(reader, stream, previous, first, moving=True,
                          require_walk=tick >= 2 and vyaw != 0.)
            row["tick"] = tick
            trace["trajectory"].append(row)
            previous = row["pose"] | {"robot_t_ns": row["robot_t_ns"]}
        time.sleep(max(0, started + .2 - time.monotonic()))
    finally:
        trace["stop"] = bounded_stop(STATE / "duck-a.sock")
        trace["stop_completed_ns"] = time.monotonic_ns()
        trace["active_through_stop_s"] = time.monotonic() - started
    if trace["stop"]["result"] != "PASS":
        raise RuntimeError("stop ACK missing")
    if not .2 <= trace["active_through_stop_s"] <= .3:
        raise RuntimeError("pulse including stop exceeded bounded duration")
    trace["post_stop_trajectory"] = []
    settle_start = time.monotonic()
    for i in range(21):
        time.sleep(max(0, settle_start + (i + 1) * .05 - time.monotonic()))
        row = sampled(reader, stream, previous, first, moving=True)
        row["tick"] = i
        trace["post_stop_trajectory"].append(row)
        previous = row["pose"] | {"robot_t_ns": row["robot_t_ns"]}
        if i >= 9 and any(abs(v) > .005 for v in row["applied"]):
            raise RuntimeError("motion persisted more than 0.5s after stop")
    trace["plateau"] = plateau(reader, stream, previous, first, f"post_stop_{number}")


def captured(command: list[str], env: dict, path: Path, timeout: int = 120) -> int:
    result = subprocess.run(command, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=timeout, check=False)
    with path.open("xb") as stream:
        stream.write(result.stdout)
        stream.flush()
        os.fsync(stream.fileno())
    return result.returncode


def verify_material() -> None:
    for key, commit in (("microduck_path", "microduck_commit"),
                        ("microduck_rl_path", "microduck_rl_commit")):
        if subprocess.check_output(["git", "-C", R1_CONFIG[key], "rev-parse", "HEAD"],
                                   text=True).strip() != R1_CONFIG[commit]:
            raise RuntimeError(f"pinned upstream mismatch: {key}")
    for key, digest in (("walking_policy_path", "walking_policy_sha256"),
                        ("graph_path", "graph_sha256")):
        if sha(Path(R1_CONFIG[key])) != R1_CONFIG[digest]:
            raise RuntimeError(f"pinned material mismatch: {key}")


def process_start_ticks() -> int:
    fields = Path("/proc/self/stat").read_text().split()
    return int(fields[21])


def interrupted(signum, _frame):
    raise RuntimeError(f"diagnostic process interrupted by signal {signum}")


def trace_integrity(row: dict, expected: dict) -> bool:
    """Validate raw evidence before using any saved delta or result label."""
    try:
        if any(row[k] != expected[k] for k in ("id", "seed", "block", "condition")):
            return False
        if row["result"] != "VALID" or row["initial_stop"]["result"] != "PASS":
            return False
        if (row["cleanup_stop"]["result"] != "PASS" or
                row["down_before_exit"] != 0 or row["up_exit"] != 0 or
                row["down_after_exit"] != 0 or
                row["final_probe"]["result"] != "PASS" or
                row["health"].get("healthy") is not True or
                row["health"].get("degraded") is True or
                row["policy_verified"]["loaded_walk_sha256"] !=
                R1_CONFIG["walking_policy_sha256"]):
            return False
        if len(row["initial_plateau"]) != 21 or len(row["pulses"]) != 2:
            return False
        expected_yaw = {"positive": .2, "negative": -.2, "sham": 0.}[row["condition"]]
        first = row["initial_plateau"][0]["pose"]
        if (abs(first["x_m"] - REFERENCE["x_m"]) > .03 or
                abs(first["y_m"] - REFERENCE["y_m"]) > .03 or
                abs(first["trunk_z_m"] - REFERENCE["trunk_z_m"]) > .025 or
                abs(wrapped_delta(first["heading_rad"], REFERENCE["heading_rad"])) > .35):
            return False
        phases = [row["initial_plateau"]]
        for pulse_row in row["pulses"]:
            if (pulse_row["vyaw_radps"] != expected_yaw or
                    pulse_row["duration_s"] != .2 or
                    not .2 <= pulse_row["active_through_stop_s"] <= .3 or
                    pulse_row["stop"]["result"] != "PASS" or
                    len(pulse_row["requests"]) != 10 or
                    len(pulse_row["trajectory"]) != 10 or
                    len(pulse_row["post_stop_trajectory"]) != 21 or
                    len(pulse_row["plateau"]) != 21):
                return False
            if any(request["ack"].get("accepted") is not True or
                   request["ack_ns"] - request["call_ns"] > 100_000_000 or
                   request["ack_ns"] < request["write_ns"]
                   for request in pulse_row["requests"]):
                return False
            if any(b["ack_ns"] - a["ack_ns"] > 100_000_000
                   for a, b in zip(pulse_row["requests"],
                                   pulse_row["requests"][1:])):
                return False
            if any(not 10_000_000 <= b["call_ns"] - a["call_ns"] <= 30_000_000
                   for a, b in zip(pulse_row["requests"],
                                   pulse_row["requests"][1:])):
                return False
            if expected_yaw != 0. and any(
                    sample["policy"] != "walk"
                    for sample in pulse_row["trajectory"][2:]):
                return False
            if any(any(abs(v) > .005 for v in sample["applied"])
                   for sample in pulse_row["post_stop_trajectory"][9:]):
                return False
            phases.extend((pulse_row["trajectory"],
                           pulse_row["post_stop_trajectory"],
                           pulse_row["plateau"]))
        for phase in phases:
            if any(b["pose"]["sim_time_s"] <= a["pose"]["sim_time_s"]
                   for a, b in zip(phase, phase[1:])):
                return False
            if any(b["robot_t_ns"] < a["robot_t_ns"]
                   for a, b in zip(phase, phase[1:])):
                return False
            for sample in phase:
                pose = sample["pose"]
                if ((pose["response_ns"] - pose["request_ns"]) > 100_000_000 or
                        pose["response_ns"] < pose["request_ns"] or
                        not all(math.isfinite(v) for v in
                                sample["requested"] + sample["applied"]) or
                        sample["policy"] not in ("stand", "walk") or
                        sample["safety"]["fallen"] or sample["safety"]["limp"] or
                        abs(pose["roll_rad"]) > .5 or
                        abs(pose["pitch_rad"]) > .5 or
                        math.hypot(pose["x_m"] - first["x_m"],
                                   pose["y_m"] - first["y_m"]) > .01 or
                        not all(math.isfinite(pose[key]) for key in
                                ("heading_rad", "x_m", "y_m", "trunk_z_m",
                                 "roll_rad", "pitch_rad", "sim_time_s"))):
                    return False
        for phase in (row["initial_plateau"],
                      row["pulses"][0]["plateau"],
                      row["pulses"][1]["plateau"]):
            if any(abs(v) > .005 for sample in phase for v in sample["applied"]):
                return False
            if abs(wrapped_delta(phase[-1]["pose"]["heading_rad"],
                                 phase[0]["pose"]["heading_rad"])) > .005:
                return False
            if any(b["robot_t_ns"] <= a["robot_t_ns"]
                   for a, b in zip(phase, phase[1:])):
                return False
        if any(pulse_row["trajectory"][-1]["robot_t_ns"] <=
               pulse_row["trajectory"][0]["robot_t_ns"]
               for pulse_row in row["pulses"]):
            return False
        recomputed = wrapped_delta(heading_median(row["pulses"][-1]["plateau"]),
                                   heading_median(row["initial_plateau"]))
        return math.isclose(row["delta_heading_rad"], recomputed, abs_tol=1e-10)
    except (KeyError, TypeError, ValueError, IndexError):
        return False


def score(protocol: dict, records: list[dict]) -> dict:
    planned = matrix(protocol)
    if len(records) != 50 or any(
            (row.get("id"), row.get("seed"), row.get("condition")) !=
            (expected["id"], expected["seed"], expected["condition"])
            for row, expected in zip(records, planned)):
        return {"result": "FAIL", "reason": "missing/reordered development matrix"}
    if any(not trace_integrity(row, expected)
           for row, expected in zip(records, planned)):
        return {"result": "FAIL", "reason": "invalid or incomplete reset",
                "invalid_ids": [expected["id"] for row, expected in zip(records, planned)
                                if not trace_integrity(row, expected)]}
    shams = [abs(row["delta_heading_rad"]) for row in records
             if row["condition"] == "sham"]
    floor = max(protocol["measurement"]["minimum_abs_delta_rad"],
                max(shams) + protocol["measurement"]["sham_margin_rad"])
    positive = [row["delta_heading_rad"] for row in records
                if row["condition"] == "positive"]
    negative = [row["delta_heading_rad"] for row in records
                if row["condition"] == "negative"]
    if len(positive) != 20 or len(negative) != 20 or len(shams) != 10:
        return {"result": "FAIL", "reason": "condition counts"}
    classifications = {
        row["id"]: ("EXPECTED" if row["condition"] == "sham" or
                    (row["condition"] == "positive" and row["delta_heading_rad"] > floor) or
                    (row["condition"] == "negative" and row["delta_heading_rad"] < -floor)
                    else "WRONG_SIGN" if
                    (row["condition"] == "positive" and row["delta_heading_rad"] < -floor) or
                    (row["condition"] == "negative" and row["delta_heading_rad"] > floor)
                    else "INCONCLUSIVE")
        for row in records}
    return {"result": "PASS" if all(v == "EXPECTED" for v in classifications.values())
            else "FAIL", "noise_floor_rad": floor,
            "positive_delta_rad": positive, "negative_delta_rad": negative,
            "sham_abs_delta_rad": shams, "classifications": classifications,
            "development_only": True}


def score_root(root: Path) -> dict:
    """Recompute from a downloaded copy without trusting the saved gate."""
    protocol = json.loads((ROOT / "config/p8_03_r3_yaw_diagnostic_v1.json").read_text())
    manifest = json.loads((root / "manifest.json").read_text())
    if (manifest["schema_version"] != "p8-03-r3-manifest-v1" or
            len({entry["path"] for entry in manifest["files"]}) != len(manifest["files"])):
        raise RuntimeError("invalid raw manifest")
    for entry in manifest["files"]:
        path = root / entry["path"]
        if (not path.is_file() or sha(path) != entry["sha256"] or
                path.stat().st_size != entry["bytes"] or
                len(path.read_bytes().splitlines()) != entry["record_count"]):
            raise RuntimeError(f"raw manifest mismatch: {entry['path']}")
    traces = []
    for item in matrix(protocol):
        path = root / item["id"] / "trace.json"
        if not path.is_file():
            break
        traces.append(json.loads(path.read_text()))
    return score(protocol, traces)


def run(output: Path, reviewed_head: str) -> None:
    protocol_path = ROOT / "config/p8_03_r3_yaw_diagnostic_v1.json"
    protocol = json.loads(protocol_path.read_text())
    if protocol["schema_version"] != "p8-03-r3-yaw-diagnostic-v1" or output != OUTPUT or output.exists():
        raise RuntimeError("frozen R3 protocol or single-use output mismatch")
    if (not socket.gethostname().startswith("jetsonthor") or
            platform.python_version_tuple()[:2] != ("3", "12") or
            subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                    text=True).strip() != reviewed_head or
            subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT,
                                    text=True).strip()):
        raise RuntimeError("clean reviewed Thor Python 3.12 source required")
    verify_material()
    preprobe = probe_final_sim_state(STATE, PORT, phase="r3_preflight")
    if preprobe["result"] != "PASS":
        raise RuntimeError("dedicated simulator state is occupied")
    output.mkdir(parents=True, exist_ok=False)
    start_ticks = process_start_ticks()
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    if hasattr(signal, "SIGHUP"):
        signal.signal(signal.SIGHUP, interrupted)
    atomic_json(output / "run.json", {
        "status": "RUNNING", "source_head": reviewed_head,
        "pid": os.getpid(), "process_start_ticks": start_ticks,
        "active_id": None, "completed_ids": [],
        "single_use_no_retry": True})
    atomic_json(output / "preflight.json", {"source_head": reviewed_head,
        "protocol_sha256": sha(protocol_path), "pinned": R1_CONFIG,
        "sim_probe": preprobe})
    sim = str(Path(R1_CONFIG["microduck_path"]) / "scripts/duck-sim")
    env = dict(os.environ, DUCK_SIM_VIEWER="0", DUCK_SIM_STATE=str(STATE),
               DUCK_SIM_KEYFRAME="SIT", DUCK_SIM_RL=R1_CONFIG["microduck_rl_path"],
               DUCK_SIM_PORT=str(PORT), PYTHONPATH=str(ROOT))
    env["PATH"] = str(Path(R1_CONFIG["microduck_path"]).parent /
                      "rustup/toolchains/stable-aarch64-unknown-linux-gnu/bin") + os.pathsep + env["PATH"]
    records = []
    for item in matrix(protocol):
        folder = output / item["id"]
        folder.mkdir()
        row = dict(item, source_head=reviewed_head, result="RUNNING",
                   started_ns=time.monotonic_ns())
        atomic_json(folder / "trace.json", row)
        atomic_json(output / "run.json", {
            "status": "RUNNING", "source_head": reviewed_head,
            "pid": os.getpid(), "process_start_ticks": start_ticks,
            "active_id": item["id"],
            "completed_ids": [r["id"] for r in records],
            "single_use_no_retry": True})
        try:
            row["down_before_exit"] = captured([sim, "down"], env, folder / "down-before.log")
            atomic_json(folder / "trace.json", row)
            if row["down_before_exit"]:
                raise RuntimeError("official pre-reset down failed")
            row["up_exit"] = captured([sim, "up"], env, folder / "up.log")
            atomic_json(folder / "trace.json", row)
            if row["up_exit"]:
                raise RuntimeError("official fresh up failed")
            row["policy_load_exit"] = captured(
                [sim, "ctl", "policy", "load", "walk", R1_CONFIG["walking_policy_path"]],
                env, folder / "policy-load.log")
            row["policy_readback_exit"] = captured(
                [sim, "ctl", "policy", "list", "--json"], env,
                folder / "policy-readback.json")
            atomic_json(folder / "trace.json", row)
            if row["policy_load_exit"] or row["policy_readback_exit"]:
                raise RuntimeError("policy load/readback failed")
            row["policy_verified"] = validate_loaded_walk_policy(
                json.loads((folder / "policy-readback.json").read_text()),
                Path(R1_CONFIG["walking_policy_path"]),
                R1_CONFIG["walking_policy_sha256"])
            sock = STATE / "duck-a.sock"
            row["initial_stop"] = bounded_stop(sock)
            if row["initial_stop"]["result"] != "PASS":
                raise RuntimeError("initial stop ACK missing")
            reader = TimedPoseReader(PORT)
            client = RobotdClient(str(sock), timeout_s=.2)
            command = JsonLines(str(sock))
            command.socket.settimeout(.2)
            stream = StateStream(str(sock))
            try:
                client.connect()
                row["health"] = client.health()
                if row["health"].get("healthy") is not True or row["health"].get("degraded"):
                    raise RuntimeError("robotd unhealthy")
                time.sleep(1.0)
                row["initial_plateau"] = plateau(reader, stream, None, None, "initial")
                first = row["initial_plateau"][0]["pose"]
                previous = row["initial_plateau"][-1]["pose"] | {
                    "robot_t_ns": row["initial_plateau"][-1]["robot_t_ns"]}
                row["pulses"] = []
                for number in (1, 2):
                    pulse_trace = {}
                    row["pulses"].append(pulse_trace)
                    atomic_json(folder / "trace.json", row)
                    pulse(reader, stream, command, first, previous,
                          item["condition"], number, pulse_trace)
                    previous = pulse_trace["plateau"][-1]["pose"] | {
                        "robot_t_ns": pulse_trace["plateau"][-1]["robot_t_ns"]}
                    atomic_json(folder / "trace.json", row)
                row["delta_heading_rad"] = wrapped_delta(
                    heading_median(row["pulses"][-1]["plateau"]),
                    heading_median(row["initial_plateau"]))
                row["final_heading_rad"] = heading_median(row["pulses"][-1]["plateau"])
                row["initial_heading_rad"] = heading_median(row["initial_plateau"])
                row["result"] = "VALID"
            finally:
                command.close()
                client.close()
                reader.close()
                stream.close()
        except BaseException as error:
            row["result"] = "FAIL"
            row["error"] = f"{type(error).__name__}: {error}"
        finally:
            row["cleanup_stop"] = bounded_stop(STATE / "duck-a.sock")
            try:
                row["down_after_exit"] = captured([sim, "down"], env, folder / "down-after.log")
            except BaseException as error:
                row["down_after_exit"] = None
                row["down_after_error"] = repr(error)
            try:
                row["final_probe"] = probe_final_sim_state(
                    STATE, PORT, phase="r3_final_down")
            except BaseException as error:
                row["final_probe"] = {"result": "FAIL", "error": repr(error)}
            if (row["cleanup_stop"]["result"] != "PASS" or
                    row["down_after_exit"] != 0 or row["final_probe"]["result"] != "PASS"):
                row["result"] = "FAIL"
                row["cleanup_failure"] = True
            atomic_json(folder / "trace.json", row)
            records.append(row)
            atomic_json(output / "run.json", {
                "status": "RUNNING", "source_head": reviewed_head,
                "pid": os.getpid(), "process_start_ticks": start_ticks,
                "active_id": None, "completed_ids": [r["id"] for r in records],
                "single_use_no_retry": True})
        if row["result"] != "VALID":
            break
    gate = score(protocol, records)
    gate.update({"schema_version": "p8-03-r3-yaw-gate-v1",
                 "source_head": reviewed_head, "protocol_sha256": sha(protocol_path),
                 "planned": 50, "observed": len(records)})
    manifest = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name not in ("manifest.json", "gate.json", "run.json"):
            raw = path.read_bytes()
            manifest.append({"path": path.relative_to(output).as_posix(),
                             "sha256": hashlib.sha256(raw).hexdigest(),
                             "bytes": len(raw), "record_count": len(raw.splitlines())})
    atomic_json(output / "manifest.json", {"schema_version": "p8-03-r3-manifest-v1",
                                          "files": manifest, "source_head": reviewed_head})
    gate["manifest_sha256"] = sha(output / "manifest.json")
    atomic_json(output / "gate.json", gate)
    atomic_json(output / "run.json", {
        "status": gate["result"], "source_head": reviewed_head,
        "pid": os.getpid(), "process_start_ticks": start_ticks,
        "active_id": None, "completed_ids": [r["id"] for r in records],
        "gate_sha256": sha(output / "gate.json"), "single_use_no_retry": True})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--reviewed-head")
    parser.add_argument("--score-root", type=Path)
    arguments = parser.parse_args()
    if arguments.score_root is not None:
        if arguments.output is not None or arguments.reviewed_head is not None:
            parser.error("--score-root is standalone")
        print(json.dumps(score_root(arguments.score_root), sort_keys=True))
    elif arguments.output is not None and arguments.reviewed_head is not None:
        run(arguments.output, arguments.reviewed_head)
    else:
        parser.error("run requires --output and --reviewed-head")
