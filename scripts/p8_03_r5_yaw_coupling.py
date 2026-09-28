"""R5 development-only yaw/translation coupling diagnostic."""
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
OUTPUT = PARENT / "p8-03-r5-yaw-coupling-v1"
STATE = Path("/tmp/p8-03-r5-yaw-coupling-state")
PORT = 7900
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
    client = RobotdClient(str(sock), timeout_s=.1)
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
        result["latency_s"] = (result["completed_ns"] - result["started_ns"]) / 1e9
        if result["latency_s"] > .2:
            result["result"] = "FAIL"
            result["deadline_exceeded"] = True
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


def durable_mkdir(path: Path) -> None:
    path.mkdir(parents=False, exist_ok=False)
    if os.name == "nt":
        return  # R5 execution is pinned to Thor/Linux; Windows supports local logic tests.
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class SafetyAbort(RuntimeError):
    def __init__(self, reason: str, current: dict, previous: dict | None,
                 measured: float | None, threshold: float | None):
        super().__init__(reason)
        self.trigger = {
            "reason": reason, "trigger_sample_index": current["sample_index"],
            "previous_sample_index": None if previous is None else previous["sample_index"],
            "trigger_pose": current["pose"],
            "previous_pose": None if previous is None else previous["pose"],
            "measured": measured, "threshold": threshold,
            "command_active_duration_s": current.get("command_active_duration_s")}


class SampleJournal:
    """Append-only, fsynced raw observations; bound evaluation follows append."""

    def __init__(self, path: Path):
        self.path = path
        self.fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND, 0o644)
        self.next_index = 0
        self.last_pose: dict | None = None
        self.first_pose: dict | None = None
        self.last_robot_t_ns: int | None = None
        self.last_robot_advance_ns: int | None = None
        if os.name != "nt":
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)

    def append(self, kind: str, payload: dict) -> dict:
        record = {"kind": kind, "sample_index": self.next_index, **payload}
        data = (json.dumps(record, sort_keys=True, separators=(",", ":"),
                           allow_nan=False) + "\n").encode()
        sent = 0
        while sent < len(data):
            count = os.write(self.fd, data[sent:])
            if count <= 0:
                raise OSError("raw journal short write")
            sent += count
        os.fsync(self.fd)
        self.next_index += 1
        if kind == "pose":
            if self.first_pose is None:
                self.first_pose = record
            self.last_pose = record
        return record

    def close(self) -> None:
        os.close(self.fd)


def matrix(protocol: dict) -> list[dict]:
    assert protocol["schema_version"] == "p8-03-r5-yaw-coupling-v1"
    assert protocol["blocks"] == 6 and protocol["seed_first"] == 888200
    assert protocol["seed_last"] == 888229
    assert protocol["even_block"] == [
        "sham", "positive_low", "negative_low", "positive_medium", "negative_medium"]
    assert protocol["odd_block"] == [
        "sham", "negative_low", "positive_low", "negative_medium", "positive_medium"]
    assert protocol["sham_ticks_by_block"] == [3, 5, 3, 5, 3, 5]
    assert protocol["development_only"] is True
    assert protocol["dose"] == {
        "low_ticks": 3, "medium_ticks": 5, "tick_s": .02,
        "abs_vyaw_radps": .2, "vx_mps": 0., "vy_mps": 0.,
        "max_through_stop_s": .30, "max_command_integral_rad": .08,
        "ttl_s": .10}
    assert protocol["pose"]["max_motion_xy_from_initial_m"] == .01
    assert protocol["measurement"]["minimum_abs_delta_rad"] == .005
    rows = []
    for block in range(6):
        conditions = protocol["even_block"] if block % 2 == 0 else protocol["odd_block"]
        for condition in conditions:
            index = len(rows)
            ticks = (protocol["sham_ticks_by_block"][block] if condition == "sham"
                     else protocol["dose"]["low_ticks"] if condition.endswith("_low")
                     else protocol["dose"]["medium_ticks"])
            rows.append({"id": f"C{index:02d}", "seed": 888200 + index,
                         "block": block, "condition": condition, "ticks": ticks,
                         "vyaw_radps": 0. if condition == "sham" else
                         .2 if condition.startswith("positive") else -.2})
    assert len(rows) == 30 and rows[-1]["seed"] == protocol["seed_last"]
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
        raw = self.stream.readline()
        try:
            packet = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            packet = {}
        if not isinstance(packet, dict):
            packet = {}
        response_ns = time.monotonic_ns()
        imu = packet.get("imu")
        trunk = packet.get("trunk")
        quat = imu.get("quat") if isinstance(imu, dict) else None
        sim_time = packet.get("sim_time")
        valid = (isinstance(trunk, list) and len(trunk) == 3 and
                 isinstance(quat, list) and len(quat) == 4 and
                 isinstance(sim_time, (float, int)) and
                 all(type(v) in (int, float) and math.isfinite(v)
                     for v in trunk + quat + [sim_time]))
        if valid:
            w, x, y, z = quat
            roll = math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y))
            pitch = math.asin(max(-1., min(1., 2 * (w * y - z * x))))
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

    def close(self):
        self.stream.close()
        self.sock.close()


