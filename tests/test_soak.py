import json
import math
from pathlib import Path
import unittest

from microduck_connectome.soak import run_soak
from microduck_connectome.workload_identity import soak_workload_definition, workload_sha256

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config" / "neural_model_v1.json").read_text(encoding="utf-8"))
EVIDENCE = ROOT / "docs" / "evidence" / "p3-07" / "soak-v1.json"


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
        expected = soak_workload_definition(timestep_ms=20, steps=20)
        self.assertEqual(report["workload_sha256"], workload_sha256(expected))

    def test_bounded_mode_exercises_spikes_and_stays_finite(self):
        report = run_soak(CONFIG, mode="bounded", steps=20, clock=FakeClock())
        self.assertTrue(report["healthy"])
        self.assertFalse(report["nonfinite_detected"])
        self.assertGreater(report["total_spikes"], 0)
        self.assertTrue(math.isfinite(report["max_abs_state"]))
        self.assertEqual(report["wall_seconds"], 0.25)

    def test_30000_steps_is_ten_minutes_neural_time(self):
        self.assertEqual(30_000 * CONFIG["timestep_ms"] / 1000.0, 600.0)

    def test_workload_hash_is_deterministic_and_parameter_sensitive(self):
        first = soak_workload_definition()
        second = soak_workload_definition()
        changed = soak_workload_definition(steps=30_001)
        self.assertEqual(workload_sha256(first), workload_sha256(second))
        self.assertNotEqual(workload_sha256(first), workload_sha256(changed))

    def test_historical_v1_evidence_remains_self_consistent(self):
        evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        self.assertEqual(evidence["schema_version"], "p3-07-soak-v1")
        self.assertEqual(evidence["dataset"], "male-cns:v1.0")
        self.assertEqual(
            evidence["neural_config_sha256"],
            "6fb682ee73302142d75d54c81ef3c2a7acb647ca8e70a59dc3c93b04df8f7a15",
        )
        self.assertTrue(evidence["all_healthy"])
        self.assertFalse(evidence["nonfinite_detected"])
        self.assertEqual([run["mode"] for run in evidence["runs"]], ["zero", "bounded"])
        for run in evidence["runs"]:
            self.assertEqual(run["steps"], 30_000)
            self.assertEqual(run["final_step_count"], 30_000)
            self.assertEqual(run["timestep_ms"], 20)
            self.assertEqual(run["simulated_seconds"], 600.0)
            self.assertTrue(run["healthy"])
            self.assertFalse(run["nonfinite_detected"])
        self.assertEqual(evidence["runs"][0]["total_spikes"], 0)
        self.assertGreater(evidence["runs"][1]["total_spikes"], 0)

    def test_invalid_mode_or_steps_is_rejected(self):
        with self.assertRaises(ValueError):
            run_soak(CONFIG, mode="other", steps=1)
        with self.assertRaises(ValueError):
            run_soak(CONFIG, mode="zero", steps=0)


if __name__ == "__main__":
    unittest.main()
