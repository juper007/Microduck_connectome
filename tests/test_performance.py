import json
from pathlib import Path
import tempfile
import unittest

from microduck_connectome.performance import (
    build_matched_scale_graph,
    percentile_nearest_rank,
    profile_runtime,
    read_linux_process_memory,
)
from microduck_connectome.workload_identity import (
    performance_workload_definition,
    workload_sha256,
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


class FakeMemoryReader:
    def __init__(self, samples):
        self._samples = iter(samples)

    def __call__(self):
        return next(self._samples)


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

    def test_profile_report_schema_with_fake_clock_and_memory(self):
        clock = FakeClock([1_000_000, 2_000_000, 3_000_000, 4_000_000, 5_000_000])
        memory = FakeMemoryReader([
            {"measurement_method": "fake-rss", "rss_bytes": 1000, "peak_rss_bytes": 1200},
            {"measurement_method": "fake-rss", "rss_bytes": 5000, "peak_rss_bytes": 5200},
            {"measurement_method": "fake-rss", "rss_bytes": 5500, "peak_rss_bytes": 7000},
        ])
        report = profile_runtime(
            CONFIG,
            warmup_steps=2,
            measured_steps=5,
            clock_ns=clock,
            memory_reader=memory,
        )
        self.assertEqual(report["measured_steps"], 5)
        self.assertEqual(report["p50_ms"], 3.0)
        self.assertEqual(report["p95_ms"], 5.0)
        self.assertEqual(report["p99_ms"], 5.0)
        self.assertTrue(report["preferred_p95_target_met"])
        self.assertEqual(report["memory_measurement_method"], "fake-rss")
        self.assertEqual(report["baseline_rss_bytes"], 1000)
        self.assertEqual(report["runtime_constructed_rss_bytes"], 5000)
        self.assertEqual(report["post_profile_rss_bytes"], 5500)
        self.assertEqual(report["peak_rss_bytes"], 7000)
        self.assertEqual(report["runtime_rss_delta_bytes"], 4000)
        expected = performance_workload_definition(warmup_steps=2, measured_steps=5)
        self.assertEqual(report["workload_definition"], expected)
        self.assertEqual(report["workload_sha256"], workload_sha256(expected))

    def test_workload_hash_is_deterministic_and_parameter_sensitive(self):
        first = performance_workload_definition()
        second = performance_workload_definition()
        changed = performance_workload_definition(measured_steps=501)
        self.assertEqual(workload_sha256(first), workload_sha256(second))
        self.assertNotEqual(workload_sha256(first), workload_sha256(changed))

    def test_linux_proc_memory_parser(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "status"
            path.write_text(
                "Name:\tpython\nVmHWM:\t2048 kB\nVmRSS:\t1536 kB\n",
                encoding="utf-8",
            )
            sample = read_linux_process_memory(path)
        self.assertEqual(sample["measurement_method"], "linux-proc-status-vmrss-vmhwm")
        self.assertEqual(sample["rss_bytes"], 1536 * 1024)
        self.assertEqual(sample["peak_rss_bytes"], 2048 * 1024)

    def test_invalid_percentile_inputs(self):
        with self.assertRaises(ValueError):
            percentile_nearest_rank([], 0.5)
        with self.assertRaises(ValueError):
            percentile_nearest_rank([1], 0)


if __name__ == "__main__":
    unittest.main()
