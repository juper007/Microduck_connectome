"""Fault races and persistent authentic stop refresh for the P8-R3 handoff."""

import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from microduck_connectome.control_contracts import make_behavior_intent
from microduck_connectome.fault_stop import FaultStopLatch
from microduck_connectome.motion_adapter import RobotMotionAdapter
from microduck_connectome.neural_stop_arbiter import MotionLatched, NeuralStopMotionArbiter
from microduck_connectome.neural_stop_scheduler import NeuralStopRefreshScheduler
from microduck_connectome.scheduler import NeuralUpdate
from microduck_connectome.watchdog import ControllerWatchdog


ROOT = Path(__file__).resolve().parents[1]


class RecordingRobotd:
    def __init__(self):
        self.status = SimpleNamespace(connected=True, generation=1)
        self.calls = []
        self.entered = None
        self.release = None

    def _send_watchdog(self, output, transport):
        assert transport == "robot_stop"
        if self.entered is not None:
            self.entered.set()
            assert self.release.wait(2)
        self.calls.append((dict(output["intent"]), output["stale_reason"]))
        return "robot_stop_refreshed" if output["intent"]["stop"] else "move"


def update(now_ns, sequence, *, stop=False):
    return NeuralUpdate(
        readout={"timestamp_ns": now_ns, "sequence": sequence,
                 "steering_left": 0.0, "steering_right": 0.0,
                 "escape": 0.0, "runtime_healthy": True},
        behavior_intent=make_behavior_intent(
            timestamp_ns=now_ns, sequence=sequence, vx=0.05 if not stop else 0.0,
            stop=stop, confidence=0.8),
    )


