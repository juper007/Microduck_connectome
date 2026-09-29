"""Development probe READY and fixed 20 ms slot checks."""

from pathlib import Path
import threading
import time
import unittest

from microduck_connectome.control_contracts import make_behavior_intent
from microduck_connectome.fault_stop import FaultStopLatch
from microduck_connectome.neural_stop_arbiter import NeuralStopMotionArbiter
from microduck_connectome.p8_03_timing_gate import ReadyStartGate, TimingGateError
from microduck_connectome.p8_03_timing_scheduler import ReadyTimingScheduler
from microduck_connectome.perception_frame import make_perception_frame
from microduck_connectome.scheduler import NeuralUpdate
from microduck_connectome.watchdog import ControllerWatchdog


ROOT = Path(__file__).resolve().parents[1]


class TimingGateTests(unittest.TestCase):
    def test_all_workers_ready_before_arm(self):
        gate = ReadyStartGate(2)
        results = []
        workers = [threading.Thread(target=lambda name=name: results.append(
            gate.arrive_and_wait(name))) for name in ("neural", "motion")]
        with self.assertRaises(TimingGateError):
            gate.release(123)
        workers[0].start()
        self.assertFalse(gate.wait_ready(.01))
        workers[1].start()
        self.assertTrue(gate.wait_ready(.5))
        gate.release(123)
        for worker in workers:
            worker.join(.5)
            self.assertFalse(worker.is_alive())
        self.assertEqual(results, [123, 123])

    def test_aborted_gate_releases_waiters_without_arm(self):
        gate = ReadyStartGate(1)
        errors = []
        worker = threading.Thread(target=lambda: self._wait_error(gate, errors))
        worker.start()
        self.assertTrue(gate.wait_ready(.5))
        gate.abort()
        worker.join(.5)
        self.assertEqual(errors, [TimingGateError])

    @staticmethod
    def _wait_error(gate, errors):
        try:
            gate.arrive_and_wait("worker")
        except BaseException as error:
            errors.append(type(error))


class ReadySchedulerTests(unittest.TestCase):
    def make_scheduler(self, *, slots=3, perception_delay=0, neural_delay=0):
        gate = ReadyStartGate(3)
        seen = {"neural": [], "control": [], "visual": []}
        sequence = 0

        def perception(now_ns):
            if perception_delay:
                time.sleep(perception_delay)
            seen["visual"].append(now_ns)
            return make_perception_frame(timestamp_ns=now_ns,
                                         frame_id=len(seen["visual"]), valid=True)

        def neural(frame, now_ns):
            nonlocal sequence
            if neural_delay:
                time.sleep(neural_delay)
            seen["neural"].append((now_ns, frame))
            if frame is None:
                return None
            sequence += 1
            return NeuralUpdate(
                {"timestamp_ns": now_ns, "sequence": sequence,
                 "steering_left": 0.0, "steering_right": 0.0,
                 "escape": 0.0, "runtime_healthy": True},
                make_behavior_intent(timestamp_ns=now_ns, sequence=sequence))

        def publish(output):
            seen["control"].append(output)
            return "neutral"

        scheduler = ReadyTimingScheduler(
            start_gate=gate, slots=slots,
            fault_latch=FaultStopLatch(), motion_arbiter=NeuralStopMotionArbiter(),
            config=ROOT / "config/p8_r3_visual_scheduler_v1.json",
            watchdog=ControllerWatchdog(ROOT / "config/watchdog_v1.json"),
            perception_step=perception, neural_step=neural, publisher=publish)
        before = time.monotonic_ns()
        scheduler.prime_perception(
            make_perception_frame(timestamp_ns=before, frame_id=1, valid=True),
            now_ns=before)
        return scheduler, gate, seen

    def run_short_probe(self, scheduler, gate, *, delay_before_arm=.01):
        result = []
        thread = threading.Thread(target=lambda: self._run_scheduler(scheduler, result))
        thread.start()
        self.assertTrue(gate.wait_ready(.5))
        time.sleep(delay_before_arm)
        self.assertEqual(scheduler.timing_rows, [])
        arm_ns = time.monotonic_ns()
        gate.release(arm_ns)
        time.sleep(.09)
        scheduler.request_complete()
        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(result), 1)
        if isinstance(result[0], BaseException):
            raise result[0]
        return arm_ns, result[0]

    @staticmethod
    def _run_scheduler(scheduler, result):
        try:
            result.append(scheduler.run())
        except BaseException as error:
            result.append(error)

    def test_workers_start_after_arm_on_exact_20ms_deadlines(self):
        scheduler, gate, seen = self.make_scheduler()
        arm_ns, summary = self.run_short_probe(scheduler, gate)
        for domain in ("perception", "neural", "watchdog"):
            rows = sorted((r for r in scheduler.timing_rows if r.get("domain") == domain),
                          key=lambda r: r["slot"])
            self.assertEqual([r["slot"] for r in rows], [0, 1, 2])
            self.assertEqual([r["scheduled_deadline_ns"] for r in rows],
                             [arm_ns + i * 20_000_000 for i in range(3)])
            self.assertTrue(all(r["worker_wake_ns"] >= arm_ns for r in rows))
            self.assertTrue(all(r["thread_id"] for r in rows))
        self.assertEqual(len(seen["neural"]), 3)
        self.assertEqual(len(seen["control"]), 3)
        self.assertEqual([row["intent"]["sequence"] for row in seen["control"]],
                         [1, 2, 3])
        self.assertEqual(summary["scheduler_exceptions"], 0)

    def test_blocking_perception_does_not_remove_neural_slots(self):
        scheduler, gate, seen = self.make_scheduler(perception_delay=.05)
        self.run_short_probe(scheduler, gate)
        self.assertEqual(len(seen["neural"]), 3)
        self.assertEqual(len(seen["control"]), 3)
        self.assertEqual(len([r for r in scheduler.timing_rows
                              if r.get("domain") == "neural"]), 3)

    def test_overdue_neural_tick_remains_visible(self):
        scheduler, gate, _ = self.make_scheduler(neural_delay=.03)
        with self.assertRaises(Exception):
            self.run_short_probe(scheduler, gate)
        rows = [r for r in scheduler.timing_rows if r.get("domain") == "neural"]
        self.assertTrue(any(r["late_or_overrun"] for r in rows))
        self.assertGreater(scheduler._metrics.missed_deadlines["neural"], 0)


if __name__ == "__main__":
    unittest.main()
