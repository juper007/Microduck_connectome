"""Deterministic development-only motion timing tests."""

import threading
import time
import unittest

from scripts.p8_03_timing_motion import MotionTimingCoordinator


class ManualClock:
    def __init__(self):
        self.value = 1_000_000_000
        self.condition = threading.Condition()

    def now(self):
        with self.condition:
            return self.value

    def advance(self, ns):
        with self.condition:
            self.value += ns
            self.condition.notify_all()

    def wait_until(self, deadline, stop):
        with self.condition:
            while self.value < deadline and not stop.is_set():
                self.condition.wait(.01)


class Gate:
    def __init__(self):
        self.arm_ns = None
        self.ready = set()
        self.lock = threading.Lock()

    def mark_ready(self, name):
        with self.lock:
            self.ready.add(name)

    def release(self, arm_ns):
        self.arm_ns = arm_ns

    def abort(self):
        self.aborted = True


def eventually(predicate, timeout=.5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(.001)
    return predicate()


class MotionTimingTests(unittest.TestCase):
    def make_coordinator(self, *, state=None, pose=None, capacity=8,
                         scored_slots=50, send_override=None):
        clock = ManualClock()
        gate = Gate()
        faults = []
        calls = []

        def send():
            now = clock.now()
            calls.append(now)
            return {"accepted": True}, now, now, now

        def observe(_ack):
            return {"timestamp_ns": clock.now(), "applied_velocity": [0.07, 0, 0]}

        coordinator = MotionTimingCoordinator(
            send_move=send_override or send, observe_state=state or observe,
            observe_pose=pose or observe, fault=faults.append,
            period_ns=20_000_000, max_observation_age_ns=200_000_000,
            queue_capacity=capacity, clock_ns=clock.now,
            wait_until=clock.wait_until, gate=gate, scored_slots=scored_slots)
        return coordinator, clock, gate, calls, faults

    def test_delayed_state_read_does_not_suppress_refresh_or_arm_transition(self):
        entered = threading.Event()
        unblock = threading.Event()

        def slow_state(_ack):
            entered.set()
            self.assertTrue(unblock.wait(1))
            return {"timestamp_ns": clock.now(), "applied_velocity": [0.07, 0, 0]}

        coordinator, clock, gate, calls, faults = self.make_coordinator(
            state=slow_state, scored_slots=3)
        try:
            coordinator.start()
            self.assertTrue(coordinator.wait_ready(.5))
            self.assertEqual(gate.ready, {"motion", "state", "pose"})
            self.assertTrue(entered.wait(.5))
            for count in range(2, 5):
                clock.advance(20_000_000)
                self.assertTrue(eventually(lambda: len(calls) >= count))
            gate.release(clock.now())
            clock.advance(1_000_000)
            self.assertTrue(eventually(lambda: len(calls) >= 5))
            for slot in (2, 3):
                clock.advance(19_000_000 if slot == 2 else 20_000_000)
                self.assertTrue(eventually(lambda: coordinator.snapshot()[
                    "scored_slots_sent"] >= slot))
            self.assertEqual(faults, [])
            self.assertEqual([r["phase"] for r in coordinator.snapshot()["rows"]
                              if r["kind"] == "motion_refresh"],
                             ["prearm"] * 4 + ["scored"] * 3)
            scored = [r for r in coordinator.snapshot()["rows"]
                      if r["kind"] == "motion_refresh" and r["phase"] == "scored"]
            self.assertEqual([r["scored_slot"] for r in scored], [0, 1, 2])
            arm = next(r for r in coordinator.snapshot()["rows"]
                       if r["kind"] == "motion_arm")
            self.assertEqual(arm["last_move_ack_ns"], calls[3])
        finally:
            unblock.set()
            coordinator.stop()

    def test_delayed_pose_read_does_not_suppress_refresh(self):
        entered = threading.Event()
        unblock = threading.Event()

        def slow_pose(_ack):
            entered.set()
            self.assertTrue(unblock.wait(1))
            return {"timestamp_ns": clock.now(), "x_m": 0.01}

        coordinator, clock, _, calls, faults = self.make_coordinator(pose=slow_pose)
        try:
            coordinator.start()
            self.assertTrue(coordinator.wait_ready(.5))
            self.assertTrue(entered.wait(.5))
            for count in range(2, 5):
                clock.advance(20_000_000)
                self.assertTrue(eventually(lambda: len(calls) >= count))
            self.assertEqual(faults, [])
        finally:
            unblock.set()
            coordinator.stop()

    def test_observer_queue_overflow_fails_closed(self):
        entered = threading.Event()
        unblock = threading.Event()

        def blocked(_ack):
            entered.set()
            unblock.wait(1)
            return {"timestamp_ns": clock.now()}

        coordinator, clock, _, calls, faults = self.make_coordinator(state=blocked,
                                                                     capacity=1)
        try:
            coordinator.start()
            self.assertTrue(coordinator.wait_ready(.5))
            self.assertTrue(entered.wait(.5))
            clock.advance(20_000_000)
            self.assertTrue(eventually(lambda: len(calls) >= 2))
            clock.advance(20_000_000)
            self.assertTrue(eventually(lambda: bool(faults)))
            self.assertIn("observation_queue_overflow", faults[0])
            self.assertEqual(coordinator.snapshot()["queue_drops"], 1)
        finally:
            unblock.set()
            coordinator.stop()

    def test_stale_observation_fails_closed_and_preserves_source(self):
        def stale(_ack):
            return {"timestamp_ns": 1, "applied_velocity": [0.07, 0, 0]}

        coordinator, _, _, _, faults = self.make_coordinator(state=stale)
        try:
            coordinator.start()
            self.assertTrue(eventually(lambda: bool(faults)))
            self.assertIn("state_observation_failed", faults[0])
            self.assertIn("stale", faults[0])
            self.assertEqual(coordinator.snapshot()["fault_reason"], faults[0])
        finally:
            coordinator.stop()

    def test_late_arm_slot_is_failed_not_backfilled(self):
        coordinator, clock, gate, _, faults = self.make_coordinator(scored_slots=3)
        try:
            coordinator.start()
            self.assertTrue(coordinator.wait_ready(.5))
            gate.release(clock.now())
            clock.advance(20_000_000)
            self.assertTrue(eventually(lambda: bool(faults)))
            self.assertEqual(coordinator.snapshot()["scored_slots_sent"], 0)
            self.assertTrue(faults[0].startswith("motion_deadline_missed"))
        finally:
            coordinator.stop()

    def test_release_waits_for_inflight_move_then_preserves_handoff(self):
        entered = threading.Event()
        unblock = threading.Event()
        calls = []
        clock = ManualClock()

        def send():
            if len(calls) == 1:
                entered.set()
                self.assertTrue(unblock.wait(1))
            now = clock.now()
            calls.append(now)
            return {"accepted": True}, now, now, now

        gate = Gate()
        faults = []

        def observe(_ack):
            return {"timestamp_ns": clock.now(), "applied_velocity": [0.07, 0, 0]}

        coordinator = MotionTimingCoordinator(
            send_move=send, observe_state=observe, observe_pose=observe,
            fault=faults.append, period_ns=20_000_000,
            max_observation_age_ns=200_000_000, queue_capacity=8,
            clock_ns=clock.now, wait_until=clock.wait_until, gate=gate,
            scored_slots=2)
        try:
            coordinator.start()
            self.assertTrue(coordinator.wait_ready(.5))
            clock.advance(20_000_000)
            self.assertTrue(entered.wait(.5))
            released = []
            aligned = []
            def at_arm(arm_ns):
                self.assertIsNone(gate.arm_ns)
                aligned.append(arm_ns)
            release_thread = threading.Thread(
                target=lambda: released.append(coordinator.release_arm(
                    lambda: None, at_arm)))
            release_thread.start()
            self.assertFalse(eventually(lambda: bool(released), timeout=.02))
            unblock.set()
            self.assertTrue(eventually(lambda: bool(released)))
            release_thread.join(.5)
            self.assertEqual(aligned, released)
            clock.advance(1_000_000)
            self.assertTrue(eventually(lambda: coordinator.snapshot()[
                "scored_slots_sent"] == 1))
            rows = coordinator.snapshot()["rows"]
            arm = next(r for r in rows if r["kind"] == "motion_arm")
            self.assertEqual(arm["last_move_ack_ns"], calls[1])
            self.assertEqual(arm["handoff_gap_ns"], 0)
            self.assertEqual(faults, [])
        finally:
            unblock.set()
            coordinator.stop()

    def test_failed_arm_validation_aborts_and_faults(self):
        coordinator, _, gate, _, faults = self.make_coordinator()
        try:
            coordinator.start()
            self.assertTrue(coordinator.wait_ready(.5))
            def reject():
                raise RuntimeError("unhealthy robotd")
            with self.assertRaisesRegex(RuntimeError, "unhealthy robotd"):
                coordinator.release_arm(reject)
            self.assertTrue(gate.aborted)
            self.assertIsNone(gate.arm_ns)
            self.assertTrue(faults[0].startswith("arm_prepare_failed"))
        finally:
            coordinator.stop()


if __name__ == "__main__":
    unittest.main()