class NeuralStopPersistenceTests(unittest.TestCase):
    def fixture(self):
        fault = FaultStopLatch()
        arbiter = NeuralStopMotionArbiter()
        robot = RecordingRobotd()
        adapter = RobotMotionAdapter(robot, ROOT / "config/motion_adapter_v1.json")
        scheduler = NeuralStopRefreshScheduler(
            fault_latch=fault, motion_arbiter=arbiter,
            config=ROOT / "config/scheduler_v1.json",
            watchdog=ControllerWatchdog(ROOT / "config/watchdog_v1.json"),
            perception_step=lambda _now: None, neural_step=lambda _frame, _now: None,
            publisher=adapter.send,
        )
        return fault, arbiter, robot, scheduler

    def test_transient_stale_then_fresh_updates_refresh_stop_at_50_hz(self):
        _, arbiter, robot, scheduler = self.fixture()
        base = 1_000_000_000
        scheduler._neural.put(update(base, 1), base)
        scheduler._control_tick(base)
        self.assertFalse(robot.calls[-1][0]["stop"])
        scheduler._control_tick(base + 120_000_000)
        self.assertEqual(robot.calls[-1][1], "stale_neural")
        self.assertEqual(arbiter.latch_reason, "fault_stale_neural")
        for index in range(1, 6):
            now = base + 120_000_000 + index * 20_000_000
            scheduler._neural.put(update(now, index + 1), now)
            scheduler._control_tick(now)
        self.assertTrue(all(intent["stop"] for intent, _ in robot.calls[1:]))
        self.assertTrue(all(reason == "fault_stale_neural"
                            for _, reason in robot.calls[2:]))
        self.assertEqual([b[0]["timestamp_ns"] - a[0]["timestamp_ns"]
                          for a, b in zip(robot.calls[1:], robot.calls[2:])],
                         [20_000_000] * 5)
        self.assertIsNotNone(arbiter.first_stop_ack_ns)
        self.assertEqual(scheduler._metrics.scheduler_exceptions, 0)
        with self.assertRaises(MotionLatched):
            arbiter.move(lambda: None)

    def test_later_external_fault_is_recorded_and_remains_stop_only(self):
        fault, arbiter, robot, scheduler = self.fixture()
        base = 2_000_000_000
        scheduler._control_tick(base)  # first watchdog safe-stop
        scheduler._neural.put(update(base + 20_000_000, 1), base + 20_000_000)
        scheduler._control_tick(base + 20_000_000)
        fault.latch("camera_loss", detected_ns=base + 21_000_000, planned=True)
        for index in (2, 3, 4):
            now = base + index * 20_000_000
            scheduler._neural.put(update(now, index), now)
            scheduler._control_tick(now)
        self.assertEqual(fault.snapshot().reason, "camera_loss")
        self.assertEqual(arbiter.latch_reason, "fault_camera_loss")
        self.assertTrue(all(intent["stop"] for intent, _ in robot.calls))
        self.assertEqual(scheduler._metrics.scheduler_exceptions, 0)

    def test_neural_then_fault_priority_with_nonstop_update(self):
        fault, arbiter, robot, scheduler = self.fixture()
        base = 3_000_000_000
        arbiter.latch("healthy_neural_escape")
        scheduler._neural.put(update(base, 1, stop=True), base)
        scheduler._control_tick(base)
        self.assertEqual(robot.calls[-1][1], None)
        fault.latch("tof_loss", detected_ns=base + 1, planned=True)
        scheduler._neural.put(update(base + 20_000_000, 2), base + 20_000_000)
        scheduler._control_tick(base + 20_000_000)
        self.assertEqual(arbiter.latch_reason, "fault_tof_loss")
        self.assertEqual(robot.calls[-1][1], "fault_tof_loss")
        self.assertTrue(all(intent["stop"] for intent, _ in robot.calls))

    def test_watchdog_safe_stop_supersedes_healthy_neural_latch(self):
        _, arbiter, robot, scheduler = self.fixture()
        base = 3_500_000_000
        arbiter.latch("healthy_neural_escape")
        scheduler._neural.put(update(base, 1, stop=True), base)
        scheduler._control_tick(base)
        self.assertEqual(arbiter.latch_reason, "healthy_neural_escape")
        scheduler._control_tick(base + 120_000_000)
        self.assertEqual(robot.calls[-1][1], "stale_neural")
        self.assertEqual(arbiter.latch_reason, "fault_stale_neural")
        scheduler._neural.put(update(base + 140_000_000, 2), base + 140_000_000)
        scheduler._control_tick(base + 140_000_000)
        self.assertTrue(all(intent["stop"] for intent, _ in robot.calls))

    def test_fault_waits_for_inflight_stop_ack_then_refreshes(self):
        fault, arbiter, robot, scheduler = self.fixture()
        robot.entered = threading.Event()
        robot.release = threading.Event()
        base = 4_000_000_000
        control = threading.Thread(target=lambda: scheduler._control_tick(base))
        control.start()
        self.assertTrue(robot.entered.wait(2))
        fault_thread = threading.Thread(target=lambda: fault.latch(
            "camera_loss", detected_ns=base + 1, planned=True))
        fault_thread.start()
        try:
            self.assertFalse(robot.calls)
            self.assertTrue(fault_thread.is_alive())
        finally:
            robot.release.set()
            control.join(2)
            fault_thread.join(2)
        self.assertFalse(control.is_alive() or fault_thread.is_alive())
        self.assertEqual(len(robot.calls), 1)
        self.assertEqual(fault.snapshot().reason, "camera_loss")
        scheduler._neural.put(update(base + 20_000_000, 1), base + 20_000_000)
        scheduler._control_tick(base + 20_000_000)
        self.assertEqual(arbiter.latch_reason, "fault_camera_loss")
        self.assertTrue(all(intent["stop"] for intent, _ in robot.calls))

    def test_fault_during_inflight_move_ack_orders_stop_after_move(self):
        fault, arbiter, robot, scheduler = self.fixture()
        entered = threading.Event()
        release = threading.Event()
        base = 5_000_000_000
        outcome = []

        def send_move():
            call_ns = time.monotonic_ns()
            entered.set()
            assert release.wait(2)
            ack_ns = time.monotonic_ns()
            return "move", call_ns, call_ns, ack_ns

        def move_worker():
            outcome.append(arbiter.move(send_move))

        move = threading.Thread(target=move_worker)
        move.start()
        self.assertTrue(entered.wait(2))
        fault.latch("camera_loss", detected_ns=base, planned=True)
        control = threading.Thread(target=lambda: scheduler._control_tick(base))
        control.start()
        try:
            self.assertFalse(robot.calls)
            self.assertTrue(control.is_alive())
        finally:
            release.set()
            move.join(2)
            control.join(2)
        self.assertFalse(move.is_alive() or control.is_alive())
        self.assertEqual(len(outcome), 1)
        self.assertEqual(len(robot.calls), 1)
        self.assertTrue(robot.calls[0][0]["stop"])
        self.assertLessEqual(outcome[0][3], arbiter.first_stop_ack_ns)
        self.assertEqual(arbiter.latch_reason, "fault_camera_loss")
        with self.assertRaises(MotionLatched):
            arbiter.move(send_move)


if __name__ == "__main__":
    unittest.main()
