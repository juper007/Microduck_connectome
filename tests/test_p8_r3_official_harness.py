"""Offline preflight checks for the blocked P8-R3 official fixture."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.p8_r3_official_batch import validate_trial_artifacts
from scripts.p8_r3_official_trial import VisualCadence, validate_frozen_selection


ROOT = Path(__file__).resolve().parents[1]


class OfficialSelectionTests(unittest.TestCase):
    def setUp(self):
        self.protocol = json.loads((ROOT / "config/p8_r3_official_v1.json").read_text())

    def test_unselected_internal_failure_cannot_launch(self):
        with self.assertRaisesRegex(RuntimeError, "internal neural gate"):
            validate_frozen_selection(self.protocol)
        v21 = json.loads((ROOT / "config/p8_r3_v21_official_v1.json").read_text())
        with self.assertRaisesRegex(RuntimeError, "internal neural gate"):
            validate_frozen_selection(v21)

    def frozen(self):
        protocol = copy.deepcopy(self.protocol)
        protocol["internal_gate_status"] = "PASS"
        protocol["official_freeze_status"] = "FROZEN"
        protocol["selected_v2"] = {
            "method": "log_area", "full_scale_rate_per_s": 0.5,
            "area_epsilon": 1e-6, "max_gap_ms": 150, "window_ms": 200,
        }
        protocol["visual_hz"] = 25
        protocol["scenario_config_path"] = "config/looming_scenario_v1.json"
        protocol["scenario_config_sha256"] = "a" * 64
        protocol["internal_gate_artifact_path"] = "docs/evidence/p8-r3/internal-development-raw-v1.json"
        protocol["internal_gate_artifact_sha256"] = "b" * 64
        return protocol

    def test_frozen_candidate_and_cadence_are_exact(self):
        protocol = self.frozen()
        selected, hz = validate_frozen_selection(protocol)
        self.assertEqual((selected.method, hz), ("log_area", 25))
        protocol["selected_v2"]["full_scale_rate_per_s"] = 0.49
        with self.assertRaisesRegex(RuntimeError, "prospective"):
            validate_frozen_selection(protocol)
        protocol = self.frozen()
        protocol["visual_hz"] = 50
        with self.assertRaisesRegex(RuntimeError, "visual cadence"):
            validate_frozen_selection(protocol)

    def test_official_seed_matrix_cannot_be_replaced(self):
        protocol = self.frozen()
        protocol["ordered_official_runs"][1]["seed"] = 880000
        with self.assertRaisesRegex(RuntimeError, "seed matrix"):
            validate_frozen_selection(protocol)

    def test_v21_requires_fractional_detector_and_log_area(self):
        protocol = self.frozen()
        protocol["schema_version"] = "p8-r3-v21-official-development-v1"
        protocol["ordered_official_runs"] = [
            {"run_id": f"{i+1:02d}-{seed}", "seed": seed,
             "arm_elapsed_s": arm}
            for i, (seed, arm) in enumerate(zip((885421, 885422, 885423),
                                                 (2.0, 2.6, 3.0)))
        ]
        protocol["fractional_rgb_module_sha256"] = "c" * 64
        with self.assertRaisesRegex(RuntimeError, "RGB representation"):
            validate_frozen_selection(protocol)
        protocol["visual_representation"] = "fractional_rgb_v21"
        selected, hz = validate_frozen_selection(protocol)
        self.assertEqual((selected.method, hz), ("log_area", 25))
        protocol["selected_v2"]["method"] = "relative_radius"
        protocol["selected_v2"]["full_scale_rate_per_s"] = 0.25
        with self.assertRaisesRegex(RuntimeError, "V2.1 fractional RGB"):
            validate_frozen_selection(protocol)


class ArtifactTests(unittest.TestCase):
    def test_retained_raw_artifacts_must_match_hash_and_folder(self):
        import hashlib

        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            summary = {}
            for key in ("trace_artifact", "events_artifact", "neural_ledger_artifact",
                        "visual_frame_artifact"):
                path = folder / f"{key}.jsonl"
                path.write_text('{"event":1}\n')
                summary[key] = {"path": str(path), "record_count": 1,
                                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            validate_trial_artifacts(summary, folder)
            summary["visual_frame_artifact"]["sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
                validate_trial_artifacts(summary, folder)


class CadenceTests(unittest.TestCase):
    def test_frozen_visual_rates_on_50hz_scheduler_ticks(self):
        ticks = [index * 20_000_000 for index in range(16)]
        for hz, expected in (
            (10, [0, 100, 200, 300]),
            (20, [0, 60, 100, 160, 200, 260, 300]),
            (25, [0, 40, 80, 120, 160, 200, 240, 280]),
        ):
            with self.subTest(hz=hz):
                cadence = VisualCadence(hz)
                observed = [tick // 1_000_000 for tick in ticks if cadence.due(tick)]
                self.assertEqual(observed, expected)


if __name__ == "__main__":
    unittest.main()
