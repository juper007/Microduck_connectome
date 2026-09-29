"""Deterministic development-only motion timing tests."""

import json
import socket
import tempfile
from pathlib import Path
import threading
import time
import unittest

from scripts.p8_02_r1_trial import acknowledged_precondition_move
from scripts.p8_03_timing_motion import (DurableMotionJournal, MotionTimingCoordinator,
                                         classify_ack_miss)
from scripts.p8_03_trial import recent_moving_pose


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

    def test_late_ack_has_durable_start_end_and_failed_attempt_row(self):
        clock = ManualClock()
        gate = Gate()
        faults = []
        sent = []
        def send():
            now = clock.now()
            sent.append(now)
            if len(sent) == 2:
                clock.advance(21_000_000)
            return {"accepted": True}, now, now, clock.now()
        def observe(_ack):
            return {"timestamp_ns": clock.now()}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "motion-request-journal.jsonl"
            coordinator = MotionTimingCoordinator(
                send_move=send, observe_state=observe, observe_pose=observe,
                fault=faults.append, clock_ns=clock.now, wait_until=clock.wait_until,
                gate=gate, journal=DurableMotionJournal(path),
                request_id_hint=lambda: len(sent) + 1)
            coordinator.start()
            self.assertTrue(coordinator.wait_ready(.5))
            clock.advance(20_000_000)
            self.assertTrue(eventually(lambda: bool(faults)))
            snapshot = coordinator.stop()
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual([r["kind"] for r in rows],
                             ["motion_request_start", "motion_request_end"] * 2)
            self.assertEqual(rows[-1]["status"], "late_ack")
            self.assertEqual(rows[-1]["failure_reason"],
                             "motion_slot_missed:ACK_after_next_deadline")
            attempts = [r for r in snapshot["rows"] if r["kind"] == "motion_attempt"]
            self.assertEqual(len(attempts), 2)
            self.assertEqual(attempts[-1]["status"], "late_ack")
            self.assertEqual(snapshot["missed_periods"], 1)
            self.assertIsNone(gate.arm_ns)

    def test_missing_ack_exception_retains_terminal_row_and_no_arm(self):
        clock = ManualClock()
        gate = Gate()
        faults = []
        def send():
            trace = coordinator.current_request_trace()
            trace.update(request_id=3, pre_send_ns=clock.now(),
                         socket_write_start_ns=clock.now(),
                         socket_write_end_ns=clock.now(), flush_end_ns=clock.now(),
                         response_wait_start_ns=clock.now())
            raise TimeoutError("no response")
        def observe(_ack):
            return {"timestamp_ns": clock.now()}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "motion-request-journal.jsonl"
            coordinator = MotionTimingCoordinator(
                send_move=send, observe_state=observe, observe_pose=observe,
                fault=faults.append, clock_ns=clock.now, wait_until=clock.wait_until,
                gate=gate, journal=DurableMotionJournal(path))
            coordinator.start()
            self.assertTrue(eventually(lambda: bool(faults)))
            snapshot = coordinator.stop()
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual([r["kind"] for r in rows],
                             ["motion_request_start", "motion_request_end"])
            self.assertEqual(rows[-1]["status"], "exception")
            self.assertEqual(rows[-1]["request_id"], 3)
            self.assertEqual(rows[-1]["ack_miss_class"], "L_unresolved")
            self.assertEqual(len([r for r in snapshot["rows"]
                                  if r["kind"] == "motion_attempt"]), 1)
            self.assertIsNone(gate.arm_ns)

    def test_lock_contention_is_classified_only_when_timestamp_crosses_deadline(self):
        row = {"next_deadline_ns": 120, "worker_wake_ns": 100,
               "lock_wait_start_ns": 101, "command_lock_acquired_ns": 121,
               "pre_send_ns": 122}
        self.assertEqual(classify_ack_miss(row), "H_lock_contention")
        row["command_lock_acquired_ns"] = 102
        row["pre_send_ns"] = 110
        row["first_response_byte_ns"] = 125
        self.assertEqual(classify_ack_miss(row), "L_unresolved")

    def test_prearm_prime_waits_for_new_ack_without_changing_period(self):
        coordinator, clock, gate, calls, faults = self.make_coordinator()
        try:
            coordinator.start()
            self.assertTrue(coordinator.wait_ready(.5))
            prior = calls[-1]
            observed = []
            waiter = threading.Thread(target=lambda: observed.append(
                coordinator.wait_for_ack_after(prior, .5)))
            waiter.start()
            self.assertFalse(eventually(lambda: bool(observed), timeout=.02))
            clock.advance(20_000_000)
            self.assertTrue(eventually(lambda: bool(observed)))
            waiter.join(.5)
            self.assertEqual(observed[0] - prior, 20_000_000)
            self.assertEqual(faults, [])
            self.assertIsNone(gate.arm_ns)
        finally:
            coordinator.stop()

    def test_instrumented_socket_records_write_flush_read_and_parse(self):
        class File:
            def __init__(self):
                self.bytes = bytearray()
                self.reply = b'{"jsonrpc":"2.0","id":1,"result":{"accepted":true}}\n'
            def write(self, data):
                self.bytes.extend(data)
            def flush(self):
                pass
            def read(self, count):
                return self.reply[:count]
            def readline(self):
                return self.reply[1:]
        class Client:
            next_id = 1
            file = File()
            socket = socket.socket()
        client = Client()
        try:
            trace = {}
            result, call, write, ack = acknowledged_precondition_move(
                client, vx=.07, vy=0, vyaw=0, trace=trace)
            self.assertTrue(result["accepted"])
            self.assertEqual(trace["request_id"], 1)
            self.assertLessEqual(call, trace["socket_write_start_ns"])
            self.assertLessEqual(trace["socket_write_start_ns"],
                                 trace["socket_write_end_ns"])
            self.assertLessEqual(trace["socket_write_end_ns"], trace["flush_end_ns"])
            self.assertLessEqual(trace["response_wait_start_ns"],
                                 trace["first_response_byte_ns"])
            self.assertLessEqual(trace["first_response_byte_ns"],
                                 trace["parse_complete_ns"])
            self.assertEqual((write, ack), (trace["flush_end_ns"], trace["ack_ns"]))
        finally:
            client.socket.close()


class PrearmBodyMotionTests(unittest.TestCase):
    def test_recent_sustained_pose_required_at_arm(self):
        now_ns = 1_000_000_000
        rows = [{"kind": "pose_observation",
                 "source_timestamp_ns": now_ns - 343_000_000 + i * 20_000_000,
                 "value": {"pose": {"x_m": .07 * i * .02, "y_m": 0}}}
                for i in range(18)]
        self.assertIsNotNone(recent_moving_pose(rows, now_ns))
        stopped = [dict(row) for row in rows]
        stopped[-7:] = [{**row, "value": {"pose": {"x_m": stopped[-8]["value"]["pose"]["x_m"],
                                               "y_m": 0}}} for row in stopped[-7:]]
        self.assertIsNone(recent_moving_pose(stopped, now_ns))


if __name__ == "__main__":
    unittest.main()
