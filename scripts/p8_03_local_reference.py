"""Prospective per-reset local-reference acquisition for official duck-sim.

Only official body pose and robotd read-only health/state enter this gate.
The reference is evaluator evidence; it is never a motion correction target.
"""

from __future__ import annotations

import json
import math
import socket
import threading
import time

from microduck_connectome.robotd_client import RobotdClient
from scripts.p6_telemetry_runtime_fixture import RobotStateSampler
from scripts.p8_02_r1_batch import atomic_json


def wrap(angle: float) -> float:
    return (angle + math.pi) % (2 * math.pi) - math.pi


def body_pose(packet: dict) -> dict:
    trunk, quat = packet["trunk"], packet["imu"]["quat"]
    if (type(trunk) is not list or len(trunk) != 3 or type(quat) is not list
            or len(quat) != 4 or not all(type(v) in (int, float) and math.isfinite(v)
                                            for v in trunk + quat)):
        raise ValueError("invalid official trunk/quaternion")
    w, x, y, z = quat
    return {"x_m": trunk[0], "y_m": trunk[1], "trunk_z_m": trunk[2],
            "heading_rad": math.atan2(2 * (w*z + x*y), 1 - 2 * (y*y + z*z)),
            "roll_rad": math.atan2(2 * (w*x + y*z), 1 - 2 * (x*x + y*y)),
            "pitch_rad": math.asin(max(-1., min(1., 2 * (w*y - z*x))))}


class RawBodyReader:
    """Official body protocol reader retaining raw packet and timing."""

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
        return {"request_ns": request_ns, "response_ns": response_ns,
                "raw_packet": raw.decode("utf-8").rstrip("\n"),
                "sim_time_s": packet.get("sim_time"), **body_pose(packet)}

    def close(self) -> None:
        self.stream.close()
        self.sock.close()


class PoseWithLineage:
    """Supply legacy exact-field pose dicts while retaining official raw lineage."""

    def __init__(self, port: int):
        self.reader = RawBodyReader(port)
        self.lock = threading.Lock()
        self.sources: dict[int, tuple[dict, dict]] = {}

    def read(self) -> dict:
        raw = self.reader.read()
        pose = {k: raw[k] for k in ("x_m", "y_m", "trunk_z_m", "heading_rad")}
        with self.lock:
            self.sources[id(pose)] = (pose, raw)
        return pose

    def source(self, pose: dict) -> dict:
        with self.lock:
            retained, raw = self.sources[id(pose)]
        if retained is not pose:
            raise RuntimeError("pose source identity changed")
        return raw

    def close(self) -> None:
        self.reader.close()


def valid_sample(row: dict, gate: dict, up_exit_ns: int) -> bool:
    """One complete, fresh, nonmoving, safe post-up observation."""
    try:
        pose, state, health = row["pose"], row["state"], row["health"]
        t = pose["response_ns"]
        applied = state["move"]["applied"]
        safety = state["safety"]
        return (
            t >= up_exit_ns + int(gate["post_up_min_capture_s"] * 1e9)
            and 0 <= t - pose["request_ns"] <= gate["max_pose_response_age_ms"] * 1e6
            and abs(t - row["state_received_ns"]) <= gate["max_robotd_state_age_ms"] * 1e6
            and abs(t - row["health_received_ns"]) <= gate["max_health_age_ms"] * 1e6
            and health.get("healthy") is True and health.get("degraded") in (None, False)
            and type(health.get("control_loop", {}).get("ticks")) is int
            and health["control_loop"]["ticks"] > 0
            and state.get("policy") in gate["allowed_observed_policy_states"]
            and not safety.get("fallen") and not safety.get("limp")
            and len(applied) == 3
            and all(type(v) in (int, float) and math.isfinite(v) for v in applied)
            and all(abs(v) <= gate[k] for v, k in zip(applied, (
                "max_abs_applied_vx_mps", "max_abs_applied_vy_mps",
                "max_abs_applied_vyaw_radps")))
            and max(abs(pose["roll_rad"]), abs(pose["pitch_rad"]))
                <= gate["max_abs_roll_pitch_rad"]
            and all(math.isfinite(pose[k]) for k in (
                "x_m", "y_m", "trunk_z_m", "heading_rad"))
        )
    except (KeyError, TypeError, ValueError, IndexError):
        return False


