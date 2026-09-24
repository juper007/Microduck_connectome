"""Freeze checks for Phase-7 trial identities and outcome math."""

from collections import Counter
from itertools import product
import json
from pathlib import Path
import unittest

from scripts.p7_preregister import generate
from scripts.p7_target_batch import wilson_interval


ROOT = Path(__file__).resolve().parents[1]


class P7PreregistrationTests(unittest.TestCase):
    def test_manifest_is_deterministic_balanced_and_unique(self):
        frozen = json.loads((ROOT / "config/steering_experiment_v2.json").read_text())
        self.assertEqual(generate(), frozen)
        targets = frozen["target_trials"]
        controls = frozen["no_target_trials"]
        self.assertEqual((len(targets), len(controls)), (100, 40))
        self.assertEqual(len({row["seed"] for row in targets + controls}), 140)
        classes = Counter((row["target_side"], row["target_eccentricity"],
                           row["target_motion"], row["visual_noise_level"]) for row in targets)
        for combination in product(("left", "right"), ("near_center", "medium", "far"),
                                   ("static", "slow_crossing"), ("clean", "moderate")):
            self.assertGreaterEqual(classes[combination], 4)
        self.assertTrue(all(not row["target_present"] for row in controls))
        self.assertEqual(frozen["schema_version"], "steering-experiment-v2")

    def test_wilson_interval_includes_point_estimate(self):
        lower, upper = wilson_interval(90, 100)
        self.assertLess(lower, .9)
        self.assertGreater(upper, .9)
        self.assertEqual(wilson_interval(0, 0), [None, None])


if __name__ == "__main__":
    unittest.main()
