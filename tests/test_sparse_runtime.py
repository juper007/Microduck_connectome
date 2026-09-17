import json
import math
from pathlib import Path
import unittest

from microduck_connectome.sparse_runtime import NeuralRuntimeError, SparseNeuralRuntime

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config" / "neural_model_v1.json").read_text(encoding="utf-8"))


class StubGraph:
    body_ids = (1, 2, 3)

    def edges(self):
        return (
            {"source_body_id": 1, "target_body_id": 2, "normalized_weight": 0.5},
            {"source_body_id": 2, "target_body_id": 3, "normalized_weight": 0.25},
        )


class SparseRuntimeTests(unittest.TestCase):
    def test_previous_step_spikes_drive_recurrence(self):
        runtime = SparseNeuralRuntime(StubGraph(), CONFIG)
        first = runtime.step({1: 1.0})
        self.assertEqual(first["spikes"], (True, False, False))
        second = runtime.step()
        self.assertEqual(second["state"], (0.0, 0.5, 0.0))
        third = runtime.step({2: 0.55})
        self.assertEqual(third["spikes"], (False, True, False))
        fourth = runtime.step()
        self.assertEqual(fourth["state"][2], 0.25)

    def test_reset_returns_zero_healthy_state(self):
        runtime = SparseNeuralRuntime(StubGraph(), CONFIG)
        runtime.step({1: 1.0})
        runtime.reset()
        self.assertEqual(runtime.state(), (0.0, 0.0, 0.0))
        self.assertEqual(runtime.spikes(), (False, False, False))
        self.assertEqual(runtime.step_count, 0)
        self.assertTrue(runtime.healthy)

    def test_invalid_external_fails_closed(self):
        runtime = SparseNeuralRuntime(StubGraph(), CONFIG)
        with self.assertRaises(NeuralRuntimeError):
            runtime.step({999: 1.0})
        self.assertFalse(runtime.healthy)
        with self.assertRaises(NeuralRuntimeError):
            runtime.step()

    def test_nonfinite_external_fails_closed(self):
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                runtime = SparseNeuralRuntime(StubGraph(), CONFIG)
                with self.assertRaises(NeuralRuntimeError):
                    runtime.step({1: value})
                self.assertFalse(runtime.healthy)

    def test_excessive_state_fails_closed(self):
        runtime = SparseNeuralRuntime(StubGraph(), CONFIG, max_abs_state=0.5)
        with self.assertRaises(NeuralRuntimeError):
            runtime.step({1: 0.6})
        self.assertFalse(runtime.healthy)

    def test_rejects_unsorted_graph_ids(self):
        class BadGraph:
            body_ids = (2, 1)
            def edges(self):
                return ()
        with self.assertRaises(NeuralRuntimeError):
            SparseNeuralRuntime(BadGraph(), CONFIG)

    def test_rejects_negative_or_nonfinite_weight(self):
        for bad_weight in (-0.1, math.nan):
            with self.subTest(weight=bad_weight):
                class BadGraph:
                    body_ids = (1, 2)
                    def edges(self):
                        return ({"source_body_id": 1, "target_body_id": 2,
                                 "normalized_weight": bad_weight},)
                with self.assertRaises(NeuralRuntimeError):
                    SparseNeuralRuntime(BadGraph(), CONFIG)

    def test_zero_input_leaks_state(self):
        runtime = SparseNeuralRuntime(StubGraph(), CONFIG)
        runtime.step({3: 0.5})
        self.assertAlmostEqual(runtime.state()[2], 0.5)
        runtime.step()
        self.assertAlmostEqual(runtime.state()[2], 0.45, places=6)

    def test_candidate_is_quantized_to_float32_before_threshold(self):
        runtime = SparseNeuralRuntime(StubGraph(), CONFIG)
        result = runtime.step({1: 0.99999998})
        self.assertTrue(result["spikes"][0])
        self.assertEqual(result["state"][0], 0.0)

    def test_deterministic_replay(self):
        trace = ({1: 0.4}, {1: 0.7}, {2: 0.6}, {}, {3: 0.2})
        def run():
            runtime = SparseNeuralRuntime(StubGraph(), CONFIG)
            return [runtime.step(item) for item in trace]
        self.assertEqual(run(), run())


if __name__ == "__main__":
    unittest.main()
