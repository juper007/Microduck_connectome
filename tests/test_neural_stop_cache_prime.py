"""V2.3 startup cache handoff checks without official simulator seeds."""

from __future__ import annotations

import unittest
from pathlib import Path

from microduck_connectome.control_contracts import make_behavior_intent
from microduck_connectome.fault_stop import FaultStopLatch
from microduck_connectome.neural_stop_arbiter import NeuralStopMotionArbiter
from microduck_connectome.neural_stop_scheduler import NeuralStopRefreshScheduler
from microduck_connectome.perception_frame import make_perception_frame
from microduck_connectome.scheduler import NeuralUpdate, SchedulerError
from microduck_connectome.watchdog import ControllerWatchdog


ROOT = Path(__file__).resolve().parents[1]
BASE = 1_000_000_000


def frame(source_ns: int, frame_id: int = 1, *, valid: bool = True):
    return make_perception_frame(timestamp_ns=source_ns, frame_id=frame_id,
                                 valid=valid)


class StartupCacheTests(unittest.TestCase):
    def fixture(self):
        inputs, outputs = [], []
        sequence = 0

        def neural(sample, now_ns):
            nonlocal sequence
            inputs.append((now_ns, sample))
            if sample is None:
                return None
            sequence += 1
            return NeuralUpdate(
                {"timestamp_ns": now_ns, "sequence": sequence,
                 "steering_left": 0.0, "steering_right": 0.0,
                 "escape": 0.0, "runtime_healthy": True},
                make_behavior_intent(timestamp_ns=now_ns, sequence=sequence),
            )

        def publish(output):
            outputs.append(output)
            return "robot_stop_refreshed" if output["intent"]["stop"] else "neutral"

        scheduler = NeuralStopRefreshScheduler(
            fault_latch=FaultStopLatch(), motion_arbiter=NeuralStopMotionArbiter(),
            config=ROOT / "config/p8_r3_visual_scheduler_v1.json",
            watchdog=ControllerWatchdog(ROOT / "config/watchdog_v1.json"),
            perception_step=lambda now_ns: frame(now_ns, 2),
            neural_step=neural, publisher=publish,
        )
        return scheduler, neural, inputs, outputs

    def test_primed_source_is_used_once_then_replaced_by_20hz_frame(self):
        scheduler, neural, inputs, outputs = self.fixture()
        first = frame(BASE)
        direct = neural(first, BASE)  # Existing one-time neutral graph/Watchdog priming.
        scheduler.watchdog.observe_neural(direct.readout)
        scheduler.watchdog.observe_behavior(direct.behavior_intent)
        self.assertEqual(scheduler.prime_perception(first, now_ns=BASE + 5_000_000),
                         first)
        self.assertEqual(scheduler._perception.get()[0], first)
        self.assertEqual(scheduler._perception.get()[1], BASE)
        for elapsed_ms in (20, 40, 60, 80, 100):
            now_ns = BASE + elapsed_ms * 1_000_000
            if elapsed_ms in (60, 100):
                scheduler._perception_tick(now_ns)
            scheduler._neural_tick(now_ns)
            scheduler._control_tick(now_ns)
        self.assertEqual(len(inputs), 6)  # One direct step, five scheduler steps.
        self.assertTrue(all(sample is not None for _, sample in inputs))
        self.assertEqual([sample["frame_id"] for _, sample in inputs], [1, 1, 1, 2, 2, 2])
        self.assertEqual([sample["timestamp_ns"] for _, sample in inputs[:3]], [BASE] * 3)
        self.assertTrue(all(0 <= now - sample["timestamp_ns"] <= 100_000_000
                            for now, sample in inputs))
        self.assertEqual(scheduler._metrics.dropped_neural, 0)
        self.assertTrue(all(output["watchdog_state"] == "healthy" for output in outputs))
        self.assertEqual(scheduler._metrics.scheduler_exceptions, 0)

    def test_invalid_future_stale_missing_and_duplicate_priming_rejected(self):
        invalid = (
            (None, BASE),
            (frame(BASE, valid=False), BASE),
            (frame(BASE + 1), BASE),
            (frame(BASE), BASE + 100_000_001),
            ({"timestamp_ns": BASE, "frame_id": -1}, BASE),
            ({**frame(BASE), "looming": float("nan")}, BASE),
            ({**frame(BASE), "unexpected": 1}, BASE),
        )
        for sample, now_ns in invalid:
            with self.subTest(sample=sample, now_ns=now_ns):
                scheduler, _, _, _ = self.fixture()
                with self.assertRaises(SchedulerError):
                    scheduler.prime_perception(sample, now_ns=now_ns)
                self.assertEqual(scheduler._perception.get()[2], 0)
        scheduler, _, _, _ = self.fixture()
        scheduler.prime_perception(frame(BASE), now_ns=BASE + 100_000_000)
        with self.assertRaises(SchedulerError):
            scheduler.prime_perception(frame(BASE), now_ns=BASE + 100_000_000)

    def test_delayed_start_rechecks_original_source_timestamp(self):
        scheduler, _, _, _ = self.fixture()
        scheduler.prime_perception(frame(BASE), now_ns=BASE + 5_000_000)
        scheduler.clock_ns = lambda: BASE + 100_000_000
        with self.assertRaisesRegex(SchedulerError, "expired before scheduler start"):
            scheduler.run(0.01)
        self.assertEqual(scheduler._threads, [])
        self.assertIsNone(scheduler._started_ns)

    def test_dropped_next_visual_cannot_rebase_ttl_or_restart_after_fault(self):
        scheduler, neural, inputs, outputs = self.fixture()
        first = frame(BASE)
        direct = neural(first, BASE)
        scheduler.watchdog.observe_neural(direct.readout)
        scheduler.watchdog.observe_behavior(direct.behavior_intent)
        scheduler.prime_perception(first, now_ns=BASE + 5_000_000)
        scheduler._neural_tick(BASE + 20_000_000)
        scheduler._control_tick(BASE + 20_000_000)
        # The expected next 20 Hz frame is dropped.  The original timestamp
        # remains in the cache, so an old frame cannot become fresh again.
        scheduler._neural_tick(BASE + 120_000_000)
        scheduler._control_tick(BASE + 140_000_000)
        self.assertIsNone(inputs[-1][1])
        self.assertEqual(scheduler._metrics.dropped_neural, 1)
        self.assertTrue(outputs[-1]["intent"]["stop"])
        self.assertEqual(scheduler.motion_arbiter.latch_reason, "fault_stale_neural")
        scheduler._perception_tick(BASE + 160_000_000)
        scheduler._neural_tick(BASE + 160_000_000)
        scheduler._control_tick(BASE + 160_000_000)
        scheduler._control_tick(BASE + 180_000_000)
        scheduler._control_tick(BASE + 200_000_000)
        self.assertTrue(outputs[-1]["intent"]["stop"])
        self.assertTrue(all(output["intent"]["stop"] for output in outputs[-4:]))
        self.assertEqual([output["intent"]["timestamp_ns"] for output in outputs[-4:]],
                         [BASE + offset * 1_000_000 for offset in (140, 160, 180, 200)])
        self.assertEqual(scheduler._metrics.scheduler_exceptions, 0)

    def test_fault_after_neural_stop_keeps_priority_after_priming(self):
        scheduler, _, _, outputs = self.fixture()
        scheduler.prime_perception(frame(BASE), now_ns=BASE + 5_000_000)
        scheduler.motion_arbiter.latch("healthy_neural_escape")
        scheduler.fault_latch.latch("camera_loss", detected_ns=BASE + 20_000_000,
                                    planned=True)
        scheduler._control_tick(BASE + 20_000_000)
        scheduler._control_tick(BASE + 40_000_000)
        self.assertEqual(scheduler.motion_arbiter.latch_reason, "fault_camera_loss")
        self.assertTrue(all(output["intent"]["stop"] for output in outputs))
        self.assertEqual(scheduler._metrics.scheduler_exceptions, 0)


if __name__ == "__main__":
    unittest.main()
