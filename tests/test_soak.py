import json
import math
from pathlib import Path
import unittest

from microduck_connectome.soak import run_soak

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config" / "neural_model_v1.json").read_text(encoding="utf-8"))


class FakeClock:
    def __init__(self):
        self.values = iter((10.0, 10.25))
    def __call__(self):
        return next(self.values)


class SoakTests(unittest.TestCase):
    def test_zero_mode_short_fixture_is_stable(self):
        report = run_soak(CONFIG, mode="zero", steps=20, clock=FakeClock())
        self.assertTrue(report["healthy"])
        self.assertFalse(report["nonfinite_detected"])
        self.assertEqual(report["final_step_count"], 20)
        self.assertEqual(report["simulated_seconds"], 0.4)
        self.assertEqual(report["max_abs_state"], 0.0)
        self.assertEqual(report["total_spikes"], 0)

    def test_bounded_mode_exercises_spikes_and_stays_finite(self):
        report = run_soak(CONFIG, mode="bounded", steps=20, clock=FakeClock())
        self.assertTrue(report["healthy"])
        self.assertFalse(report["nonfinite_detected"])
        self.assertGreater(report["total_spikes"], 0)
        self.assertTrue(math.isfinite(report["max_abs_state"]))
        self.assertEqual(report["wall_seconds"], 0.25)

    def test_30000_steps_is_ten_minutes_neural_time(self):
        self.assertEqual(30_000 * CONFIG["timestep_ms"] / 1000.0, 600.0)

    def test_invalid_mode_or_steps_is_rejected(self):
        with self.assertRaises(ValueError):
            run_soak(CONFIG, mode="other", steps=1)
        with self.assertRaises(ValueError):
            run_soak(CONFIG, mode="zero", steps=0)


if __name__ == "__main__":
    unittest.main()
