import math
import unittest

from microduck_connectome.looming import LoomingConfig, LoomingError, LoomingEstimator


class LoomingTests(unittest.TestCase):
    def test_stationary_and_receding_are_zero(self):
        estimator = LoomingEstimator()
        self.assertEqual(estimator.update(0.4, timestamp_ns=0), 0.0)
        self.assertEqual(estimator.update(0.4, timestamp_ns=50_000_000), 0.0)
        self.assertEqual(estimator.update(0.2, timestamp_ns=100_000_000), 0.0)

    def test_controlled_approach_is_monotonic(self):
        estimator = LoomingEstimator(LoomingConfig(full_scale_area_rate_per_s=2.0, max_gap_ms=100))
        samples = [
            estimator.update(0.10, timestamp_ns=0),
            estimator.update(0.15, timestamp_ns=100_000_000),
            estimator.update(0.25, timestamp_ns=200_000_000),
            estimator.update(0.40, timestamp_ns=300_000_000),
        ]
        self.assertEqual(samples[0], 0.0)
        self.assertTrue(all(a <= b for a, b in zip(samples, samples[1:])))
        self.assertEqual(samples[1:], [0.25, 0.5, 0.75])

    def test_output_clamps_to_one(self):
        estimator = LoomingEstimator(LoomingConfig(full_scale_area_rate_per_s=0.1))
        estimator.update(0.0, timestamp_ns=0)
        self.assertEqual(estimator.update(1.0, timestamp_ns=10_000_000), 1.0)

    def test_invalid_source_resets_to_neutral(self):
        estimator = LoomingEstimator()
        estimator.update(0.1, timestamp_ns=0)
        self.assertGreater(estimator.update(0.2, timestamp_ns=50_000_000), 0.0)
        self.assertEqual(estimator.update(0.9, timestamp_ns=60_000_000, valid=False), 0.0)
        self.assertEqual(estimator.update(0.9, timestamp_ns=70_000_000), 0.0)

    def test_stale_gap_restarts_from_neutral(self):
        estimator = LoomingEstimator(LoomingConfig(max_gap_ms=100))
        estimator.update(0.1, timestamp_ns=0)
        self.assertEqual(estimator.update(0.9, timestamp_ns=101_000_000), 0.0)
        self.assertGreater(estimator.update(1.0, timestamp_ns=151_000_000), 0.0)

    def test_nonmonotonic_timestamp_fails_and_resets(self):
        estimator = LoomingEstimator()
        estimator.update(0.1, timestamp_ns=10)
        with self.assertRaises(LoomingError):
            estimator.update(0.2, timestamp_ns=10)
        self.assertEqual(estimator.update(0.3, timestamp_ns=20), 0.0)

    def test_bad_inputs_and_config_are_rejected(self):
        for area in (-0.1, 1.1, math.nan, True):
            with self.subTest(area=area):
                with self.assertRaises(LoomingError):
                    LoomingEstimator().update(area, timestamp_ns=0)
        for config in (
            {"full_scale_area_rate_per_s": 0},
            {"full_scale_area_rate_per_s": math.inf},
            {"max_gap_ms": 0},
        ):
            with self.subTest(config=config):
                with self.assertRaises(LoomingError):
                    LoomingConfig(**config)


if __name__ == "__main__":
    unittest.main()
