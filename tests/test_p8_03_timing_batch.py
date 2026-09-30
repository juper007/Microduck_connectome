"""Offline guards for the opt-in P8-03 R2 timing probe allocation."""

import copy
import json
from pathlib import Path
import unittest
from types import SimpleNamespace

from scripts.p8_03_batch import preflight, probe_config, validate_probe_config


ROOT = Path(__file__).resolve().parents[1]


class TimingBatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = json.loads((ROOT / "config/p8_03_local_reference_v1_r1.json").read_text())
        cls.probe = json.loads((ROOT / "config/p8_03_timing_probe_v1.json").read_text())
        cls.ack_probe = json.loads((ROOT / "config/p8_03_timing_probe_v2.json").read_text())
        cls.causal_probe = json.loads((ROOT / "config/p8_03_timing_probe_v3.json").read_text())

    def test_preregistered_ids_and_frozen_materials(self):
        rows = validate_probe_config(self.probe, self.baseline)
        self.assertEqual([r["reset_id"] for r in rows],
                         ["TPR2-001", "TPR2-002", "TPR2-003"])
        self.assertEqual([r["ordinal"] for r in rows], [0, 1, 2])
        self.assertEqual((self.probe["visual_hz"], self.probe["neural_hz"],
                          self.probe["control_hz"], self.probe["scored_window_ms"]),
                         (20, 50, 50, 1000))

    def test_rejects_final_id_and_material_change(self):
        changed = copy.deepcopy(self.probe)
        changed["development_gate"]["ids"][0]["reset_id"] = "S889200"
        with self.assertRaises(ValueError):
            validate_probe_config(changed, self.baseline)
        changed = copy.deepcopy(self.probe)
        changed["selected_pipeline"]["graph_v2_sha256"] = "0" * 64
        with self.assertRaises(RuntimeError):
            validate_probe_config(changed, self.baseline)

    def test_fresh_ack_probe_ids_and_isolation(self):
        rows = validate_probe_config(self.ack_probe, self.baseline)
        self.assertEqual([r["reset_id"] for r in rows],
                         ["TPR2A-001", "TPR2A-002", "TPR2A-003"])
        self.assertEqual([r["ordinal"] for r in rows], [0, 1, 2])
        self.assertEqual(probe_config(SimpleNamespace(timing_probe_version="v2")),
                         "config/p8_03_timing_probe_v2.json")
        self.assertEqual(probe_config(SimpleNamespace()),
                         "config/p8_03_timing_probe_v1.json")
        for key in ("package_output", "development_output", "state_dir", "body_port"):
            self.assertNotEqual(self.ack_probe[key], self.probe[key])
        for key in ("selected_pipeline", "graph_sha256", "walking_policy_sha256",
                    "moving_gate", "scored_window_ms", "visual_hz", "neural_hz",
                    "control_hz", "max_safety_limit_violations"):
            self.assertEqual(self.ack_probe[key], self.probe[key])

    def test_fresh_ack_probe_rejects_historical_or_final_id(self):
        for rejected_id in ("TPR2-001", "S889200"):
            changed = copy.deepcopy(self.ack_probe)
            changed["development_gate"]["ids"][0]["reset_id"] = rejected_id
            with self.assertRaises(ValueError):
                validate_probe_config(changed, self.baseline)

    def test_causal_probe_accepts_only_its_isolated_source_path(self):
        rows = validate_probe_config(self.causal_probe, self.baseline)
        self.assertEqual([row["reset_id"] for row in rows],
                         ["CTP3-001", "CTP3-002", "CTP3-003"])
        changed = copy.deepcopy(self.causal_probe)
        changed["source_path"] = self.baseline["source_path"]
        with self.assertRaisesRegex(RuntimeError, "timing probe isolation mismatch"):
            validate_probe_config(changed, self.baseline)

    def test_probe_rejects_final_stage_before_file_or_sim_access(self):
        with self.assertRaisesRegex(RuntimeError, "stage D only"):
            preflight(SimpleNamespace(root=ROOT, timing_probe=True, stage="S"))


if __name__ == "__main__":
    unittest.main()
