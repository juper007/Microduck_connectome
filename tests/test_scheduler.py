from pathlib import Path
import threading
import time
import unittest

from microduck_connectome.control_contracts import make_behavior_intent
from microduck_connectome.scheduler import (
    ClosedLoopScheduler,
    NeuralUpdate,
    SchedulerWorkerError,
    load_scheduler_config,
)
from microduck_connectome.watchdog import ControllerWatchdog


ROOT = Path(__file__).resolve().parents[1]


class Recorder:
    def __init__(self):
        self.lock = threading.Lock()
        self.outputs = []

    def __call__(self, output):
        with self.lock:
            self.outputs.append(output)
        return "ok"


class Fixture:
    def __init__(self, *, neural_hz=50, perception_delay=0, neural_delay=0,
                 skip_perception=False, skip_neural=False):
        self.config = load_scheduler_config(ROOT / "config" / "scheduler_v1.json")
        self.config["neural_hz"] = neural_hz
        self.watchdog = ControllerWatchdog(ROOT / "config" / "watchdog_v1.json")
        self.publisher = Recorder()
        self.perception_sequence = 0
        self.neural_sequence = 0
        self.perception_delay = perception_delay
        self.neural_delay = neural_delay
        self.skip_perception = skip_perception
        self.skip_neural = skip_neural
        self.saw_neutral_input = False

    def perception(self, now_ns):
        if self.perception_delay:
            time.sleep(self.perception_delay)
        self.perception_sequence += 1
        if self.skip_perception and self.perception_sequence % 2 == 0:
            return None
        return {"timestamp_ns": now_ns, "frame_id": self.perception_sequence}

    def neural(self, frame, now_ns):
        if self.neural_delay:
            time.sleep(self.neural_delay)
        self.neural_sequence += 1
        if frame is None:
            self.saw_neutral_input = True
        if self.skip_neural and self.neural_sequence % 2 == 0:
            return None
        # None is explicitly encoded as neutral; it never replays a prior frame.
        vyaw = 0.0 if frame is None else 0.2
        readout = {
            "timestamp_ns": now_ns,
            "sequence": self.neural_sequence,
            "steering_left": 0.0,
            "steering_right": 0.0 if frame is None else 0.2,
            "escape": 0.0,
            "runtime_healthy": True,
        }
        return NeuralUpdate(
            readout,
            make_behavior_intent(
                timestamp_ns=now_ns, sequence=self.neural_sequence, vyaw=vyaw
            ),
        )

    def scheduler(self):
        return ClosedLoopScheduler(
            config=self.config,
            watchdog=self.watchdog,
            perception_step=self.perception,
            neural_step=self.neural,
            publisher=self.publisher,
        )


class SchedulerTests(unittest.TestCase):
    def test_nominal_50hz_control_25hz_perception_50hz_neural_and_shutdown(self):
        fixture = Fixture()
        summary = fixture.scheduler().run(0.32)
        self.assertGreaterEqual(summary["perception_hz"], 22.0)
        self.assertGreaterEqual(summary["neural_hz"], 44.0)
        self.assertGreaterEqual(summary["watchdog_hz"], 44.0)
        self.assertEqual(summary["scheduler_exceptions"], 0)
        self.assertTrue(fixture.publisher.outputs[-1]["intent"]["stop"])
        self.assertEqual(fixture.publisher.outputs[-1]["stale_reason"], "decoder_crash")

    def test_20hz_neural_fallback_keeps_50hz_watchdog(self):
        fixture = Fixture(neural_hz=20)
        summary = fixture.scheduler().run(0.32)
        self.assertGreaterEqual(summary["neural_hz"], 17.0)
        self.assertGreaterEqual(summary["watchdog_hz"], 44.0)

    def test_delayed_perception_does_not_delay_watchdog_and_becomes_neutral(self):
        fixture = Fixture(perception_delay=0.14)
        summary = fixture.scheduler().run(0.36)
        self.assertGreaterEqual(summary["watchdog_hz"], 42.0)
        self.assertTrue(fixture.saw_neutral_input)
        self.assertGreater(summary["missed_deadlines"]["perception"], 0)

    def test_delayed_neural_does_not_delay_watchdog_and_stale_motion_stops(self):
        fixture = Fixture(neural_delay=0.14)
        summary = fixture.scheduler().run(0.42)
        self.assertGreaterEqual(summary["watchdog_hz"], 42.0)
        self.assertGreater(summary["stale_events"], 0)
        self.assertTrue(any(
            output["intent"]["stop"] and output["stale_reason"] in
            ("missing_neural", "stale_neural", "stale_behavior")
            for output in fixture.publisher.outputs
        ))
        stale_index = next(
            index for index, output in enumerate(fixture.publisher.outputs)
            if output["stale_reason"] in ("stale_neural", "stale_behavior")
        )
        self.assertTrue(fixture.publisher.outputs[stale_index]["intent"]["stop"])

    def test_skipped_sensor_and_neural_updates_are_counted(self):
        fixture = Fixture(skip_perception=True, skip_neural=True)
        summary = fixture.scheduler().run(0.25)
        self.assertGreater(summary["dropped_perception"], 0)
        self.assertGreater(summary["dropped_neural"], 0)

    def test_invalid_or_future_perception_does_not_become_fresh(self):
        fixture = Fixture()

        def invalid(_now_ns):
            return {"timestamp_ns": -1, "frame_id": 1}

        scheduler = ClosedLoopScheduler(
            config=fixture.config,
            watchdog=fixture.watchdog,
            perception_step=invalid,
            neural_step=fixture.neural,
            publisher=fixture.publisher,
        )
        summary = scheduler.run(0.16)
        self.assertGreater(summary["dropped_perception"], 0)
        self.assertTrue(fixture.saw_neutral_input)

    def test_stale_neural_and_behavior_cannot_be_republished_as_motion(self):
        fixture = Fixture(skip_neural=True)
        # Every second neural call is skipped long enough only in conjunction with
        # this delay to exceed the frozen 100 ms watchdog TTL.
        fixture.neural_delay = 0.12
        summary = fixture.scheduler().run(0.38)
        self.assertGreater(summary["stale_events"], 0)
        for output in fixture.publisher.outputs:
            if output["watchdog_state"] != "healthy":
                self.assertTrue(output["intent"]["stop"])
                self.assertEqual(
                    (output["intent"]["vx"], output["intent"]["vy"], output["intent"]["vyaw"]),
                    (0.0, 0.0, 0.0),
                )

    def test_worker_exception_propagates_and_shutdown_stop_is_attempted(self):
        fixture = Fixture()

        def broken(_now_ns):
            raise LookupError("camera failed")

        scheduler = ClosedLoopScheduler(
            config=fixture.config,
            watchdog=fixture.watchdog,
            perception_step=broken,
            neural_step=fixture.neural,
            publisher=fixture.publisher,
        )
        with self.assertRaisesRegex(SchedulerWorkerError, "perception worker failed"):
            scheduler.run(1.0)
        self.assertTrue(fixture.publisher.outputs[-1]["intent"]["stop"])

    def test_bounded_wait_has_no_busy_loop(self):
        fixture = Fixture()
        summary = fixture.scheduler().run(0.12)
        # Initial immediate tick plus periodic ticks; a spin loop would be orders
        # of magnitude larger than these generous deterministic upper bounds.
        self.assertLessEqual(fixture.perception_sequence, 6)
        self.assertLessEqual(fixture.neural_sequence, 9)
        self.assertLessEqual(len(fixture.publisher.outputs), 10)
        self.assertGreater(summary["watchdog_period_ms_p50"], 10.0)


if __name__ == "__main__":
    unittest.main()