def validate_pose(record: dict, previous: dict | None, first: dict | None,
                  *, moving: bool, check_clock: bool = True) -> None:
    pose = record["pose"]
    def breach(reason: str, measured: float | None, threshold: float | None):
        raise SafetyAbort(reason, record, previous, measured, threshold)
    if any(type(pose[key]) not in (int, float) or not math.isfinite(pose[key])
           for key in ("sim_time_s", "x_m", "y_m", "trunk_z_m",
                       "heading_rad", "roll_rad", "pitch_rad")):
        breach("malformed_or_nonfinite_pose", None, None)
    age = (pose["response_ns"] - pose["request_ns"]) / 1e9
    if age > .1 or age < 0:
        breach("pose_response_stale", age, .1)
    if previous is not None and check_clock:
        prev_pose = previous["pose"]
        interval = (pose["response_ns"] - prev_pose["response_ns"]) / 1e9
        if pose["sim_time_s"] <= prev_pose["sim_time_s"] or not .01 <= interval <= .25:
            breach("pose_or_simulator_clock_not_advancing", interval, .01)
    attitude = max(abs(pose["roll_rad"]), abs(pose["pitch_rad"]))
    if attitude > .5:
        breach("body_attitude_bound_exceeded", attitude, .5)
    if first is None:
        for key, bound in (("x_m", .03), ("y_m", .03), ("trunk_z_m", .025)):
            measured = abs(pose[key] - REFERENCE[key])
            if measured > bound:
                breach(f"initial_{key}_bound_exceeded", measured, bound)
        heading = abs(wrapped_delta(pose["heading_rad"], REFERENCE["heading_rad"]))
        if heading > .35:
            breach("initial_heading_inclusion_exceeded", heading, .35)
    elif moving:
        for key in ("displacement_from_reset_start_m",
                    "displacement_from_command_start_m"):
            displacement = record[key]
            if displacement >= .01:
                breach(f"{key}_bound_exceeded", displacement, .01)


