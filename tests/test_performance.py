import json
from pathlib import Path
import unittest

from microduck_connectome.performance import (
    build_matched_scale_graph,
    percentile_nearest_rank,
    profile_runtime,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config" / "neural_model_v1.json").read_text(encoding="utf-8"))


class FakeClock:
    def __init__(self, durations):
        self._durations = iter(durations)
        self._now = 0
        self._start = True

    def __call__(self):
        if self._start:
            self._start = False
            return self._now
        self._now += next(self._durations)
        self._start = True
        return self._now


class PerformanceTests(unittest.TestCase):
    def test_nearest_rank_percentiles(self):
        values = [50, 10, 40, 20, 30]
        self.assertEqual(percentile_nearest_rank(values, 0.50), 30)
        self.assertEqual(percentile_nearest_rank(values, 0.95), 50)
        self.assertEqual(percentile_nearest_rank(values, 1.00), 50)

    def test_matched_scale_graph_shape_is_deterministic(self):
        first = build_matched_scale_graph()
        second = build_matched_scale_graph()
        self.assertEqual(first.body_ids, second.body_ids)
        self.assertEqual(first.edges(), second.edges())
        self.assertEqual(len(first.body_ids), 570)
        self.assertEqual(len(first.edges()), 21142)
        self.assertEqual(len({(e["source_body_id"], e["target_body_id"]) for e in first.edges()}), 21142)

    def test_profile_report_schema_with_fake_clock(self):
        # 2 warmup steps are untimed; 5 measured steps consume five durations.
        clock = FakeClock([1_000_000, 2_000_000, 3_000_000, 4_000_000, 5_000_000])
        report = profile_runtime(CONFIG, warmup_steps=2, measured_steps=5, clock_ns=clock)
        self.assertEqual(report["measured_steps"], 5)
        self.assertEqual(report["p50_ms"], 3.0)
        self.assertEqual(report["p95_ms"], 5.0)
        self.assertEqual(report["p99_ms"], 5.0)
        self.assertTrue(report["preferred_p95_target_met"])

    def test_invalid_percentile_inputs(self):
        with self.assertRaises(ValueError):
            percentile_nearest_rank([], 0.5)
        with self.assertRaises(ValueError):
            percentile_nearest_rank([1], 0)


if __name__ == "__main__":
    unittest.main()
