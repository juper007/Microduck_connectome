"""Focused contracts for the development-only V2 relative looming features."""

import math
import unittest

from microduck_connectome.looming import LoomingError
from microduck_connectome.looming_v2 import LoomingEstimatorV2, LoomingV2Config


def estimator(method):
    scale = 0.25 if method == "relative_radius" else 0.5
    return LoomingEstimatorV2(LoomingV2Config(method=method, full_scale_rate_per_s=scale))


class LoomingV2Tests(unittest.TestCase):
    def test_approach_static_and_receding(self):
        for method in ("log_area", "relative_radius", "log_area_regression"):
            with self.subTest(method=method):
                moving = estimator(method)
                self.assertEqual(moving.update(0.04, timestamp_ns=0), 0)
                self.assertGreater(moving.update(0.05, timestamp_ns=100_000_000), 0)
                self.assertGreater(moving.update(0.07, timestamp_ns=200_000_000), 0)
                for areas in ((0.05, 0.05, 0.05), (0.07, 0.05, 0.04)):
                    control = estimator(method)
                    self.assertEqual(
                        [control.update(area, timestamp_ns=i * 100_000_000) for i, area in enumerate(areas)],
                        [0, 0, 0],
                    )

    def test_relative_expansion_is_scale_invariant_away_from_epsilon(self):
        for method in ("log_area", "relative_radius", "log_area_regression"):
            with self.subTest(method=method):
                outputs = []
                for scale in (1, 4):
                    detector = estimator(method)
                    outputs.append([
                        detector.update(scale * area, timestamp_ns=i * 100_000_000)
                        for i, area in enumerate((0.01, 0.011, 0.012))
                    ])
                self.assertLess(max(abs(a - b) for a, b in zip(*outputs)), 0.001)

    def test_regression_window_retains_short_growth_and_then_expires(self):
        detector = estimator("log_area_regression")
        detector.update(0.04, timestamp_ns=0)
        detector.update(0.05, timestamp_ns=100_000_000)
        self.assertGreater(detector.update(0.05, timestamp_ns=200_000_000), 0)
        self.assertEqual(detector.update(0.05, timestamp_ns=300_000_000), 0)

    def test_gap_zero_area_and_source_loss_rebaseline(self):
        for method in ("log_area", "relative_radius", "log_area_regression"):
            with self.subTest(method=method):
                detector = estimator(method)
                detector.update(0.04, timestamp_ns=0)
                self.assertEqual(detector.update(0.08, timestamp_ns=200_000_000), 0)
                self.assertEqual(detector.update(0, timestamp_ns=250_000_000), 0)
                self.assertEqual(detector.update(0.08, timestamp_ns=300_000_000), 0)
                self.assertEqual(detector.update(0.1, timestamp_ns=320_000_000, valid=False), 0)
                self.assertEqual(detector.update(0.1, timestamp_ns=330_000_000), 0)

    def test_bad_input_and_timestamp_reset(self):
        detector = estimator("log_area")
        for area in (-0.01, 1.01, math.nan, math.inf, True):
            with self.subTest(area=area), self.assertRaises(LoomingError):
                detector.update(area, timestamp_ns=0)
        detector.update(0.1, timestamp_ns=10)
        with self.assertRaises(LoomingError):
            detector.update(0.2, timestamp_ns=10)
        self.assertEqual(detector.update(0.2, timestamp_ns=20), 0)
        with self.assertRaises(LoomingError):
            detector.update(0.3, timestamp_ns=True)

    def test_config_validation_and_bounded_output(self):
        for kwargs in (
            {"method": "unknown"}, {"full_scale_rate_per_s": 0},
            {"area_epsilon": math.inf}, {"area_epsilon": 1},
            {"max_gap_ms": 0}, {"window_ms": 0},
            {"method": "log_area_regression", "window_ms": 100},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(LoomingError):
                LoomingV2Config(**kwargs)
        detector = estimator("log_area")
        detector.update(0.001, timestamp_ns=0)
        self.assertEqual(detector.update(0.5, timestamp_ns=20_000_000), 1)


if __name__ == "__main__":
    unittest.main()