def sampled(reader: TimedPoseReader, stream: StateStream, journal: SampleJournal,
            health_client: RobotdClient, first: dict | None,
            health_cache: dict, command_context: dict,
            *, phase: str, moving: bool, require_walk: bool = False) -> dict:
    deadline = time.monotonic() + .05
    while True:
        pose = reader.read()
        previous = journal.last_pose
        state = stream.latest
        state_received_ns = stream.received_ns
        # Persist the untouched observation before computing any derived value.
        row = journal.append("pose", {
            "phase": phase, "pose": pose, "host_monotonic_ns": time.monotonic_ns(),
            "robot_t_ns": None if state is None else state.get("t_ns"),
            "state_received_ns": state_received_ns,
            "requested": None if state is None else state.get("move", {}).get("requested"),
            "applied": None if state is None else state.get("move", {}).get("applied"),
            "limited_by": None if state is None else state.get("move", {}).get("limited_by"),
            "policy": None if state is None else state.get("policy"),
            "safety": None if state is None else state.get("safety"),
            "robotd_state": state,
            "robotd_health": health_cache["value"],
            "robotd_health_received_ns": health_cache["received_ns"],
            "last_command_ack": command_context.get("ack"),
            "commanded_vyaw_radps": command_context.get("vyaw_radps", 0.),
            "command_active_duration_s": command_context.get("active_duration_s", 0.),
            "previous_pose_sample_index": None if previous is None else previous["sample_index"]})
        origin = command_context.get("command_start_pose") or first or (None if journal.first_pose is None
                           else journal.first_pose["pose"]) or pose
        row["displacement_from_reset_start_m"] = math.hypot(
            pose["x_m"] - journal.first_pose["pose"]["x_m"],
            pose["y_m"] - journal.first_pose["pose"]["y_m"])
        row["displacement_from_command_start_m"] = math.hypot(
            pose["x_m"] - origin["x_m"], pose["y_m"] - origin["y_m"])
        row["wrapped_heading_delta_rad"] = wrapped_delta(
            pose["heading_rad"], origin["heading_rad"])
        journal.append("derived", {"pose_sample_index": row["sample_index"],
            "displacement_from_reset_start_m": row["displacement_from_reset_start_m"],
            "displacement_from_command_start_m": row["displacement_from_command_start_m"],
            "wrapped_heading_delta_rad": row["wrapped_heading_delta_rad"]})
        validate_pose(row, previous, first, moving=moving, check_clock=False)
        fresh = (previous is None or
                 (pose["sim_time_s"] > previous["pose"]["sim_time_s"] and
                  pose["response_ns"] - previous["pose"]["response_ns"] >= 10_000_000))
        if fresh:
            validate_pose(row, previous, first, moving=moving, check_clock=True)
            break
        if time.monotonic() >= deadline:
            raise SafetyAbort("fresh_pose_wait_expired", row, previous,
                              pose["sim_time_s"] - previous["pose"]["sim_time_s"], 0.)
        time.sleep(.002)
    if state is None or state_received_ns is None or pose["response_ns"] - state_received_ns > 100_000_000:
        raise SafetyAbort("robotd_state_stale", row, previous, None, .1)
    robot_t_ns = row["robot_t_ns"]
    if type(robot_t_ns) is not int:
        raise SafetyAbort("robotd_clock_malformed", row, previous, None, None)
    if journal.last_robot_t_ns is None or robot_t_ns > journal.last_robot_t_ns:
        journal.last_robot_t_ns = robot_t_ns
        journal.last_robot_advance_ns = pose["response_ns"]
    elif robot_t_ns < journal.last_robot_t_ns:
        raise SafetyAbort("robotd_clock_regressed", row, previous,
                          robot_t_ns - journal.last_robot_t_ns, 0.)
    elif pose["response_ns"] - journal.last_robot_advance_ns > 100_000_000:
        raise SafetyAbort("robotd_clock_frozen", row, previous,
                          (pose["response_ns"] - journal.last_robot_advance_ns) / 1e9, .1)
    if not isinstance(state.get("safety"), dict) or not isinstance(state.get("move"), dict):
        raise SafetyAbort("robotd_state_malformed", row, previous, None, None)
    if state["safety"].get("fallen") or state["safety"].get("limp"):
        raise SafetyAbort("robotd_safety_fault", row, previous, None, None)
    if state["policy"] not in ("stand", "walk"):
        raise SafetyAbort("unexpected_robotd_policy_state", row, previous, None, None)
    if require_walk and state["policy"] != "walk":
        raise SafetyAbort("walk_policy_not_active", row, previous, None, None)
    if health_cache["value"].get("healthy") is not True or health_cache["value"].get("degraded"):
        raise SafetyAbort("robotd_unhealthy", row, previous, None, None)
    if (pose["response_ns"] - health_cache["received_ns"]) > 100_000_000:
        raise SafetyAbort("robotd_health_stale", row, previous,
                          (pose["response_ns"] - health_cache["received_ns"]) / 1e9, .1)
    try:
        fresh_health = health_client.health()
    except BaseException as error:
        raise SafetyAbort("robotd_health_read_failed", row, previous, None, None) from error
    health_cache["value"] = fresh_health
    health_cache["received_ns"] = time.monotonic_ns()
    if fresh_health.get("healthy") is not True or fresh_health.get("degraded"):
        raise SafetyAbort("robotd_health_lost", row, previous, None, None)
    return row


