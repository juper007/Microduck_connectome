"""Inject P6-06 faults against Thor's official robotd and MuJoCo body."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import signal
import socket
import subprocess
import time

from microduck_connectome.control_contracts import make_behavior_intent
from microduck_connectome.fault_evidence import REQUIRED_FAULTS, build_fault_matrix, make_fault_record, write_fault_matrix
from microduck_connectome.motion_adapter import MotionAdapterError, RobotMotionAdapter
from microduck_connectome.perception_compositor import PerceptionPipeline
from microduck_connectome.robotd_client import RobotdClient, RobotdConnectionError, RobotdTimeoutError
from microduck_connectome.watchdog import ControllerWatchdog


def git_head(path: Path) -> str:
    return subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()


def wait_for(predicate, timeout_s=12.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise RuntimeError("timed out waiting for scoped runtime lifecycle")


def process_exited(pid: int) -> bool:
    """Treat an unreaped child zombie as exited; it cannot own IPC or motion."""
    stat = Path(f"/proc/{pid}/stat")
    if not stat.exists():
        return True
    try:
        return stat.read_text(encoding="ascii").split()[2] == "Z"
    except (OSError, IndexError):
        return not stat.exists()


def quaternion_yaw(wxyz):
    w, x, y, z = wxyz
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


class BodyReader:
    def __init__(self, port):
        self.socket = socket.create_connection(("127.0.0.1", port), timeout=2.0)
        self.file = self.socket.makefile("rwb")
        self.file.write(b'{"op":"hello","protocol":1,"joints":15}\n')
        self.file.flush()
        if json.loads(self.file.readline()) != {"protocol": 1}:
            raise RuntimeError("unexpected MuJoCo body hello")

    def heading(self):
        self.file.write(b'{"op":"read"}\n')
        self.file.flush()
        return quaternion_yaw(json.loads(self.file.readline())["imu"]["quat"])

    def close(self):
        self.file.close()
        self.socket.close()


class Session:
    def __init__(self, args, raw):
        self.args = args
        self.raw = raw
        self.sequence = 0
        self.client = RobotdClient(str(args.socket), timeout_s=args.timeout_s)
        self.client.connect()
        self.client.enable(True)
        self.adapter = RobotMotionAdapter(self.client, args.root / "config/motion_adapter_v1.json")
        self.body = BodyReader(args.body_port)

    def next_meta(self):
        self.sequence += 2
        return time.monotonic_ns(), self.sequence

    def output(self, *, stop=False, vx=0.0, vyaw=0.0, mode="healthy"):
        timestamp, sequence = self.next_meta()
        watchdog = ControllerWatchdog(self.args.root / "config/watchdog_v1.json")
        if mode == "decoder_crash":
            watchdog.mark_decoder_crashed(1)
        elif mode == "missing":
            pass
        else:
            neural_time = timestamp
            behavior_time = timestamp
            healthy = True
            if mode in ("stale_neural", "stale_behavior"):
                if mode == "stale_neural": neural_time -= 100_000_001
                else: behavior_time -= 100_000_001
            if mode == "runtime_unhealthy": healthy = False
            neural = {
                "timestamp_ns": neural_time, "sequence": sequence,
                "steering_left": 0.0, "steering_right": 0.2,
                "escape": 0.0, "runtime_healthy": healthy,
            }
            if mode == "malformed_neural": neural["steering_left"] = float("nan")
            watchdog.observe_neural(neural)
            watchdog.observe_behavior(make_behavior_intent(
                timestamp_ns=behavior_time, sequence=sequence,
                vx=vx, vyaw=vyaw, stop=stop,
            ))
        output = watchdog.tick(now_ns=time.monotonic_ns(), output_sequence=sequence + 1)
        return output

    def motion(self):
        output = self.output(vyaw=0.2)
        self.adapter.send(output)
        time.sleep(0.06)
        return output

    def safe_state(self):
        observer = RobotdClient(str(self.args.socket), timeout_s=2.0)
        observer.connect()
        # robot.stop changes policy immediately, while the official policy's
        # applied velocity converges through its own bounded smoothing.
        deadline = time.monotonic() + 3.0
        state = None
        while time.monotonic() < deadline:
            state = observer.state(hz=50)
            requested = state["move"]["requested"]
            applied = state["move"]["applied"]
            if all(abs(float(v)) <= 1e-6 for v in requested + applied):
                break
        else:
            raise RuntimeError(f"official robot.state did not reach rest: {state['move']!r}")
        # A zero command alone is not motion-stop evidence. Restart recovery can
        # carry body momentum, so require consecutive MuJoCo headings to settle.
        heading_deadline = time.monotonic() + 3.0
        before = self.body.heading()
        while True:
            time.sleep(0.10)
            after = self.body.heading()
            delta = abs(after - before)
            if delta <= 0.02:
                break
            if time.monotonic() >= heading_deadline:
                raise RuntimeError(f"MuJoCo heading still changing after stop: {delta}")
            before = after
        observer.close()
        return {
            "requested": list(state["move"]["requested"]),
            "applied": list(state["move"]["applied"]),
            "heading_before_rad": before, "heading_after_rad": after,
            "heading_delta_rad": delta,
        }

    def recover(self, old_output):
        try:
            self.adapter.send(old_output)
            raise AssertionError("pre-fault command replay was accepted")
        except MotionAdapterError:
            pass
        fresh = self.output(vyaw=-0.2)
        self.adapter.send(fresh)
        time.sleep(0.04)
        self.adapter.send(self.output(mode="missing"))
        self.safe_state()
        return time.monotonic_ns()

    def close(self):
        try: self.client.close()
        finally: self.body.close()


def observe_perception(root, fault):
    pipeline = PerceptionPipeline()
    now = time.monotonic_ns()
    timestamp = now - 100_000_001 if fault == "stale_perception" else now
    camera_valid = fault not in ("camera_dropout", "invalid_perception", "compositor_invalid")
    tof_valid = fault != "tof_dropout"
    frame = pipeline.process(
        (((255, 0, 0),),), camera_timestamp_ns=timestamp, camera_frame_id=1,
        tof_left_mm=500, tof_center_mm=500, tof_right_mm=500,
        tof_timestamp_ns=timestamp, tof_frame_id=1, now_ns=now,
        camera_source_valid=camera_valid, tof_source_valid=tof_valid,
    )
    if frame["valid"]:
        raise AssertionError(f"{fault} did not neutralize perception")
    return {"valid": frame["valid"], "reasons": list(pipeline.compositor.last_reasons)}


def standard_fault(session, name, mode, raw, perception=False):
    old = session.motion()
    injected = time.monotonic_ns()
    if mode in ("stale_neural", "stale_behavior") or name == "stale_perception":
        # A freeze/stale fault begins when updates cease. Let the frozen 100 ms
        # TTL elapse in monotonic wall time instead of fabricating zero latency.
        time.sleep(0.101)
    condition = observe_perception(session.args.root, name) if perception else {"mode": mode}
    output = session.output(mode=mode)
    if output["watchdog_state"] != "safe_stop" or not output["intent"]["stop"]:
        raise AssertionError(f"{name} did not reach watchdog safe stop")
    detected = time.monotonic_ns()
    session.adapter.send(output)
    safe_at = time.monotonic_ns()
    state = session.safe_state()
    stopped = time.monotonic_ns()
    recovered = session.recover(old)
    raw.append({"fault": name, "condition": condition, "stale_reason": output["stale_reason"]})
    return make_fault_record(
        fault=name, injected_at_ns=injected, detected_at_ns=detected,
        safe_command_at_ns=safe_at, motion_stopped_at_ns=stopped,
        recovery_at_ns=recovered, state_evidence=state,
    )


def verified_pid(pid_file: Path, expected: Path, socket_path: Path):
    pid = int(pid_file.read_text(encoding="ascii").strip())
    cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode()
    if str(expected) not in cmdline or str(socket_path) not in cmdline:
        raise RuntimeError(f"refusing to signal unverified pid {pid}: {cmdline}")
    return pid


def restart_robotd(args):
    env = dict(os.environ)
    env.update({"DUCK_IDENTITY": "duck-a", "DUCK_RUNTIME_DIR": str(args.runtime_dir),
                "ORT_DYLIB_PATH": str(args.ort_dylib), "RUST_LOG": "info"})
    log = args.runtime_dir / "p6-06-robotd-restart.log"
    handle = log.open("ab")
    process = subprocess.Popen([
        str(args.robotd), "--sim", f"127.0.0.1:{args.body_port}",
        "--params", str(args.params), "--socket", str(args.socket),
    ], env=env, stdout=handle, stderr=subprocess.STDOUT, start_new_session=True)
    args.pid_file.write_text(f"{process.pid}\n", encoding="ascii")
    wait_for(lambda: args.socket.exists() and process.poll() is None)
    handle.close()
    return process.pid


def reconnect_and_stop(session):
    wait_for(lambda: session.args.socket.exists())
    session.client.reconnect()
    session.client.enable(True)
    stop = session.output(mode="missing")
    session.adapter.send(stop)
    safe_at = time.monotonic_ns()
    session.body.close()
    session.body = BodyReader(session.args.body_port)
    state = session.safe_state()
    return safe_at, state, time.monotonic_ns()


def lifecycle_fault(session, name, args, raw, action):
    old = session.motion()
    injected = time.monotonic_ns()
    action()
    try:
        session.adapter.send(session.output(mode="missing"))
        raise AssertionError(f"{name} was not detected")
    except (RobotdConnectionError, RobotdTimeoutError, OSError):
        detected = time.monotonic_ns()
    restart_robotd(args)
    safe_at, state, stopped = reconnect_and_stop(session)
    recovered = session.recover(old)
    raw.append({"fault": name, "actual_lifecycle": True})
    return make_fault_record(
        fault=name, injected_at_ns=injected, detected_at_ns=detected,
        safe_command_at_ns=safe_at, motion_stopped_at_ns=stopped,
        recovery_at_ns=recovered, state_evidence=state,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--body-port", type=int, required=True)
    parser.add_argument("--runtime-dir", type=Path, required=True)
    parser.add_argument("--pid-file", type=Path, required=True)
    parser.add_argument("--robotd", type=Path, required=True)
    parser.add_argument("--params", type=Path, required=True)
    parser.add_argument("--ort-dylib", type=Path, required=True)
    parser.add_argument("--duck-sim", type=Path, required=True)
    parser.add_argument("--microduck", type=Path, required=True)
    parser.add_argument("--microduck-rl", type=Path, required=True)
    parser.add_argument("--source-head", required=True)
    parser.add_argument("--raw-artifact", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-s", type=float, default=0.15)
    args = parser.parse_args()
    if not socket.gethostname().startswith("jetsonthor") or platform.python_version_tuple()[:2] != ("3", "12"):
        raise RuntimeError("P6-06 runtime authority requires Thor and Python 3.12")
    if re.fullmatch(r"[0-9a-f]{40}", args.source_head) is None:
        raise ValueError("source-head must be a full SHA")

    raw = []
    records = []
    session = Session(args, raw)
    try:
        for name in ("camera_dropout", "tof_dropout", "stale_perception", "invalid_perception", "compositor_invalid"):
            records.append(standard_fault(session, name, "missing", raw, perception=True))
        for name, mode in (
            ("runtime_unhealthy", "runtime_unhealthy"), ("neural_freeze", "stale_neural"),
            ("malformed_neural", "malformed_neural"), ("neural_unavailable", "missing"),
            ("decoder_crash", "decoder_crash"), ("decoder_stale", "stale_behavior"),
        ):
            records.append(standard_fault(session, name, mode, raw))

        # Explicit controller-side disconnect: motion cannot cross the generation boundary.
        old = session.motion(); injected = time.monotonic_ns(); session.client.disconnect()
        try: session.adapter.send(session.output(vyaw=0.2)); raise AssertionError("disconnect not detected")
        except (MotionAdapterError, RobotdConnectionError): detected = time.monotonic_ns()
        safe_at, state, stopped = reconnect_and_stop(session); recovered = session.recover(old)
        records.append(make_fault_record(fault="ipc_disconnect", injected_at_ns=injected, detected_at_ns=detected,
            safe_command_at_ns=safe_at, motion_stopped_at_ns=stopped, recovery_at_ns=recovered, state_evidence=state))

        # A real absent Unix endpoint must refuse; the active endpoint is then stopped safely.
        old = session.motion(); injected = time.monotonic_ns()
        try: RobotdClient(str(args.runtime_dir / "absent-p6-06.sock"), timeout_s=args.timeout_s).connect(); raise AssertionError("connection unexpectedly accepted")
        except RobotdConnectionError: detected = time.monotonic_ns()
        session.adapter.send(session.output(mode="missing")); safe_at = time.monotonic_ns(); state = session.safe_state(); stopped = time.monotonic_ns(); recovered = session.recover(old)
        records.append(make_fault_record(fault="connection_refused", injected_at_ns=injected, detected_at_ns=detected,
            safe_command_at_ns=safe_at, motion_stopped_at_ns=stopped, recovery_at_ns=recovered, state_evidence=state))

        # SIGSTOP is scoped to the verified robotd PID and causes an actual bounded read timeout.
        old = session.motion(); injected = time.monotonic_ns(); pid = verified_pid(args.pid_file, args.robotd, args.socket); os.kill(pid, signal.SIGSTOP)
        try:
            try: session.client.health(); raise AssertionError("read timeout not detected")
            except RobotdTimeoutError: detected = time.monotonic_ns()
        finally: os.kill(pid, signal.SIGCONT)
        safe_at, state, stopped = reconnect_and_stop(session); recovered = session.recover(old)
        records.append(make_fault_record(fault="read_timeout", injected_at_ns=injected, detected_at_ns=detected,
            safe_command_at_ns=safe_at, motion_stopped_at_ns=stopped, recovery_at_ns=recovered, state_evidence=state))

        def kill_current():
            pid = verified_pid(args.pid_file, args.robotd, args.socket)
            os.kill(pid, signal.SIGTERM)
            wait_for(lambda: process_exited(pid))
        for name in ("write_failure", "socket_close", "robotd_restart"):
            records.append(lifecycle_fault(session, name, args, raw, kill_current))

        # Full official simulator lifecycle. Old adapter/session survives to prove generation gating.
        old = session.motion(); injected = time.monotonic_ns()
        env = dict(os.environ)
        env.update({
            "DUCK_SIM_STATE": str(args.runtime_dir),
            "DUCK_SIM_RL": str(args.microduck_rl),
            "DUCK_SIM_PORT": str(args.body_port),
            "DUCK_SIM_VIEWER": "0",
        })
        down = subprocess.run([str(args.duck_sim), "down"], env=env, timeout=30, check=False, capture_output=True, text=True)
        if down.returncode != 0: raise RuntimeError(f"duck-sim down failed: {down.stderr}")
        try: session.client.health(); raise AssertionError("simulator restart loss not detected")
        except (RobotdConnectionError, RobotdTimeoutError): detected = time.monotonic_ns()
        up = subprocess.run([str(args.duck_sim)], env=env, timeout=120, check=False, capture_output=True, text=True)
        if up.returncode != 0: raise RuntimeError(f"duck-sim up failed: {up.stderr}")
        safe_at, state, stopped = reconnect_and_stop(session); recovered = session.recover(old)
        raw.append({"fault": "simulator_restart", "down_stdout": down.stdout[-1000:], "up_stdout": up.stdout[-1000:]})
        records.append(make_fault_record(fault="simulator_restart", injected_at_ns=injected, detected_at_ns=detected,
            safe_command_at_ns=safe_at, motion_stopped_at_ns=stopped, recovery_at_ns=recovered, state_evidence=state))
    finally:
        try: session.adapter.send(session.output(mode="missing"))
        except Exception: pass
        session.close()

    if [record["fault"] for record in records] != list(REQUIRED_FAULTS):
        raise AssertionError("runtime did not execute canonical complete fault set")
    args.raw_artifact.parent.mkdir(parents=True, exist_ok=True)
    args.raw_artifact.write_text("".join(json.dumps(item, sort_keys=True, allow_nan=False) + "\n" for item in raw), encoding="utf-8")
    raw_hash = hashlib.sha256(args.raw_artifact.read_bytes()).hexdigest()
    identities = {
        "microduck_commit": git_head(args.microduck), "microduck_rl_commit": git_head(args.microduck_rl),
        "steering_yaw_sign": -1, "stop_transport": "robot_stop",
        "perception_ttl_ms": 100, "neural_ttl_ms": 100, "behavior_ttl_ms": 100,
        "robotd_interface": "official JSON-RPC high-level intent",
        "fixture_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    matrix = build_fault_matrix(
        execution_target="Thor", source_head=args.source_head, identities=identities,
        records=records, artifact={"path": str(args.raw_artifact), "sha256": raw_hash, "record_count": len(raw)},
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_fault_matrix(args.output, matrix)
    print(json.dumps(matrix, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
