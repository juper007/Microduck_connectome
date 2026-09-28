"""Passive high-rate official SIT startup timeline for P8-03-R7.

No motion or correction is requested. The official duck-sim up command itself
enables the pinned robotd stand policy; this runner only observes that startup.
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
from scripts.p8_02_final_batch import probe_final_sim_state
from scripts.p8_03_r7_score import (
    EVENTS, body_pose_from_packet, derive_timeline, finite, health_phase, matrix,
    read_journal, score_root, settled_candidate, trial_metrics, verify_trial,
)

PINS = {"MicroDuck": "344925c9f8fa031f85428a305b1e8ec2eaae29c1",
        "microduck_rl": "cb70b792312d559a4da09064d92009079671815f",
        "python": "3.12.3",
        "policy_sha256": "98c3ea73fa6bb196bcf16586cf38b9fffb782787447d638fa1c1028df9082c1a",
        "graph_sha256": "c4160c42941163079b6b569d117bf67afcf8b45eaa128c444f7c96c2567593cc"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)


class Journal:
    """Thread-safe, append-only raw ledger; every row is durable on return."""

    def __init__(self, path: Path):
        self.file = path.open("x", encoding="utf-8")
        self.lock = threading.Lock()
        self.index = 0

    def add(self, kind: str, **fields) -> dict:
        with self.lock:
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


class FaultBox:
    def __init__(self):
        self.lock = threading.Lock()
        self.value = None

    def set(self, category: str, reason: str, source_index: int | None) -> None:
        with self.lock:
            if self.value is None:
                self.value = {"category": category, "reason": reason,
                              "source_sample_index": source_index,
                              "host_monotonic_ns": time.monotonic_ns()}


class BodyReader:
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
        raw_text = raw.decode("utf-8", errors="replace").rstrip("\n")
        try:
            pose = body_pose_from_packet(raw_text)
        except (ValueError, KeyError, TypeError, IndexError):
            pose = {key: None for key in (
                "sim_time_s", "x_m", "y_m", "trunk_z_m", "heading_rad",
                "roll_rad", "pitch_rad", "imu_quat_wxyz", "joint_positions",
                "joint_velocities", "currents_ma", "contact_or_gait")}
        return {"request_ns": request_ns, "response_ns": response_ns,
                "raw_body_packet": raw_text, **pose}

    def close(self) -> None:
        self.stream.close()
        self.sock.close()


def unix_connectable(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.settimeout(.005)
            return probe.connect_ex(str(path)) == 0
    except OSError:
        return False


def persist_notification(raw: bytes, journal: Journal,
                         faults: FaultBox) -> tuple[dict | None, dict, int]:
    """Durably store wire bytes before parsing or classifying a notification."""
    received_ns = time.monotonic_ns()
    raw_text = raw.decode("utf-8", errors="replace").rstrip("\n")
    raw_row = journal.add("robotd_raw_notification", received_ns=received_ns,
                          raw_line=raw_text)
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("robotd notification is not an object")
        return parsed, raw_row, received_ns
    except (ValueError, UnicodeDecodeError) as error:
        journal.add("robotd_malformed_notification",
                    raw_source_sample_index=raw_row["sample_index"],
                    raw_bytes_hex=raw.hex(), error=repr(error))
        faults.set("DATA_INTEGRITY_FAIL", "malformed_robotd_notification",
                   raw_row["sample_index"])
        return None, raw_row, received_ns


class StateSubscriber:
    """Dedicated read-only stream; persist every robot.state notification."""

    def __init__(self, sock_path: Path, journal: Journal, faults: FaultBox,
                 protocol: dict):
        self.journal, self.faults, self.protocol = journal, faults, protocol
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(2.)
        self.sock.connect(str(sock_path))
        self.stream = self.sock.makefile("rwb")
        self.stream.write(b'{"jsonrpc":"2.0","id":1,"method":"robot.subscribe","params":{"hz":50}}\n')
        self.stream.flush()
        self.latest = None
        self.state_index = 0
        self.error = None
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def _read(self) -> None:
        try:
            while not self.stop_event.is_set():
                raw = self.stream.readline()
                if not raw:
                    raise RuntimeError("robotd state stream closed")
                message, raw_row, received_ns = persist_notification(
                    raw, self.journal, self.faults)
                if message is None:
                    break
                if message.get("method") != "robot.state":
                    continue
                state = message["params"]
                row = self.journal.add("robotd_state", state_index=self.state_index,
                                       raw_notification_index=raw_row["sample_index"],
                                       raw_state_line=raw_row["raw_line"],
                                       state=state, received_ns=received_ns,
                                       robotd_t_ns=state.get("t_ns"))
                self.latest = row
                self.state_index += 1
                safety = state.get("safety", {})
                if safety.get("fallen") or safety.get("limp"):
                    self.faults.set("SAFETY_FAIL", "robotd_fallen_or_limp",
                                    row["sample_index"])
                applied = state.get("move", {}).get("applied")
                if (not isinstance(applied, list) or len(applied) != 3 or
                        not all(finite(v) for v in applied)):
                    self.faults.set("DATA_INTEGRITY_FAIL", "invalid_applied_twist",
                                    row["sample_index"])
                else:
                    limits = self.protocol["genuine_safety"]
                    for value, key in zip(applied, ("max_abs_vx_mps",
                                                    "max_abs_vy_mps",
                                                    "max_abs_vyaw_radps")):
                        if abs(value) > limits[key]:
                            self.faults.set("SAFETY_FAIL", "applied_twist_bound",
                                            row["sample_index"])
        except BaseException as error:
            if not self.stop_event.is_set():
                self.error = f"{type(error).__name__}: {error}"
                self.faults.set("INFRA_FAIL", "robotd_state_stream_error", None)

    def close(self) -> None:
        self.stop_event.set()
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.stream.close()
        self.sock.close()
        self.thread.join(timeout=.5)


def health_transition(health: dict, connected_ns: int, received_ns: int,
                      had_healthy_cycle: bool, protocol: dict
                      ) -> tuple[bool, tuple[str, str] | None]:
    phase = health_phase(health)
    if phase == "HEALTHY":
        return True, None
    if had_healthy_cycle:
        return True, ("SAFETY_FAIL", "robotd_unhealthy_after_cycle")
    if phase == "STARTUP_UNREADY":
        if received_ns-connected_ns > protocol["startup_unready_grace_s"]*1e9:
            return False, ("INFRA_FAIL", "startup_unready_timeout")
        return False, None
    if phase == "CONTRADICTORY_STARTUP_HEALTH":
        return False, ("DATA_INTEGRITY_FAIL", "contradictory_startup_health")
    return False, ("SAFETY_FAIL", "robotd_unhealthy")


class RobotdMonitor:
    """Health and connection worker, separate from the 50 Hz body read loop."""

    def __init__(self, sock: Path, journal: Journal, faults: FaultBox,
                 protocol: dict):
        self.sock, self.journal, self.faults = sock, journal, faults
        self.protocol = protocol
        self.stop_event = threading.Event()
        self.latest_health = None
        self.had_healthy_cycle = False
        self.subscriber = None
        self.reachable_row = None
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def _run(self) -> None:
        client = None
        try:
            while not self.stop_event.is_set() and client is None:
                if not unix_connectable(self.sock):
                    time.sleep(.01)
                    continue
                candidate = RobotdClient(str(self.sock), timeout_s=.2)
                try:
                    candidate.connect()
                    client = candidate
                except RuntimeError:
                    candidate.disconnect()
                    time.sleep(.01)
            if client is None:
                return
            connected_ns = time.monotonic_ns()
            self.reachable_row = self.journal.add("robotd_reachable",
                                                  socket_path=str(self.sock),
                                                  connected_ns=connected_ns)
            self.subscriber = StateSubscriber(self.sock, self.journal,
                                              self.faults, self.protocol)
            period = self.protocol["health_poll_period_s"]
            while not self.stop_event.is_set():
                try:
                    health = client.health()
                    received_ns = time.monotonic_ns()
                    row = self.journal.add("robotd_health", health=health,
                                           received_ns=received_ns)
                    self.latest_health = row
                    self.had_healthy_cycle, fault = health_transition(
                        health, connected_ns, received_ns,
                        self.had_healthy_cycle, self.protocol)
                    if fault:
                        self.faults.set(*fault, row["sample_index"])
                except RuntimeError as error:
                    row = self.journal.add("robotd_health_error", error=repr(error))
                    if self.latest_health is not None and (
                            row["host_monotonic_ns"] -
                            self.latest_health["host_monotonic_ns"] >
                            self.protocol["max_health_age_s"] * 1e9):
                        self.faults.set("INFRA_FAIL", "robotd_health_stale",
                                        row["sample_index"])
                time.sleep(period)
        except BaseException as error:
            if not self.stop_event.is_set():
                self.faults.set("INFRA_FAIL", f"robotd_monitor:{error}", None)
        finally:
            if self.subscriber:
                self.subscriber.close()
            if client:
                client.disconnect()

    def snapshot(self) -> tuple[dict | None, dict | None]:
        return ((self.subscriber.latest if self.subscriber else None),
                self.latest_health)

    def close(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=3.)
        if self.thread.is_alive():
            raise RuntimeError("robotd monitor did not stop")


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


def wait_body(port: int, deadline: float) -> BodyReader:
    while time.monotonic() < deadline:
        try:
            return BodyReader(port)
        except (OSError, TimeoutError, ValueError, json.JSONDecodeError):
            time.sleep(.01)
    raise TimeoutError("official body server not reachable")


def capture_body(reader: BodyReader, monitor: RobotdMonitor | None,
                 sock: Path, journal: Journal, index: int) -> dict:
    probe_start = time.monotonic_ns()
    socket_available = unix_connectable(sock)
    probe_end = time.monotonic_ns()
    pose = reader.read()
    state_row, health_row = monitor.snapshot() if monitor else (None, None)
    state = state_row["state"] if state_row else None
    row = journal.add("body_sample", body_index=index, pose=pose,
                      socket_probe_start_ns=probe_start,
                      socket_probe_end_ns=probe_end,
                      robotd_socket_available=socket_available,
                      snapshot_state_index=state_row["sample_index"] if state_row else None,
                      snapshot_state_age_s=(pose["response_ns"]-
                                            state_row["received_ns"])/1e9 if state_row else None,
                      snapshot_health_index=health_row["sample_index"] if health_row else None,
                      policy=state.get("policy") if state else None,
                      requested=state.get("move", {}).get("requested") if state else None,
                      applied=state.get("move", {}).get("applied") if state else None,
                      limited_by=state.get("move", {}).get("limited_by") if state else None,
                      safety=state.get("safety") if state else None,
                      health=health_row["health"] if health_row else None)
    return row


def body_fault(row: dict, previous: dict | None, last_advance_ns: int,
               protocol: dict) -> tuple[str, str] | None:
    pose = row["pose"]
    if not all(finite(pose.get(k)) for k in (
            "sim_time_s", "x_m", "y_m", "trunk_z_m", "heading_rad",
            "roll_rad", "pitch_rad")):
        return "DATA_INTEGRITY_FAIL", "malformed_body_pose"
    if not 0 <= (pose["response_ns"]-pose["request_ns"])/1e9 <= protocol["max_body_response_age_s"]:
        return "DATA_INTEGRITY_FAIL", "body_response_stale"
    if previous:
        if pose["response_ns"]-previous["pose"]["response_ns"] > protocol["max_body_gap_s"]*1e9:
            return "DATA_INTEGRITY_FAIL", "body_capture_gap"
        if pose["sim_time_s"] < previous["pose"]["sim_time_s"]:
            return "DATA_INTEGRITY_FAIL", "simulator_clock_reversed"
    if pose["response_ns"]-last_advance_ns > protocol["max_body_gap_s"]*1e9:
        return "DATA_INTEGRITY_FAIL", "simulator_clock_stalled"
    if max(abs(pose["roll_rad"]), abs(pose["pitch_rad"])) > protocol["genuine_safety"]["max_abs_roll_pitch_rad"]:
        return "SAFETY_FAIL", "body_attitude_bound"
    return None


def run_one(plan: dict, root: Path, protocol: dict, sim: Path,
            state_dir: Path, env: dict, port: int) -> dict:
    folder = root / plan["id"]
    folder.mkdir()
    journal = Journal(folder / "samples.jsonl")
    trace = {**plan, "result": "RUNNING", "move_count": 0,
             "single_attempt": True, "started_utc_ns": time.time_ns()}
    atomic_json(folder / "trace.json", trace)
    faults = FaultBox()
    sock = state_dir / "duck-a.sock"
    up = reader = monitor = log_thread = None
    body_rows = []
    up_exit_ns = None
    last_up_alive_poll_ns = None
    try:
        journal.add("reset_start", development_reset_id=plan["development_reset_id"])
        trace["down_before_exit"] = captured([str(sim), "down"], env,
                                              folder / "down-before.log")
        journal.add("official_down", exit=trace["down_before_exit"])
        if trace["down_before_exit"]:
            raise RuntimeError("official down failed")
        up = subprocess.Popen([str(sim), "up"], env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, bufsize=1)
        last_up_alive_poll_ns = time.monotonic_ns()
        journal.add("official_up_started", pid=up.pid)

        def pump_log() -> None:
            with (folder / "up.log").open("x", encoding="utf-8") as output:
                for line in up.stdout:
                    received_ns = time.monotonic_ns()
                    event = journal.add("process_log", line=line.rstrip("\n"),
                                        stream="official_up_combined",
                                        received_ns=received_ns)
                    output.write(f"{event['received_ns']} {line}")
                    output.flush()
                    os.fsync(output.fileno())

        log_thread = threading.Thread(target=pump_log, daemon=True)
        log_thread.start()
        deadline = time.monotonic() + protocol["startup_timeout_s"]
        reader = wait_body(port, deadline)
        reached_ns = time.monotonic_ns()
        journal.add("body_reachable", body_port=port, reached_ns=reached_ns)
        first = capture_body(reader, None, sock, journal, 0)
        body_rows.append(first)
        last_advance_ns = first["pose"]["response_ns"]
        problem = body_fault(first, None, last_advance_ns, protocol)
        if problem:
            faults.set(*problem, first["sample_index"])
        monitor = RobotdMonitor(sock, journal, faults, protocol)
        monitor.start()
        while faults.value is None:
            if time.monotonic() > deadline:
                faults.set("INFRA_FAIL", "official_up_timeout", None)
                break
            tick = time.monotonic()
            previous = body_rows[-1]
            row = capture_body(reader, monitor, sock, journal, len(body_rows))
            body_rows.append(row)
            if row["pose"]["sim_time_s"] is not None and (
                    row["pose"]["sim_time_s"] > previous["pose"]["sim_time_s"]):
                last_advance_ns = row["pose"]["response_ns"]
            problem = body_fault(row, previous, last_advance_ns, protocol)
            if problem:
                faults.set(*problem, row["sample_index"])
                break
            if (monitor.reachable_row is not None and
                    row["pose"]["response_ns"]-
                    monitor.reachable_row["connected_ns"] > int(.25e9)):
                state_row, health_row = monitor.snapshot()
                if (state_row is None or
                        row["pose"]["response_ns"]-state_row["received_ns"] >
                        protocol["max_robotd_state_age_s"]*1e9):
                    faults.set("DATA_INTEGRITY_FAIL", "robotd_state_stale",
                               row["sample_index"])
                    break
                if (health_row is None or
                        row["pose"]["response_ns"]-health_row["received_ns"] >
                        protocol["max_health_age_s"]*1e9):
                    faults.set("DATA_INTEGRITY_FAIL", "robotd_health_stale",
                               row["sample_index"])
                    break
            if up_exit_ns is None:
                status = up.poll()
                observed_poll_ns = time.monotonic_ns()
                if status is None:
                    last_up_alive_poll_ns = observed_poll_ns
                else:
                    trace["up_exit"] = status
                    up_row = journal.add("up_exit", exit=status, pid=up.pid,
                                         last_alive_poll_ns=last_up_alive_poll_ns,
                                         observed_exit_ns=observed_poll_ns)
                    up_exit_ns = observed_poll_ns
                    if status != 0:
                        faults.set("INFRA_FAIL", "official_up_nonzero_exit",
                                   up_row["sample_index"])
                        break
            if up_exit_ns is not None:
                elapsed = (row["pose"]["response_ns"]-up_exit_ns)/1e9
                if elapsed >= protocol["post_up_min_capture_s"]:
                    settled = settled_candidate(body_rows, up_exit_ns, protocol)
                    if settled is not None:
                        trace["capture_end_reason"] = "STAND_SETTLED"
                        journal.add("capture_end", reason="STAND_SETTLED",
                                    settled_source_sample_index=settled["sample_index"])
                        break
                if elapsed >= protocol["post_up_max_capture_s"]:
                    faults.set("DATA_INTEGRITY_FAIL", "stand_not_settled",
                               row["sample_index"])
                    break
            time.sleep(max(0., protocol["body_target_period_s"]-
                           (time.monotonic()-tick)))
        if faults.value is not None:
            trace["result"] = faults.value["category"]
            trace["trigger"] = faults.value
            journal.add("failure_event", trigger=faults.value)
            if trace["result"] == "SAFETY_FAIL" and unix_connectable(sock):
                trace["safety_stop"] = bounded_stop(sock)
                journal.add("safety_stop_ack", **trace["safety_stop"])
        else:
            trace["result"] = "OBSERVED"
    except BaseException as error:
        trace["error"] = f"{type(error).__name__}: {error}"
        if trace["result"] == "RUNNING":
            trace["result"] = "INFRA_FAIL"
    finally:
        if up is not None and up.poll() is None:
            up.terminate()
            try:
                up.wait(timeout=5)
            except subprocess.TimeoutExpired:
                up.kill()
                up.wait(timeout=5)
        if log_thread:
            log_thread.join(timeout=3.)
            if log_thread.is_alive():
                trace["log_thread_error"] = "official up log pump did not finish"
        if monitor:
            try:
                monitor.close()
            except BaseException as error:
                trace["monitor_close_error"] = repr(error)
        if reader:
            try:
                reader.close()
            except BaseException as error:
                trace["body_close_error"] = repr(error)
        if faults.value is not None and trace["result"] == "OBSERVED":
            trace["result"] = faults.value["category"]
            trace["trigger"] = faults.value
            journal.add("failure_event", trigger=faults.value)
        if trace["result"] == "OBSERVED":
            try:
                rows = read_journal(folder / "samples.jsonl")
                timeline = derive_timeline(rows, protocol)
                for name in EVENTS:
                    journal.add("timeline_event", name=name, event=timeline[name])
                rows = read_journal(folder / "samples.jsonl")
                trace["metrics"] = trial_metrics(rows, protocol)
            except BaseException as error:
                trace["result"] = "DATA_INTEGRITY_FAIL"
                trace["analysis_error"] = f"{type(error).__name__}: {error}"
        for log_name in ("body.log", "duck-a.log"):
            source = state_dir / log_name
            try:
                if source.is_file():
                    destination = folder / f"official-{log_name}"
                    shutil.copyfile(source, destination)
                    journal.add("daemon_log_snapshot", source=log_name,
                                available=True, captured_ns=time.monotonic_ns(),
                                sha256=sha(destination), bytes=destination.stat().st_size)
                else:
                    journal.add("daemon_log_snapshot", source=log_name,
                                available=False, captured_ns=time.monotonic_ns())
            except BaseException as error:
                trace.setdefault("daemon_log_errors", []).append(repr(error))
        trace["cleanup_stop"] = bounded_stop(sock)
        try:
            trace["down_after_exit"] = captured([str(sim), "down"], env,
                                                  folder / "down-after.log")
        except BaseException as error:
            trace["down_after_exit"] = None
            trace["down_after_error"] = repr(error)
        trace["final_probe"] = probe_final_sim_state(state_dir, port)
        if (trace["cleanup_stop"]["result"] != "PASS" or
                trace["down_after_exit"] != 0 or
                trace["final_probe"]["result"] != "PASS" or
                trace.get("monitor_close_error") or trace.get("body_close_error") or
                trace.get("log_thread_error") or trace.get("daemon_log_errors")):
            if trace["result"] != "SAFETY_FAIL":
                trace["result"] = "INFRA_FAIL"
        trace["completed_utc_ns"] = time.time_ns()
        journal.add("cleanup", stop=trace["cleanup_stop"],
                    down_exit=trace["down_after_exit"],
                    final_probe=trace["final_probe"])
        journal.close()
        atomic_json(folder / "trace.json", trace)
        if trace["result"] == "OBSERVED":
            rows = read_journal(folder / "samples.jsonl")
            good, reason = verify_trial(trace, plan, rows, protocol)
            if not good:
                trace["result"] = "DATA_INTEGRITY_FAIL"
                trace["validation_error"] = reason
                atomic_json(folder / "trace.json", trace)
    return trace


def manifest(root: Path) -> dict:
    files = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name not in ("manifest.json", "gate.json"):
            raw = path.read_bytes()
            files.append({"path": path.relative_to(root).as_posix(),
                          "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                          "record_count": len(raw.splitlines())})
    return {"schema_version": "p8-03-r7-manifest-v3", "files": files}


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
    protocol = json.loads(args.protocol.read_text())
    planned = matrix(protocol)
    if args.evidence_root.exists():
        raise RuntimeError("single-use R7 evidence root already exists")
    source_root = Path(__file__).resolve().parents[1]
    args.evidence_root.mkdir(parents=True)
    for name, source in (("protocol.json", args.protocol),
                         ("runner.py", Path(__file__)),
                         ("scorer.py", Path(__file__).with_name("p8_03_r7_score.py"))):
        shutil.copyfile(source, args.evidence_root / name)
    preflight = {"reviewed_head": args.reviewed_head,
                 "source_head": subprocess.check_output(
                     ["git", "-C", str(source_root), "rev-parse", "HEAD"],
                     text=True).strip(),
                 "source_status": subprocess.check_output(
                     ["git", "-C", str(source_root), "status", "--porcelain"],
                     text=True).strip(),
                 "microduck_head": subprocess.check_output(
                     ["git", "-C", str(args.microduck), "rev-parse", "HEAD"],
                     text=True).strip(),
                 "microduck_rl_head": subprocess.check_output(
                     ["git", "-C", str(args.microduck_rl), "rev-parse", "HEAD"],
                     text=True).strip(),
                 "policy_sha256": sha(args.policy), "graph_sha256": sha(args.graph),
                 "python": sys.version.split()[0],
                 "initial_sim_probe": probe_final_sim_state(
                     args.sim_state, args.body_port, phase="r7_preflight")}
    preflight["result"] = "PASS" if (
        preflight["source_head"] == args.reviewed_head and
        not preflight["source_status"] and
        preflight["microduck_head"] == PINS["MicroDuck"] and
        preflight["microduck_rl_head"] == PINS["microduck_rl"] and
        preflight["policy_sha256"] == PINS["policy_sha256"] and
        preflight["graph_sha256"] == PINS["graph_sha256"] and
        preflight["python"] == PINS["python"] and
        preflight["initial_sim_probe"]["result"] == "PASS") else "FAIL"
    atomic_json(args.evidence_root / "preflight.json", preflight)
    env = os.environ.copy()
    env.update(DUCK_SIM_VIEWER="0", DUCK_SIM_STATE=str(args.sim_state),
               DUCK_SIM_KEYFRAME="SIT", DUCK_SIM_RL=str(args.microduck_rl),
               DUCK_SIM_PORT=str(args.body_port), PYTHONPATH=str(source_root))
    env["PATH"] = (str(args.microduck.parent /
                       "rustup/toolchains/stable-aarch64-unknown-linux-gnu/bin") +
                   os.pathsep + env["PATH"])
    records = []
    if preflight["result"] == "PASS":
        for plan in planned:
            row = run_one(plan, args.evidence_root, protocol,
                          args.microduck / "scripts/duck-sim", args.sim_state,
                          env, args.body_port)
            records.append(row)
            atomic_json(args.evidence_root / "run.json", {
                "planned": len(planned), "attempted": len(records),
                "last_result": row["result"]})
            if row["result"] != "OBSERVED":
                break
    else:
        atomic_json(args.evidence_root / "run.json", {
            "planned": len(planned), "attempted": 0,
            "last_result": "PREFLIGHT_FAIL"})
    atomic_json(args.evidence_root / "manifest.json", manifest(args.evidence_root))
    gate = score_root(args.evidence_root)
    atomic_json(args.evidence_root / "gate.json", gate)
    print(json.dumps({"result": gate["result"], "attempted": gate["attempted"],
                      "valid_resets": gate["valid_resets"]}))
    return 0 if gate["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