def plateau(reader, stream, journal, health_client, health_cache, first,
            label: str, command_context: dict) -> list[dict]:
    rows = []
    start = time.monotonic() + (.05 if journal.last_pose is not None else 0.)
    for i in range(21):
        time.sleep(max(0, start + i * .05 - time.monotonic()))
        previous = journal.last_pose
        row = sampled(reader, stream, journal, health_client, first,
                      health_cache, command_context, phase=label,
                      moving=first is not None)
        if previous is not None and row["robot_t_ns"] <= previous["robot_t_ns"]:
            raise SafetyAbort("robotd_clock_not_advancing", row, previous,
                              row["robot_t_ns"] - previous["robot_t_ns"], 1.)
        if any(abs(v) > .005 for v in row["applied"]):
            raise SafetyAbort("stopped_applied_velocity_exceeded", row, previous,
                              max(abs(v) for v in row["applied"]), .005)
        rows.append(row)
    headings = [r["pose"]["heading_rad"] for r in rows]
    drift = abs(wrapped_delta(headings[-1], headings[0]))
    if drift > .005:
        raise SafetyAbort("plateau_heading_drift_exceeded", rows[-1], rows[-2],
                          drift, .005)
    return rows


def heading_median(rows: list[dict]) -> float:
    anchor = rows[0]["pose"]["heading_rad"]
    return anchor + statistics.median(
        wrapped_delta(r["pose"]["heading_rad"], anchor) for r in rows[-5:])


def pulse(reader, stream, journal, health_client, health_cache, command,
          first, item: dict, trace: dict) -> None:
    vyaw, ticks = item["vyaw_radps"], item["ticks"]
    duration = ticks * .02
    trace.update({"vyaw_radps": vyaw, "ticks": ticks, "duration_s": duration,
                  "requests": [], "trajectory": []})
    started = time.monotonic()
    trace["started_ns"] = time.monotonic_ns()
    last_ack_ns = None
    command_context = {"vyaw_radps": vyaw, "ack": None, "active_duration_s": 0.,
                       "command_start_pose": journal.last_pose["pose"]}
    try:
        for tick in range(ticks):
            due = started + tick * .02
            time.sleep(max(0, due - time.monotonic()))
            if time.monotonic() - due > .01:
                raise RuntimeError("50 Hz command refresh deadline exceeded")
            journal.append("command_request", {
                "tick": tick, "vyaw_radps": vyaw, "vx_mps": 0., "vy_mps": 0.,
                "scheduled_ns": trace["started_ns"] + tick * 20_000_000,
                "issued_ns": time.monotonic_ns()})
            ack, call_ns, write_ns, ack_ns = acknowledged_precondition_move(
                command, vx=0., vy=0., vyaw=vyaw)
            request = {"tick": tick, "ack": ack, "call_ns": call_ns,
                       "write_ns": write_ns, "ack_ns": ack_ns}
            journal.append("command_ack", request)
            if (ack_ns - call_ns > 100_000_000 or
                    last_ack_ns is not None and ack_ns - last_ack_ns > 100_000_000):
                raise RuntimeError("command ACK or TTL exceeded")
            trace["requests"].append(request)
            last_ack_ns = ack_ns
            command_context["ack"] = request
            command_context["active_duration_s"] = time.monotonic() - started
            time.sleep(max(0, due + .015 - time.monotonic()))
            row = sampled(reader, stream, journal, health_client, first,
                          health_cache, command_context, phase="COMMAND",
                          moving=True, require_walk=tick >= 2 and vyaw != 0.)
            trace["trajectory"].append(row)
        time.sleep(max(0, started + duration - time.monotonic()))
    except SafetyAbort as error:
        trace["trigger"] = error.trigger
        raise
    finally:
        trace["stop"] = bounded_stop(STATE / "duck-a.sock")
        trace["stop_completed_ns"] = time.monotonic_ns()
        trace["active_through_stop_s"] = time.monotonic() - started
        try:
            journal.append("stop_ack", trace["stop"] | {
                "active_through_stop_s": trace["active_through_stop_s"]})
        except BaseException as error:
            trace["stop_journal_error"] = repr(error)
    if "stop_journal_error" in trace:
        raise RuntimeError("stop ACK raw journal write failed")
    if trace["stop"]["result"] != "PASS":
        raise RuntimeError("stop ACK missing")
    if not duration <= trace["active_through_stop_s"] <= .3:
        raise RuntimeError("pulse including stop exceeded bounded duration")
    trace["post_stop_trajectory"] = []
    command_context["vyaw_radps"] = 0.
    command_context["ack"] = trace["stop"]
    trace["stop_ack_pose"] = sampled(reader, stream, journal, health_client,
        first, health_cache, command_context, phase="STOP_ACK", moving=True)
    settle_start = time.monotonic()
    for i in range(50):
        time.sleep(max(0, settle_start + (i + 1) * .02 - time.monotonic()))
        command_context["active_duration_s"] = trace["active_through_stop_s"]
        row = sampled(reader, stream, journal, health_client, first,
                      health_cache, command_context,
                      phase="POST_STOP" if i < 25 else "SETTLE",
                      moving=True)
        trace["post_stop_trajectory"].append(row)
        if i >= 24 and any(abs(v) > .005 for v in row["applied"]):
            raise SafetyAbort("motion_persisted_after_stop", row,
                              trace["post_stop_trajectory"][-2],
                              max(abs(v) for v in row["applied"]), .005)
    trace["plateau"] = plateau(reader, stream, journal, health_client,
                               health_cache, first, "SETTLE",
                               command_context)


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


