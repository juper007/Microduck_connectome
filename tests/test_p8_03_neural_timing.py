"""Development-only timing spans preserve the frozen neural result."""

import threading
import time
from types import SimpleNamespace
import unittest

from microduck_connectome.neural_stop_arbiter import NeuralStopMotionArbiter
from microduck_connectome.neural_stop_latch import NeuralStopIntentLatch
from microduck_connectome.control_contracts import make_behavior_intent
from microduck_connectome.safety_clamp import SafetyClamp
from scripts.p8_02_r1_trial import LoomingChain


def make_chain(timing_enabled):
    chain = LoomingChain.__new__(LoomingChain)
    chain.timing_enabled = timing_enabled
    chain.timing_ledger = []
    chain.neural_sequence = 0
    chain.mapper = SimpleNamespace(
        map_channels=lambda frame, now_ns: {"lplc2_left": frame["looming"]},
        build_external=lambda frame, now_ns: {1: frame["looming"]})
    chain.runtime_index = {1: 0}
    chain.dn_ids = (1,)
    chain.runtime = SimpleNamespace(step=lambda external: {
        "spikes": (False,), "healthy": True})
    chain.aggregator = SimpleNamespace(update=lambda spikes, *, timestamp_ns,
                                       sequence, runtime_healthy: {
        "timestamp_ns": timestamp_ns, "sequence": sequence,
        "steering_left": 0.0, "steering_right": 0.0,
        "escape": 0.0, "runtime_healthy": runtime_healthy})
    chain.steering = SimpleNamespace(decode=lambda readout: None)
    chain.escape = SimpleNamespace(apply=lambda readout, steering: make_behavior_intent(
        timestamp_ns=readout["timestamp_ns"], sequence=readout["sequence"],
        stop=False, confidence=0.0))
    chain.safety = SafetyClamp()
    chain.neural_stop_latch = NeuralStopIntentLatch(escape_threshold=0.5)
    chain.arbiter = NeuralStopMotionArbiter()
    chain.graph_identity = "timing-test-graph"
    chain.scenario = "stop"
    chain.neural_ledger = []
    return chain


class NeuralTimingTests(unittest.TestCase):
    def test_complete_ordered_spans_and_unchanged_values(self):
        now_ns = time.monotonic_ns()
        frame = {"timestamp_ns": now_ns, "frame_id": 1, "valid": True,
                 "looming": 0.0, "proximity_left": 0.0,
                 "proximity_center": 0.0, "proximity_right": 0.0}
        ordinary = make_chain(False)
        timed = make_chain(True)
        expected = ordinary.neural(frame, now_ns)
        actual = timed.neural(frame, now_ns)
        self.assertEqual(actual, expected)
        variable_fields = {"neural_call_started_ns", "neural_call_returned_ns",
                           "perception_age_ms"}
        self.assertEqual(
            {key: value for key, value in timed.neural_ledger[0].items()
             if key not in variable_fields},
            {key: value for key, value in ordinary.neural_ledger[0].items()
             if key not in variable_fields})
        self.assertEqual(ordinary.timing_ledger, [])
        self.assertEqual(len(timed.timing_ledger), 1)
        row = timed.timing_ledger[0]
        self.assertEqual(row["thread_id"], threading.get_ident())
        self.assertLessEqual(row["thread_cpu_start_ns"], row["thread_cpu_return_ns"])
        spans = row["spans"]
        names = ("arbiter_lock_wait", "sensory_channels", "sensory_external",
                 "graph_runtime", "readout", "decoder_safety_latch",
                 "trace_construction")
        self.assertEqual(set(spans), {"neural_call", "ledger_append", *names})
        self.assertLessEqual(spans["neural_call"]["start_ns"],
                             spans["arbiter_lock_wait"]["start_ns"])
        previous = spans["arbiter_lock_wait"]["start_ns"]
        for name in names:
            span = spans[name]
            self.assertLessEqual(previous, span["start_ns"])
            self.assertLessEqual(span["start_ns"], span["end_ns"])
            previous = span["end_ns"]
        self.assertLessEqual(previous, spans["neural_call"]["end_ns"])
        self.assertLessEqual(spans["neural_call"]["end_ns"],
                             spans["ledger_append"]["start_ns"])

    def test_missing_frame_has_no_fake_compute_spans(self):
        chain = make_chain(True)
        self.assertIsNone(chain.neural(None, time.monotonic_ns()))
        spans = chain.timing_ledger[0]["spans"]
        self.assertEqual(set(spans), {"neural_call", "arbiter_lock_wait", "ledger_append"})
        self.assertTrue(chain.timing_ledger[0]["result_none"])


if __name__ == "__main__":
    unittest.main()