def settled_reference(rows: list[dict], gate: dict, up_exit_ns: int) -> dict | None:
    """Freeze the last fresh pose in the first qualifying complete window."""
    duration_ns = int(gate["settle_window_s"] * 1e9)
    for start_index, start in enumerate(rows):
        if not valid_sample(start, gate, up_exit_ns):
            continue
        end_index = next((i for i in range(start_index, len(rows))
                          if rows[i]["pose"]["response_ns"] >=
                          start["pose"]["response_ns"] + duration_ns), None)
        if end_index is None:
            break
        window = rows[start_index:end_index + 1]
        if len(window) < gate["minimum_distinct_pose_samples"]:
            continue
        timestamps = [r["pose"]["response_ns"] for r in window]
        sim_times = [r["pose"].get("sim_time_s") for r in window]
        if any(b <= a or b - a > gate["max_pose_gap_ms"] * 1e6
               for a, b in zip(timestamps, timestamps[1:])):
            continue
        if (not all(type(t) in (int, float) and math.isfinite(t)
                    for t in sim_times) or
                any(b <= a for a, b in zip(sim_times, sim_times[1:]))):
            continue
        if not all(valid_sample(r, gate, up_exit_ns) for r in window):
            continue
        health_times = sorted({r["health_received_ns"] for r in window})
        if (len(health_times) < 2 or
                any(b - a > gate["max_health_poll_gap_ms"] * 1e6
                    for a, b in zip(health_times, health_times[1:])) or
                timestamps[-1] - health_times[-1] > gate["max_health_age_ms"] * 1e6):
            continue
        first = start["pose"]
        if not all(math.hypot(r["pose"]["x_m"] - first["x_m"],
                              r["pose"]["y_m"] - first["y_m"])
                   <= gate["max_planar_drift_m"]
                   and abs(r["pose"]["trunk_z_m"] - first["trunk_z_m"])
                   <= gate["max_z_drift_m"]
                   and abs(wrap(r["pose"]["heading_rad"] - first["heading_rad"]))
                   <= gate["max_heading_drift_rad"] for r in window):
            continue
        last = window[-1]["pose"]
        return {"schema_version": "p8-03-local-reference-v1", "result": "PASS",
                "reference": {key: last[key] for key in (
                    "x_m", "y_m", "trunk_z_m", "heading_rad", "roll_rad", "pitch_rad")},
                "capture_ns": last["response_ns"],
                "window_start_ns": timestamps[0], "window_end_ns": timestamps[-1],
                "window_start_index": start_index, "window_end_index": end_index,
                "up_exit_ns": up_exit_ns, "samples": rows[:end_index + 1]}
    return None


def acquire_local_reference(socket_path: str, body_port: int, gate: dict,
                            up_exit_ns: int) -> dict:
    """Observe after official up and policy readback, before robot.move."""
    robot = RobotdClient(socket_path, timeout_s=.2)
    body = None
    sampler = None
    rows: list[dict] = []
    last_health = None
    health_ns = None
    deadline_ns = up_exit_ns + int(gate["post_up_max_capture_s"] * 1e9)
    try:
        robot.connect()
        body = RawBodyReader(body_port)
        sampler = RobotStateSampler(socket_path)
        while time.monotonic_ns() <= deadline_ns:
            tick = time.monotonic_ns()
            pose = body.read()
            if last_health is None or tick - health_ns >= int(.2e9):
                last_health = robot.health()
                health_ns = time.monotonic_ns()
            with sampler.condition:
                state = json.loads(json.dumps(sampler.latest)) if sampler.latest else None
                state_ns = sampler.received_ns
                stream_error = sampler.error
            if stream_error is not None:
                raise RuntimeError("robotd state stream failed") from stream_error
            rows.append({"pose": pose, "state": state, "state_received_ns": state_ns,
                         "health": last_health, "health_received_ns": health_ns})
            result = settled_reference(rows, gate, up_exit_ns)
            if result is not None:
                return result
            time.sleep(max(0., .02 - (time.monotonic_ns() - tick) / 1e9))
        return {"schema_version": "p8-03-local-reference-v1", "result": "FAIL",
                "reason": "post_up_settle_timeout", "up_exit_ns": up_exit_ns,
                "samples": rows}
    finally:
        if sampler is not None:
            sampler.close()
        if body is not None:
            body.close()
        robot.disconnect()


def verify_local_reference(record: dict, gate: dict) -> bool:
    """Recompute eligibility and reference from captured raw samples."""
    try:
        if record.get("result") != "PASS" or record.get("schema_version") != (
                "p8-03-local-reference-v1"):
            return False
        rows = record["samples"]
        for row in rows:
            pose = row["pose"]
            derived = body_pose(json.loads(pose["raw_packet"]))
            if any(not math.isclose(pose[k], derived[k], abs_tol=1e-10, rel_tol=0)
                   for k in derived):
                return False
        recomputed = settled_reference(rows, gate, record["up_exit_ns"])
        return (recomputed is not None and all(
            record.get(k) == recomputed[k] for k in (
                "reference", "capture_ns", "window_start_ns", "window_end_ns",
                "window_start_index", "window_end_index", "up_exit_ns", "samples")))
    except (KeyError, TypeError, ValueError, IndexError, OverflowError):
        return False


def create_durable_arm_marker(path, marker: dict) -> None:
    """Child-only arm creation; marker is durable before scored arm is effective."""
    if path.exists():
        raise FileExistsError(path)
    if (marker.get("state") != "ARMED" or
            marker.get("schema_version") != "p8-03-local-arm-v1"):
        raise ValueError("invalid arm marker state")
    atomic_json(path, marker)