from scripts.p8_03_r5_score import score, score_root, phase_metrics


def run(output: Path, reviewed_head: str) -> None:
    protocol_path = ROOT / "config/p8_03_r5_yaw_coupling_v1.json"
    protocol = json.loads(protocol_path.read_text())
    if protocol["schema_version"] != "p8-03-r5-yaw-coupling-v1" or output != OUTPUT or output.exists():
        raise RuntimeError("frozen R5 protocol or single-use output mismatch")
    if (not socket.gethostname().startswith("jetsonthor") or
            platform.python_version_tuple()[:2] != ("3", "12") or
            subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                    text=True).strip() != reviewed_head or
            subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT,
                                    text=True).strip()):
        raise RuntimeError("clean reviewed Thor Python 3.12 source required")
    verify_material()
    preprobe = probe_final_sim_state(STATE, PORT, phase="r5_preflight")
    if preprobe["result"] != "PASS":
        raise RuntimeError("dedicated simulator state is occupied")
    durable_mkdir(output)
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
        durable_mkdir(folder)
        row = dict(item, source_head=reviewed_head, result="RUNNING",
                   started_ns=time.monotonic_ns())
        atomic_json(folder / "trace.json", row)
        journal = SampleJournal(folder / "samples.jsonl")
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
                health_cache = {"value": client.health(),
                                "received_ns": time.monotonic_ns()}
                neutral_context = {"vyaw_radps": 0., "ack": row["initial_stop"],
                                   "active_duration_s": 0.}
                row["initial_plateau"] = plateau(
                    reader, stream, journal, client, health_cache, None,
                    "PRE", neutral_context)
                first = row["initial_plateau"][0]["pose"]
                row["pulses"] = []
                pulse_trace = {}
                row["pulses"].append(pulse_trace)
                atomic_json(folder / "trace.json", row)
                pulse(reader, stream, journal, client, health_cache, command,
                      first, item, pulse_trace)
                atomic_json(folder / "trace.json", row)
                row["delta_heading_rad"] = wrapped_delta(
                    heading_median(row["pulses"][-1]["plateau"]),
                    heading_median(row["initial_plateau"]))
                row["final_heading_rad"] = heading_median(row["pulses"][-1]["plateau"])
                row["initial_heading_rad"] = heading_median(row["initial_plateau"])
                moving_rows = pulse_trace["trajectory"]
                stopped_rows = pulse_trace["post_stop_trajectory"]
                all_rows = moving_rows + stopped_rows + pulse_trace["plateau"]
                row["metrics"] = {
                    "during_pulse_heading_delta_rad": wrapped_delta(
                        moving_rows[-1]["pose"]["heading_rad"],
                        row["initial_heading_rad"]),
                    "first_100ms_post_stop_delta_rad": wrapped_delta(
                        stopped_rows[4]["pose"]["heading_rad"],
                        moving_rows[-1]["pose"]["heading_rad"]),
                    "post_stop_rebound_rad": wrapped_delta(
                        row["final_heading_rad"],
                        moving_rows[-1]["pose"]["heading_rad"]),
                    "max_planar_displacement_m": max(
                        x["displacement_from_reset_start_m"] for x in all_rows),
                    "final_y_displacement_m": pulse_trace["plateau"][-1]["pose"]["y_m"] - first["y_m"],
                    "post_stop_min_heading_rad": min(x["pose"]["heading_rad"] for x in stopped_rows),
                    "post_stop_max_heading_rad": max(x["pose"]["heading_rad"] for x in stopped_rows),
                    "applied_yaw_integral_rad": sum(
                        x["applied"][2] * .02 for x in moving_rows)}
                row["phase_metrics"] = phase_metrics(row)
                row["result"] = "VALID"
            finally:
                command.close()
                client.close()
                reader.close()
                stream.close()
        except BaseException as error:
            row["result"] = "SAFETY_ABORT" if isinstance(error, SafetyAbort) else "DATA_INTEGRITY_ABORT"
            row["error"] = f"{type(error).__name__}: {error}"
            if isinstance(error, SafetyAbort):
                row["trigger"] = error.trigger
        finally:
            row["cleanup_stop"] = bounded_stop(STATE / "duck-a.sock")
            try:
                row["down_after_exit"] = captured([sim, "down"], env, folder / "down-after.log")
            except BaseException as error:
                row["down_after_exit"] = None
                row["down_after_error"] = repr(error)
            try:
                row["final_probe"] = probe_final_sim_state(
                    STATE, PORT, phase="r5_final_down")
            except BaseException as error:
                row["final_probe"] = {"result": "FAIL", "error": repr(error)}
            if (row["cleanup_stop"]["result"] != "PASS" or
                    row["down_after_exit"] != 0 or row["final_probe"]["result"] != "PASS"):
                row["result"] = "CLEANUP_ABORT"
                row["cleanup_failure"] = True
            try:
                journal.append("cleanup", {
                    "stop": row["cleanup_stop"], "down_exit": row.get("down_after_exit"),
                    "final_probe": row["final_probe"], "trigger": row.get("trigger")})
            except BaseException as error:
                row["cleanup_journal_error"] = repr(error)
                row["result"] = "DATA_INTEGRITY_ABORT"
            try:
                journal.close()
            except BaseException as error:
                row["journal_close_error"] = repr(error)
                row["result"] = "DATA_INTEGRITY_ABORT"
            atomic_json(folder / "trace.json", row)
            records.append(row)
            atomic_json(output / "run.json", {
                "status": "RUNNING", "source_head": reviewed_head,
                "pid": os.getpid(), "process_start_ticks": start_ticks,
                "active_id": None, "completed_ids": [r["id"] for r in records],
                "single_use_no_retry": True})
        if row["result"] != "VALID":
            break
    gate = score(protocol, records, output)
    gate.update({"schema_version": "p8-03-r5-yaw-coupling-gate-v1",
                 "source_head": reviewed_head, "protocol_sha256": sha(protocol_path),
                 "planned": 30, "observed": len(records)})
    manifest = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name not in ("manifest.json", "gate.json", "run.json"):
            raw = path.read_bytes()
            manifest.append({"path": path.relative_to(output).as_posix(),
                             "sha256": hashlib.sha256(raw).hexdigest(),
                             "bytes": len(raw), "record_count": len(raw.splitlines())})
    atomic_json(output / "manifest.json", {"schema_version": "p8-03-r5-manifest-v1",
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
        print(json.dumps(score_root(
            arguments.score_root, ROOT / "config/p8_03_r5_yaw_coupling_v1.json"),
            sort_keys=True))
    elif arguments.output is not None and arguments.reviewed_head is not None:
        run(arguments.output, arguments.reviewed_head)
    else:
        parser.error("run requires --output and --reviewed-head")
