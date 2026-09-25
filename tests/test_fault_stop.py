"""Deterministic fault-latch and authentic stop-refresh component checks."""

import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from microduck_connectome.control_contracts import make_behavior_intent
from microduck_connectome.fault_stop import (
    FaultAwareInputs, FaultStopLatch, FaultStopRefreshScheduler, PlannedFault,
)
from microduck_connectome.motion_adapter import RobotMotionAdapter
from microduck_connectome.perception_frame import make_perception_frame
from microduck_connectome.safety_clamp import SafetyClamp, load_safety_envelope
from microduck_connectome.scheduler import NeuralUpdate, SchedulerWorkerError
from microduck_connectome.watchdog import ControllerWatchdog


ROOT = Path(__file__).resolve().parents[1]


class FakeRobotd:
    def __init__(self):
        self.status = SimpleNamespace(connected=True, generation=1)
        self.calls = []

    def _send_watchdog(self, output, stop_transport):
        intent = output["intent"]
        assert stop_transport == "robot_stop"
        self.calls.append((time.monotonic_ns(), dict(intent), output["stale_reason"]))
        return "robot_stop_refreshed" if intent["stop"] else "move"


def fixture():
    latch = FaultStopLatch()
    watchdog = ControllerWatchdog(ROOT / "config/watchdog_v1.json")
    robot = FakeRobotd()
    adapter = RobotMotionAdapter(robot, ROOT / "config/motion_adapter_v1.json")
    return latch, watchdog, robot, adapter


def check_latch_is_first_fault_wins_and_retains_last_healthy_timestamps():
    latch = FaultStopLatch()
    latch.observe_healthy("sensor", 10)
    latch.observe_healthy("neural", 20)
    first = latch.latch("tof_loss", detected_ns=30, planned=True)
    assert latch.latch("camera_loss", detected_ns=40, planned=True) is first
    latch.observe_healthy("sensor", 50)
    assert latch.snapshot().reason == "tof_loss"
    assert (first.last_healthy_sensor_ns, first.last_healthy_neural_ns) == (10, 20)


def check_planned_sensor_fault_latches_and_cannot_be_cleared(reason):
    latch = FaultStopLatch()
    now = 1_000_000_000
    healthy = make_perception_frame(timestamp_ns=now, frame_id=1)
    calls = 0

    def sensor(_now):
        nonlocal calls
        calls += 1
        if calls == 1:
            return healthy
        if reason == "malformed_perception":
            return {**healthy, "frame_id": -1}
        if reason == "nan_feature":
            return {**healthy, "looming": float("nan")}
        if reason == "inf_feature":
            return {**healthy, "looming": float("inf")}
        if reason == "camera_stale":
            return {**healthy, "frame_id": 2}
        return {**healthy, "timestamp_ns": now + 20_000_000,
                "frame_id": 2, "valid": False}

    source_reason = (lambda frame: reason if not frame["valid"] else None)
    wrapper = FaultAwareInputs(
        fault_latch=latch, started_ns=now, perception_step=sensor,
        neural_step=lambda frame, stamp: None, source_fault_reason=source_reason,
    )
    assert wrapper.perception(now) is not None
    assert wrapper.perception(now + 20_000_000) is None
    assert latch.snapshot().reason == reason
    assert wrapper.perception(now + 40_000_000) is None
    assert calls == 2


def check_neural_freeze_and_planned_exception_are_distinct():
    now = 1_000_000_000
    latch = FaultStopLatch()
    wrapper = FaultAwareInputs(
        fault_latch=latch, started_ns=now,
        perception_step=lambda t: make_perception_frame(timestamp_ns=t, frame_id=1),
        neural_step=lambda frame, t: None,
    )
    assert wrapper.neural(None, now + 100_000_000) is None
    assert latch.snapshot() is None  # exact 100 ms is still fresh
    assert wrapper.neural(None, now + 100_000_001) is None
    assert latch.snapshot().reason == "stale_neural"

    other = FaultStopLatch()
    injected = FaultAwareInputs(
        fault_latch=other, started_ns=now,
        perception_step=lambda t: (_ for _ in ()).throw(PlannedFault("neural_freeze")),
        neural_step=lambda frame, t: None,
    )
    assert injected.perception(now) is None
    assert other.snapshot().planned and other.snapshot().reason == "neural_freeze"


def check_fault_stop_refreshes_authentic_watchdog_output_through_adapter():
    latch, watchdog, robot, adapter = fixture()
    latch.latch("tof_loss", detected_ns=1, planned=True)
    scheduler = FaultStopRefreshScheduler(
        fault_latch=latch, config=ROOT / "config/scheduler_v1.json",
        watchdog=watchdog, perception_step=lambda t: None,
        neural_step=lambda frame, t: None, publisher=adapter.send,
    )
    for index in range(5):
        scheduler._control_tick(1_000_000_000 + index * 20_000_000)
    assert len(robot.calls) == 5
    assert all(intent["stop"] and reason == "fault_tof_loss"
               for _, intent, reason in robot.calls)
    assert all(b[1]["timestamp_ns"] > a[1]["timestamp_ns"]
               for a, b in zip(robot.calls, robot.calls[1:]))


