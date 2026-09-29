"""Allocation guards for the second development-only P8-03 timing probe."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

from scripts.p8_03_timing_score import score_batch
from scripts.p8_03_trial import timing_execution_rel


ROOT = Path(__file__).resolve().parents[1]


class AckProbeAllocationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads((ROOT / "config/p8_03_timing_probe_v2.json").read_text())

    def test_fresh_ids_are_accepted_by_scorer(self):
        with tempfile.TemporaryDirectory() as tmp:
            score = score_batch(Path(tmp), self.config)
        self.assertEqual(score, {"result": "FAIL", "error": "batch_journal_unreadable"})

    def test_historical_id_is_rejected_by_scorer(self):
        changed = copy.deepcopy(self.config)
        changed["development_gate"]["ids"][0]["reset_id"] = "TPR2-001"
        with tempfile.TemporaryDirectory() as tmp:
            score = score_batch(Path(tmp), changed)
        self.assertEqual(score, {"result": "FAIL", "error": "probe_ID_allocation_invalid"})

    def test_trial_config_selector_keeps_v1_and_v2_isolated(self):
        self.assertEqual(timing_execution_rel(SimpleNamespace(
            timing_probe=True, timing_probe_version="v1")),
            "config/p8_03_timing_probe_v1.json")
        self.assertEqual(timing_execution_rel(SimpleNamespace(
            timing_probe=True, timing_probe_version="v2")),
            "config/p8_03_timing_probe_v2.json")
        with self.assertRaises(ValueError):
            timing_execution_rel(SimpleNamespace(timing_probe=False,
                                                 timing_probe_version="v2"))


if __name__ == "__main__":
    unittest.main()
