import time
import unittest
import json
from pathlib import Path

from microduck_connectome.control_contracts import make_behavior_intent
from microduck_connectome.g8_r5c_fixture import (
    CompletionScheduler, IsolatedStopPublisher, SUPPRESSED_NEUTRAL,
    UnexpectedNonzeroOutput,
)
from microduck_connectome.scheduler import NeuralUpdate, SchedulerWorkerError
from microduck_connectome.watchdog import ControllerWatchdog
from scripts.g8_r5c_trial import LoomingChain, acknowledged_precondition_move


ROOT = Path(__file__).resolve().parents[1]


def minted(*, vx=0.0, vyaw=0.0, stop=False, sequence=1):
    wd = ControllerWatchdog(ROOT / "config/watchdog_v1.json")
    assert wd.observe_neural({"timestamp_ns": 1, "sequence": 1,
                              "steering_left": 0.0, "steering_right": 0.0,
                              "escape": 0.0, "runtime_healthy": True})
    assert wd.observe_behavior(make_behavior_intent(timestamp_ns=1, sequence=1,
                                                   vx=vx, vyaw=vyaw, stop=stop))
    return wd.tick(now_ns=2, output_sequence=sequence)


class Adapter:
    def __init__(self):
        self.calls = []

    def send(self, output):
        self.calls.append(output)
        return "robot_stop_refreshed"


class G8R5cFixtureTests(unittest.TestCase):
    def test_precondition_request_has_real_ack_and_write_interval(self):
        class File:
            def __init__(self):
                self.written = b""

            def write(self, data):
                self.written += data

            def flush(self):
                pass

            def readline(self):
                return b'{"jsonrpc":"2.0","id":7,"result":{"accepted":true}}\n'

        class Client:
            next_id = 7
            file = File()

        client = Client()
        result, call_ns, write_ns, ack_ns = acknowledged_precondition_move(
            client, vx=.07, vy=0, vyaw=0)
        self.assertTrue(result["accepted"])
        self.assertLessEqual(call_ns, write_ns)
        self.assertLessEqual(write_ns, ack_ns)
        self.assertEqual(json.loads(client.file.written)["method"], "robot.move")
        self.assertEqual(client.next_id, 8)

    def test_exact_neutral_nonstop_is_suppressed_and_not_sent(self):
        adapter = Adapter()
        fixture = IsolatedStopPublisher(adapter)
        self.assertEqual(fixture.send(minted()), SUPPRESSED_NEUTRAL)
        self.assertEqual(fixture.suppressed_count, 1)
        self.assertEqual(adapter.calls, [])

    def test_nonzero_controller_output_fails_without_suppression(self):
        for vx, vyaw in ((.01, 0), (0, .01)):
            with self.subTest(vx=vx, vyaw=vyaw):
                adapter = Adapter()
                fixture = IsolatedStopPublisher(adapter)
                with self.assertRaises(UnexpectedNonzeroOutput):
                    fixture.send(minted(vx=vx, vyaw=vyaw))
                self.assertEqual(fixture.suppressed_count, 0)
                self.assertEqual(fixture.nonzero_count, 1)
                self.assertEqual(adapter.calls, [])

    def test_stop_is_transported_through_unchanged_adapter(self):
        adapter = Adapter()
        fixture = IsolatedStopPublisher(adapter)
        self.assertEqual(fixture.send(minted(stop=True)), "robot_stop_refreshed")
        self.assertEqual(len(adapter.calls), 1)

    def test_forged_mapping_rejected(self):
        with self.assertRaises(TypeError):
            IsolatedStopPublisher(Adapter()).send({"intent": {"stop": False}})

    def test_fixture_scheduler_hands_off_without_shutdown_transport(self):
        wd = ControllerWatchdog(ROOT / "config/watchdog_v1.json")
        now = time.monotonic_ns()
        wd.observe_neural({"timestamp_ns": now, "sequence": 1,
                           "steering_left": 0.0, "steering_right": 0.0,
                           "escape": 0.0, "runtime_healthy": True})
        wd.observe_behavior(make_behavior_intent(timestamp_ns=now, sequence=1))
        results = []
        scheduler = CompletionScheduler(
            config=ROOT / "config/scheduler_v1.json", watchdog=wd,
            perception_step=lambda ts: {"timestamp_ns": ts},
            neural_step=lambda frame, ts: None,
            publisher=lambda output: results.append(output) or "robot_stop_refreshed",
        )
        # The fixture signal is independent of the production failure Event.
        import threading
        timer = threading.Timer(.08, scheduler.request_handoff)
        timer.start()
        start = time.monotonic()
        summary = scheduler.run(1.0)
        timer.join()
        self.assertLess(time.monotonic() - start, .5)
        self.assertEqual(summary["scheduler_exceptions"], 0)
        self.assertGreater(len(results), 0)
        self.assertFalse(any(output["stale_reason"] == "decoder_crash" for output in results))

    def test_fixture_scheduler_preserves_worker_failure(self):
        wd = ControllerWatchdog(ROOT / "config/watchdog_v1.json")
        scheduler = CompletionScheduler(
            config=ROOT / "config/scheduler_v1.json", watchdog=wd,
            perception_step=lambda _: (_ for _ in ()).throw(RuntimeError("boom")),
            neural_step=lambda frame, ts: None,
            publisher=lambda output: "robot_stop_refreshed",
        )
        with self.assertRaisesRegex(SchedulerWorkerError, "perception worker failed: boom"):
            scheduler.run(.5)
        self.assertEqual(scheduler.summary()["scheduler_exceptions"], 1)

    def test_ack_gate_discards_visual_and_neural_input(self):
        # The gate runs before any scenario, perception, or graph dependency.
        chain = object.__new__(LoomingChain)
        chain.handoff_ack_ns = time.monotonic_ns()
        chain.discarded_visual_after_ack = []
        self.assertIsNone(chain.perception(chain.handoff_ack_ns + 1))
        self.assertIsNone(chain.neural({"timestamp_ns": chain.handoff_ack_ns + 1},
                                       chain.handoff_ack_ns + 1))
        self.assertEqual([event["kind"] for event in chain.discarded_visual_after_ack],
                         ["perception_skipped_after_ack", "neural_input_discarded_after_ack"])


if __name__ == "__main__":
    unittest.main()
