"""Separate V2.4 healthy handoff and injected-fault gates; no official seeds."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

from microduck_connectome.control_contracts import make_behavior_intent
from microduck_connectome.fault_stop import FaultStopLatch
from microduck_connectome.motion_adapter import RobotMotionAdapter
from microduck_connectome.neural_stop_arbiter import NeuralStopMotionArbiter
from microduck_connectome.neural_stop_scheduler import NeuralStopRefreshScheduler
from microduck_connectome.perception_frame import make_perception_frame
from microduck_connectome.scheduler import NeuralUpdate, SchedulerError
from microduck_connectome.watchdog import ControllerWatchdog
from scripts.p8_r3_official_trial import VisualCadence


ROOT = Path(__file__).resolve().parents[1]
BASE = 1_000_000_000
PERIOD_NS = 20_000_000
TTL_NS = 100_000_000
GROUP_A = ("normal_handoff", "real_worker_start_and_stop_refresh")
GROUP_B = ("missing_prime", "invalid_prime", "future_prime", "stale_prime",
           "malformed_prime", "nan_prime", "delayed_start",
           "visual_drop_stale_neural_persistence", "fault_supersedes_neural_stop")
_ACTIVE_CASE = None


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def committed_bytes(relative: str) -> bytes:
    return subprocess.check_output(["git", "show", "HEAD:" + relative], cwd=ROOT)


def file_identity(relative: str) -> dict:
    execution = (ROOT / relative).read_bytes()
    committed = committed_bytes(relative)
    return {
        "execution_sha256": hashlib.sha256(execution).hexdigest(),
        "committed_sha256": hashlib.sha256(committed).hexdigest(),
        "normalized_execution_equals_committed":
            execution.replace(b"\r\n", b"\n") == committed,
    }


def frame(now_ns: int, frame_id: int = 1, *, valid: bool = True) -> dict:
    return make_perception_frame(timestamp_ns=now_ns, frame_id=frame_id, valid=valid)


class FakeRobotd:
    """Records acknowledged high-level requests without a simulator."""

    def __init__(self, events: list[dict], *, real_time: bool = False):
        self.status = SimpleNamespace(connected=True, generation=1)
        self.events = events
        self.real_time = real_time

    def _send_watchdog(self, output, transport):
        intent = output["intent"]
        call_ns = time.monotonic_ns() if self.real_time else intent["timestamp_ns"]
        action = "robot.stop" if intent["stop"] else "robot.move"
        ack_ns = time.monotonic_ns() if self.real_time else call_ns + 1_000_000
        self.events.append({"kind": "command_ack", "call_ns": call_ns,
                            "ack_ns": ack_ns, "action": action,
                            "vx": intent["vx"], "watchdog_state": output["watchdog_state"],
                            "stale_reason": output["stale_reason"],
                            "intent_timestamp_ns": intent["timestamp_ns"]})
        return "robot_stop_refreshed" if intent["stop"] else "robot_move_ack"


class Case:
    def __init__(self, *, real_time: bool = False, stop_on_sequence: int | None = None):
        global _ACTIVE_CASE
        _ACTIVE_CASE = self
        self.events: list[dict] = []
        self.fault = FaultStopLatch()
        self.arbiter = NeuralStopMotionArbiter()
        self.watchdog = ControllerWatchdog(ROOT / "config/watchdog_v1.json")
        self.adapter = RobotMotionAdapter(FakeRobotd(self.events, real_time=real_time),
                                          ROOT / "config/motion_adapter_v1.json")
        self.cadence = VisualCadence(20)
        self.frame_id = 0
        self.neural_sequence = 0
        self.drop_visual = False
        self.stop_on_sequence = stop_on_sequence
        self.scheduler = NeuralStopRefreshScheduler(
            fault_latch=self.fault, motion_arbiter=self.arbiter,
            config=ROOT / "config/p8_r3_visual_scheduler_v1.json",
            watchdog=self.watchdog, perception_step=self.visual,
            neural_step=lambda sample, now_ns: self.arbiter.neural_step(
                lambda: self.neural(sample, now_ns)), publisher=self.adapter.send,
            control_observer=self.control_observer,
        )

    def visual(self, now_ns: int):
        if not self.cadence.due(now_ns):
            self.events.append({"kind": "visual_not_due", "timestamp_ns": now_ns})
            return None
        if self.drop_visual:
            self.events.append({"kind": "visual_dropped", "timestamp_ns": now_ns})
            return None
        self.frame_id += 1
        sample = frame(now_ns, self.frame_id)
        self.events.append({"kind": "visual_frame", "timestamp_ns": now_ns,
                            "source_ns": sample["timestamp_ns"],
                            "frame_id": sample["frame_id"],
                            "scheduled_due_ns": self.cadence.last_due_ns})
        return sample

    def neural(self, sample, now_ns: int):
        self.events.append({"kind": "neural_input", "timestamp_ns": now_ns,
                            "input_none": sample is None,
                            "frame_id": sample["frame_id"] if sample else None,
                            "source_ns": sample["timestamp_ns"] if sample else None,
                            "age_ns": now_ns - sample["timestamp_ns"] if sample else None,
                            "valid": sample["valid"] if sample else None})
        if sample is None:
            return None
        self.neural_sequence += 1
        stop = (self.stop_on_sequence is not None
                and self.neural_sequence >= self.stop_on_sequence)
        update = NeuralUpdate(
            {"timestamp_ns": now_ns, "sequence": self.neural_sequence,
             "steering_left": 0.0, "steering_right": 0.0,
             "escape": 1.0 if stop else 0.0, "runtime_healthy": True},
            make_behavior_intent(timestamp_ns=now_ns, sequence=self.neural_sequence,
                                 stop=stop, confidence=1.0 if stop else 0.0),
            {"neural_stop_latch": {"source": "healthy_neural_escape"}} if stop else None,
        )
        self.events.append({"kind": "neural_update", "timestamp_ns": now_ns,
                            "sequence": self.neural_sequence, "runtime_healthy": True,
                            "stop": stop})
        return update

    def control_observer(self, update, output, transport):
        self.events.append({"kind": "control", "timestamp_ns": output["intent"]["timestamp_ns"],
                            "update_none": update is None,
                            "stop": output["intent"]["stop"],
                            "watchdog_state": output["watchdog_state"],
                            "stale_reason": output["stale_reason"],
                            "transport": transport})

    def prime(self, *, source_ns: int = BASE, cache_at_ns: int | None = None):
        if cache_at_ns is None:
            cache_at_ns = source_ns + 5_000_000 if source_ns == BASE else time.monotonic_ns()
        first = self.visual(source_ns)
        direct = self.arbiter.neural_step(lambda: self.neural(first, source_ns))
        require(direct is not None and self.neural_sequence == 1,
                "direct neutral graph priming must run exactly once")
        require(self.watchdog.observe_neural(direct.readout),
                "watchdog rejected direct neural priming")
        require(self.watchdog.observe_behavior(direct.behavior_intent),
                "watchdog rejected direct behavior priming")
        cached = self.scheduler.prime_perception(first, now_ns=cache_at_ns)
        require(cached == first, "cache changed direct priming frame")
        require(not any(row["kind"] == "command_ack" for row in self.events),
                "priming sent a robot-facing command")
        self.events.append({"kind": "cache_prime", "timestamp_ns": cache_at_ns,
                            "frame_id": cached["frame_id"],
                            "source_ns": cached["timestamp_ns"]})
        return first

    def tick(self, offset_ms: int):
        now_ns = BASE + offset_ms * 1_000_000
        self.scheduler._perception_tick(now_ns)
        self.scheduler._neural_tick(now_ns)
        self.scheduler._control_tick(now_ns)


def require(condition: bool, message: str):
    if not condition:
        raise AssertionError(message)


def result(case: Case, name: str) -> dict:
    fault = case.fault.snapshot()
    neural = [row for row in case.events if row["kind"] == "neural_input"]
    armed = neural[1:] if any(row["kind"] == "cache_prime" for row in case.events) else []
    frames = [row for row in case.events if row["kind"] == "visual_frame"]
    commands = [row for row in case.events if row["kind"] == "command_ack"]
    ages = [row["age_ns"] / 1e6 for row in armed if row["age_ns"] is not None]
    frame_gaps = [(b["source_ns"] - a["source_ns"]) / 1e6
                  for a, b in zip(frames, frames[1:])]
    first_stop = next((index for index, row in enumerate(commands)
                       if row["action"] == "robot.stop"), None)
    post_stop = commands[first_stop:] if first_stop is not None else []
    first_invalid = next((row["timestamp_ns"] for row in armed
                          if row["input_none"] or row["age_ns"] is None
                          or row["valid"] is False), None)
    first_fault = next((row["timestamp_ns"] for row in case.events
                        if row["kind"] == "control"
                        and row["watchdog_state"] == "safe_stop"), None)
    ack_gaps = [(b["ack_ns"] - a["ack_ns"]) / 1e6
                for a, b in zip(post_stop, post_stop[1:])]
    return {"name": name, "result": "PASS", "events": case.events,
            "metrics": {"armed_neural_ticks": len(armed),
                        "armed_missing_count": sum(row["input_none"]
                                                    or row["age_ns"] is None for row in armed),
                        "armed_invalid_count": sum(row["valid"] is False for row in armed),
                        "armed_age_ms": ages, "frame_gaps_ms": frame_gaps,
                        "first_invalid_neural_ns": first_invalid,
                        "first_fault_control_ns": first_fault,
                        "stop_ack_gaps_ms": ack_gaps,
                        "post_stop_positive_moves": sum(
                            row["action"] == "robot.move"
                            for row in post_stop),
                        "command_ack_count": len(commands)},
            "fault_latch": asdict(fault) if fault is not None else None,
            "arbiter_latch_reason": case.arbiter.latch_reason,
            "watchdog_stop_reason": case.arbiter.watchdog_stop_reason,
            "dropped_neural": case.scheduler._metrics.dropped_neural,
            "scheduler_exceptions": case.scheduler._metrics.scheduler_exceptions}


def normal_case() -> dict:
    case = Case()
    first = case.prime()
    for offset in range(20, 221, 20):
        case.tick(offset)
    neural = [row for row in case.events if row["kind"] == "neural_input"]
    armed = neural[1:]
    visual = [row for row in case.events if row["kind"] == "visual_frame"]
    require(len(neural) == 12 and len(armed) == 11, "wrong graph step count")
    require(all(not row["input_none"] and row["valid"] and row["age_ns"] is not None
                and 0 <= row["age_ns"] <= TTL_NS for row in armed),
            "armed neural input was missing, invalid, or stale")
    require(armed[0]["frame_id"] == first["frame_id"]
            and armed[0]["source_ns"] == first["timestamp_ns"],
            "first scheduler step did not use original priming frame")
    require(any(row["frame_id"] > first["frame_id"] for row in armed),
            "ordinary visual frame did not replace primed cache")
    require(max(b["source_ns"] - a["source_ns"] for a, b in zip(visual, visual[1:]))
            <= TTL_NS, "visual gap exceeded TTL")
    require(case.scheduler._metrics.dropped_neural == 0
            and case.scheduler._metrics.scheduler_exceptions == 0,
            "scheduler dropped neural or raised")
    return result(case, "normal_handoff")


def real_worker_start_case() -> dict:
    case = Case(real_time=True, stop_on_sequence=5)
    source_ns = time.monotonic_ns()
    first = case.prime(source_ns=source_ns)
    require(case.neural_sequence == 1, "direct priming must be exactly one graph step")
    require(not any(row["kind"] == "command_ack" for row in case.events),
            "cache priming issued a robot-facing command")
    timer = threading.Timer(0.32, case.scheduler.request_complete)
    timer.start()
    try:
        summary = case.scheduler.run(0.6)
    finally:
        timer.cancel()
        timer.join(timeout=1.0)
    neural = [row for row in case.events if row["kind"] == "neural_input"]
    armed = neural[1:]
    visual = [row for row in case.events if row["kind"] == "visual_frame"]
    controls = [row for row in case.events if row["kind"] == "control"]
    commands = [row for row in case.events if row["kind"] == "command_ack"]
    require(armed and len(armed) == case.neural_sequence - 1,
            "real scheduler skipped or duplicated an armed graph step")
    require(all(not row["input_none"] and row["valid"] and row["age_ns"] is not None
                and 0 <= row["age_ns"] <= TTL_NS for row in armed),
            "real worker had missing, invalid, or stale frame")
    require(armed[0]["source_ns"] == first["timestamp_ns"]
            and armed[0]["frame_id"] == first["frame_id"],
            "first real worker tick did not use primed source")
    require(any(row["frame_id"] > first["frame_id"] for row in armed),
            "real visual worker never replaced primed frame")
    require(len(visual) >= 3 and max(b["source_ns"] - a["source_ns"]
                                     for a, b in zip(visual, visual[1:])) <= TTL_NS,
            "real visual frame gap exceeded 100 ms")
    require(controls and commands and min(row["call_ns"] for row in commands)
            >= controls[0]["timestamp_ns"], "robot-facing command preceded first control")
    require(summary["dropped_neural"] == 0 and summary["scheduler_exceptions"] == 0,
            "real workers dropped neural input or raised")
    first_stop = next(i for i, row in enumerate(commands) if row["action"] == "robot.stop")
    post = commands[first_stop:]
    gaps = [(b["ack_ns"] - a["ack_ns"]) / 1e6 for a, b in zip(post, post[1:])]
    require(len(post) >= 3 and all(row["action"] == "robot.stop" and row["vx"] == 0.0
                                   for row in post),
            "real worker resumed movement or lacked stop refresh")
    require(gaps and max(gaps) <= 100, "real worker stop ACK gap exceeded 100 ms")
    require(case.arbiter.latch_reason == "healthy_neural_escape",
            "real worker lost healthy neural stop source")
    record = result(case, "real_worker_start_and_stop_refresh")
    record["scheduler_summary"] = summary
    record["stop_ack_gaps_ms"] = gaps
    return record


def rejection_case(name: str, sample, now_ns: int) -> dict:
    case = Case()
    attempted_source = sample.get("timestamp_ns") if isinstance(sample, dict) else None
    case.events.append({"kind": "prime_attempt", "timestamp_ns": now_ns,
                        "source_ns": attempted_source,
                        "frame_id": sample.get("frame_id") if isinstance(sample, dict) else None})
    try:
        case.scheduler.prime_perception(sample, now_ns=now_ns)
    except SchedulerError as error:
        case.events.append({"kind": "prime_rejected", "timestamp_ns": now_ns,
                            "source_ns": attempted_source, "reason": str(error)})
    else:
        raise AssertionError(f"{name} priming was accepted")
    require(case.scheduler._perception.get()[2] == 0, "invalid frame entered cache")
    require(not any(row["kind"] == "command_ack" for row in case.events),
            "invalid priming published a robot-facing command")
    return result(case, name + "_prime")


def delayed_start_case() -> dict:
    case = Case()
    case.prime()
    case.scheduler.clock_ns = lambda: BASE + TTL_NS
    try:
        case.scheduler.run(0.01)
    except SchedulerError as error:
        case.events.append({"kind": "run_rejected", "timestamp_ns": BASE + TTL_NS,
                            "reason": str(error)})
    else:
        raise AssertionError("expired cache started scheduler")
    require(not case.scheduler._threads, "workers started with expired cache")
    require(not any(row["kind"] == "command_ack" for row in case.events),
            "delayed start published a robot-facing command")
    return result(case, "delayed_start")


def fault_case() -> dict:
    case = Case()
    case.prime()
    case.drop_visual = True
    for offset in range(20, 241, 20):
        case.tick(offset)
    require(case.scheduler._metrics.dropped_neural >= 1,
            "lost visual frame did not expire original source timestamp")
    require(case.arbiter.latch_reason == "fault_stale_neural",
            "stale neural fault did not latch")
    case.drop_visual = False
    for offset in range(260, 341, 20):
        case.tick(offset)
    commands = [row for row in case.events if row["kind"] == "command_ack"]
    first_stop = next(i for i, row in enumerate(commands) if row["action"] == "robot.stop")
    post = commands[first_stop:]
    require(all(row["action"] == "robot.stop" and row["vx"] == 0.0 for row in post),
            "positive command resumed after stop latch")
    require(all(b["ack_ns"] - a["ack_ns"] == PERIOD_NS for a, b in zip(post, post[1:])),
            "stop ACK refresh was not 50 Hz")
    require(case.scheduler._metrics.scheduler_exceptions == 0,
            "scheduler exception on stale-neural recovery")
    case.events.append({"kind": "fault_provenance", "timestamp_ns": BASE + 340_000_000,
                        "fault_latch": asdict(case.fault.snapshot())
                        if case.fault.snapshot() else None,
                        "arbiter_latch_reason": case.arbiter.latch_reason})
    return result(case, "visual_drop_stale_neural_persistence")


def fault_priority_case() -> dict:
    case = Case()
    case.prime()
    stop_ns = BASE + PERIOD_NS
    update = NeuralUpdate(
        {"timestamp_ns": stop_ns, "sequence": 2,
         "steering_left": 0.0, "steering_right": 0.0,
         "escape": 1.0, "runtime_healthy": True},
        make_behavior_intent(timestamp_ns=stop_ns, sequence=2, stop=True,
                             confidence=1.0),
        {"neural_stop_latch": {"source": "healthy_neural_escape"}},
    )
    case.arbiter.neural_step(lambda: update)
    case.scheduler._neural.put(update, stop_ns)
    case.events.append({"kind": "healthy_neural_stop_candidate",
                        "timestamp_ns": stop_ns, "sequence": 2})
    case.scheduler._control_tick(stop_ns)
    require(case.arbiter.latch_reason == "healthy_neural_escape",
            "healthy neural stop was not latched")
    case.fault.latch("camera_loss", detected_ns=BASE + 40_000_000, planned=True)
    case.events.append({"kind": "fault_latched", "timestamp_ns": BASE + 40_000_000,
                        "fault_latch": asdict(case.fault.snapshot())})
    for offset in (40, 60, 80):
        case.scheduler._control_tick(BASE + offset * 1_000_000)
    commands = [row for row in case.events if row["kind"] == "command_ack"]
    require(case.arbiter.latch_reason == "fault_camera_loss", "fault priority lost")
    require(all(row["action"] == "robot.stop" for row in commands),
            "non-stop after fault latch")
    require(all(b["ack_ns"] - a["ack_ns"] == PERIOD_NS
                for a, b in zip(commands, commands[1:])),
            "fault stop ACK refresh was not 50 Hz")
    return result(case, "fault_supersedes_neural_stop")


def run_case(name: str, run) -> dict:
    global _ACTIVE_CASE
    _ACTIVE_CASE = None
    try:
        row = run()
        require(row["name"] == name, "case returned wrong frozen name")
        return row
    except Exception as error:
        row = (result(_ACTIVE_CASE, name) if _ACTIVE_CASE is not None
               else {"name": name, "events": [], "metrics": {}})
        row["result"] = "FAIL"
        row["failure"] = f"{type(error).__name__}: {error}"
        return row


def group_results(cases: list[dict]) -> tuple[dict, dict]:
    by_name = {row["name"]: row for row in cases}
    healthy = [by_name[name] for name in GROUP_A]
    injected = [by_name[name] for name in GROUP_B]
    def metric(row, key, default=None):
        return row.get("metrics", {}).get(key, default)

    healthy_pass = all(
        row["result"] == "PASS"
        and metric(row, "armed_neural_ticks", 0) > 0
        and metric(row, "armed_missing_count", -1) == 0
        and metric(row, "armed_invalid_count", -1) == 0
        and len(metric(row, "armed_age_ms", []))
            == metric(row, "armed_neural_ticks")
        and all(0 <= age <= 100 for age in metric(row, "armed_age_ms", []))
        and all(gap <= 100 for gap in metric(row, "frame_gaps_ms", []))
        and row.get("scheduler_exceptions") == 0
        for row in healthy)
    drop = by_name["visual_drop_stale_neural_persistence"]
    injected_pass = (all(row["result"] == "PASS" for row in injected)
                     and metric(drop, "armed_missing_count", 0) > 0
                     and metric(drop, "first_invalid_neural_ns") is not None
                     and metric(drop, "first_fault_control_ns") is not None
                     and all(metric(row, "post_stop_positive_moves", -1) == 0
                             and row.get("scheduler_exceptions") == 0 for row in injected)
                     and all(metric(row, "command_ack_count", -1) == 0
                             for row in injected[:7]))
    return (
        {"group": "A_healthy_startup", "planned": 2,
         "passed": sum(row["result"] == "PASS" for row in healthy),
         "healthy_missing_count": sum(metric(row, "armed_missing_count", 0)
                                      for row in healthy),
         "result": "PASS" if healthy_pass else "FAIL", "case_names": list(GROUP_A)},
        {"group": "B_intentional_fault", "planned": 9,
         "passed": sum(row["result"] == "PASS" for row in injected),
         "injected_missing_count": metric(drop, "armed_missing_count", 0),
         "result": "PASS" if injected_pass else "FAIL", "case_names": list(GROUP_B)},
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise RuntimeError("startup gate raw output path must be unused")
    if subprocess.run(["git", "diff", "--quiet", "HEAD", "--"],
                      cwd=ROOT, check=False).returncode != 0:
        raise RuntimeError("startup gate requires clean tracked source")
    source_paths = (
        "scripts/p8_r3_v24_startup_gate.py",
        "microduck_connectome/neural_stop_scheduler.py",
        "microduck_connectome/neural_stop_arbiter.py",
        "scripts/p8_r3_official_trial.py",
        "microduck_connectome/watchdog.py",
        "microduck_connectome/motion_adapter.py",
    )
    source_hashes = {path: file_identity(path) for path in source_paths}
    if not all(row["normalized_execution_equals_committed"]
               for row in source_hashes.values()):
        raise RuntimeError("startup gate executing source differs from committed bytes")
    planned = (
        ("normal_handoff", normal_case),
        ("real_worker_start_and_stop_refresh", real_worker_start_case),
        ("missing_prime", lambda: rejection_case("missing", None, BASE)),
        ("invalid_prime", lambda: rejection_case(
            "invalid", frame(BASE, valid=False), BASE)),
        ("future_prime", lambda: rejection_case("future", frame(BASE + 1), BASE)),
        ("stale_prime", lambda: rejection_case(
            "stale", frame(BASE), BASE + TTL_NS + 1)),
        ("malformed_prime", lambda: rejection_case(
            "malformed", {"timestamp_ns": BASE, "frame_id": -1}, BASE)),
        ("nan_prime", lambda: rejection_case(
            "nan", {**frame(BASE), "looming": float("nan")}, BASE)),
        ("delayed_start", delayed_start_case),
        ("visual_drop_stale_neural_persistence", fault_case),
        ("fault_supersedes_neural_stop", fault_priority_case),
    )
    cases = [run_case(name, run) for name, run in planned]
    group_a, group_b = group_results(cases)
    overall = "PASS" if group_a["result"] == group_b["result"] == "PASS" else "FAIL"
    source_head = subprocess.check_output(["git", "rev-parse", "HEAD"],
                                          cwd=ROOT, text=True).strip()
    report = {
        "schema_version": "p8-r3-v24-startup-gate-v1", "result": overall,
        "group_a": group_a, "group_b": group_b,
        "scope": "separate healthy zero-skip startup and deliberate fault safety; local or Thor threaded scheduler plus deterministic ticks, fake robotd ACKs, no simulator or official seed",
        "source_head": source_head, "hostname": platform.node(),
        "python_version": platform.python_version(), "cases": cases,
        "source_hashes": source_hashes,
        "config_hashes": {name: file_identity("config/" + name) for name in (
            "p8_r3_visual_scheduler_v1.json", "watchdog_v1.json",
            "motion_adapter_v1.json")},
        "limits": ["manual cases use deterministic 20 ms ticks and 1 ms fake ACK latency",
                   "threaded case measures wall-clock scheduler and immediate fake ACKs",
                   "no official robotd, MuJoCo, or pose-derived robot evidence"],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, sort_keys=True, indent=2,
                                      allow_nan=False) + "\n", encoding="utf-8",
                           newline="\n")
    print(json.dumps({"result": overall, "group_a": group_a["result"],
                      "group_b": group_b["result"], "cases": len(cases),
                      "sha256": sha(args.output)}, sort_keys=True))
    if overall != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