def check_inflight_move_finishes_before_fault_latch_then_only_stop():
    latch, watchdog, robot, adapter = fixture()
    entered = threading.Event()
    release = threading.Event()
    original = robot._send_watchdog

    def blocking_send(output, transport):
        if not output["intent"]["stop"]:
            entered.set()
            assert release.wait(1.0)
        return original(output, transport)

    robot._send_watchdog = blocking_send
    safety = SafetyClamp(load_safety_envelope(ROOT / "config/safety_envelope_v1.json"))
    safety.apply(make_behavior_intent(timestamp_ns=1, sequence=1),
                 now_ns=1, fallback_sequence=1)
    safe = safety.apply(
        make_behavior_intent(timestamp_ns=1_000_000_000, sequence=2, vx=0.07),
        now_ns=1_000_000_000, fallback_sequence=2,
    )
    assert safe["intent"]["vx"] == 0.07
    watchdog.observe_neural({
        "timestamp_ns": 1_000_000_000, "sequence": 2,
        "steering_left": 0.0, "steering_right": 0.0,
        "escape": 0.0, "runtime_healthy": True,
    })
    watchdog.observe_behavior(safe["intent"])
    scheduler = FaultStopRefreshScheduler(
        fault_latch=latch, config=ROOT / "config/scheduler_v1.json",
        watchdog=watchdog, perception_step=lambda t: None,
        neural_step=lambda frame, t: None, publisher=adapter.send,
    )
    move = threading.Thread(target=lambda: scheduler._control_tick(1_000_000_000))
    move.start()
    assert entered.wait(1.0)
    fault = threading.Thread(target=lambda: latch.latch(
        "camera_loss", detected_ns=1_000_000_001, planned=True))
    fault.start()
    assert not robot.calls  # the move ACK is still pending
    release.set()
    move.join(timeout=1)
    fault.join(timeout=1)
    assert not move.is_alive() and not fault.is_alive()
    assert robot.calls[0][1]["stop"] is False
    watchdog.observe_neural({
        "timestamp_ns": 1_020_000_000, "sequence": 3,
        "steering_left": 0.0, "steering_right": 0.0,
        "escape": 0.0, "runtime_healthy": True,
    })
    watchdog.observe_behavior(make_behavior_intent(
        timestamp_ns=1_020_000_000, sequence=3, vx=0.07))
    scheduler._control_tick(1_020_000_000)
    assert robot.calls[-1][1]["stop"] is True
    assert robot.calls[-1][2] == "fault_camera_loss"
    assert not any(not intent["stop"] for _, intent, _ in robot.calls[1:])


def check_expected_vs_unexpected_worker_failure_keeps_control_tail(planned):
    latch, watchdog, robot, adapter = fixture()

    def perception(now_ns):
        if planned:
            raise PlannedFault("camera_loss")
        raise RuntimeError("unexpected camera worker failure")

    wrapper = FaultAwareInputs(
        fault_latch=latch, started_ns=time.monotonic_ns(),
        perception_step=perception, neural_step=lambda frame, t: None,
    )
    scheduler = FaultStopRefreshScheduler(
        fault_latch=latch, config=ROOT / "config/scheduler_v1.json",
        watchdog=watchdog, perception_step=wrapper.perception,
        neural_step=wrapper.neural, publisher=adapter.send,
    )
    errors = []

    def run():
        try:
            scheduler.run(1.0)
        except BaseException as error:
            errors.append(error)

    worker = threading.Thread(target=run)
    worker.start()
    deadline = time.monotonic() + 0.6
    while len(robot.calls) < 4 and time.monotonic() < deadline:
        time.sleep(0.005)
    scheduler.request_complete()  # independent pose observer in a Thor run
    worker.join(timeout=1)
    assert not worker.is_alive()
    assert len(robot.calls) >= 4, (robot.calls, errors, latch.snapshot())
    assert all(intent["stop"] for _, intent, _ in robot.calls)
    if planned:
        assert not errors
    else:
        assert len(errors) == 1 and isinstance(errors[0], SchedulerWorkerError)
        assert errors[0].worker == "perception"
        assert latch.snapshot().planned is False


class FaultStopTests(unittest.TestCase):
    def test_latch(self):
        check_latch_is_first_fault_wins_and_retains_last_healthy_timestamps()

    def test_sensor_faults(self):
        for reason in (
            "camera_loss", "tof_loss", "camera_and_tof_loss",
            "malformed_perception", "nan_feature", "inf_feature", "camera_stale",
        ):
            with self.subTest(reason=reason):
                check_planned_sensor_fault_latches_and_cannot_be_cleared(reason)

    def test_neural_freeze(self):
        check_neural_freeze_and_planned_exception_are_distinct()

    def test_authentic_stop_refresh(self):
        check_fault_stop_refreshes_authentic_watchdog_output_through_adapter()

    def test_inflight_move(self):
        check_inflight_move_finishes_before_fault_latch_then_only_stop()

    def test_worker_failure_tail(self):
        for planned in (True, False):
            with self.subTest(planned=planned):
                check_expected_vs_unexpected_worker_failure_keeps_control_tail(planned)
