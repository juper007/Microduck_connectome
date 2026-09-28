"""P8-03 raw decision and pose-relative fixture contract tests."""

from __future__ import annotations

import unittest
import hashlib
import json
import math
from pathlib import Path
import tempfile

from microduck_connectome.fractional_rgb_v21 import render_fractional_pixels
from microduck_connectome.looming_scenario import load_config
from microduck_connectome.p8_03_geometry import relative_trial
from scripts.p8_03_score import manifest_check, score_raw, wilson_95
from scripts.p8_03_batch import recover_only


class ControlGeometryTests(unittest.TestCase):
    def test_pose_relative_distance_and_rgb(self):
        config = load_config("config/looming_scenario_v1.json")
        pose = {"x_m": 1.2, "y_m": -0.3, "heading_rad": 0.4, "trunk_z_m": 0.3}
        for mode, elapsed, expected in (("static", 0.0, .85), ("static", 1.0, .85),
                                        ("receding", 0.0, .85), ("receding", 1.0, 1.05)):
            trial, distance = relative_trial(pose=pose, trial_id="S00", seed=881000,
                                             mode=mode, elapsed_after_arm_s=elapsed)
            self.assertAlmostEqual(distance, expected)
            self.assertEqual(len(render_fractional_pixels(config, trial, pose=pose, elapsed_s=0)), 33)
        moved = dict(pose, x_m=pose["x_m"] + .12)
        trial, distance = relative_trial(pose=moved, trial_id="S00", seed=881000,
                                         mode="static", elapsed_after_arm_s=1)
        self.assertAlmostEqual(distance, .85)
        self.assertAlmostEqual(trial.anchor_x_m - moved["x_m"],
                               .85 * math.cos(moved["heading_rad"]))


def clean_raw(stage="S"):
    start = 1_000_000_000
    rows = [{"kind": "arm", "timestamp_ns": start, "trial_id": stage + "00",
             "seed": 881000 if stage == "S" else 882000,
             "moving_confirmed_ns": start - 100_000_000,
             "precondition_displacement_m": .03, "precondition_applied_vx_mps": .06}]
    rows.append({"kind": "prearm_visual_anchor", "timestamp_ns": start - 1,
                 "distance_m": .85, "image_area": .01})
    for i in range(21):
        distance = .85 + (.01 * i if stage == "R" else 0)
        rows.append({"kind": "visual_frame", "timestamp_ns": start + i * 50_000_000,
                     "source_valid": True, "distance_m": distance,
                     "image_area": .01, "bearing_rad": 0.0,
                     "pose": {"x_m": .01 * i, "y_m": 0.0, "heading_rad": 0.0},
                     "virtual_center_x_m": .01 * i + distance,
                     "virtual_center_y_m": 0.0})
    for i in range(51):
        t = start + i * 20_000_000
        rows.extend(({"kind": "neural_step", "timestamp_ns": t, "runtime_healthy": True,
                      "dn_escape": 0, "decoder_stop": False, "source_age_ms": 0},
                     {"kind": "motion_refresh", "timestamp_ns": t, "positive_ack": True},
                     {"kind": "robot_state", "timestamp_ns": t, "deadman_limited": False}))
    rows += [{"kind": "window_complete", "timestamp_ns": start + 1_000_000_000},
             {"kind": "safety_snapshot", "timestamp_ns": start + 1_000_000_001,
              "violations": 0, "scheduler_result": {"scheduler_exceptions": 0}}]
    return rows


class RawScorerTests(unittest.TestCase):
    def test_clean_controls(self):
        for stage, seed in (("S", 881000), ("R", 882000)):
            result = score_raw(clean_raw(stage), trial_id=stage + "00", seed=seed, stage=stage)
            self.assertTrue(result["clean_true_negative"], result)

    def test_false_stop_even_if_cleanup_follows(self):
        rows = clean_raw()
        rows += [{"kind": "neural_step", "timestamp_ns": 1_500_000_000,
                  "runtime_healthy": True, "dn_escape": .6, "decoder_stop": True,
                  "source_age_ms": 0},
                 {"kind": "cleanup", "timestamp_ns": 2_000_000_001}]
        result = score_raw(rows, trial_id="S00", seed=881000, stage="S")
        self.assertTrue(result["false_neural_stop"])
        self.assertFalse(result["clean_true_negative"])

    def test_geometry_and_fault_contaminate(self):
        rows = clean_raw()
        next(r for r in rows if r["kind"] == "visual_frame")["distance_m"] = .86
        rows.append({"kind": "fault", "timestamp_ns": 1_300_000_000})
        result = score_raw(rows, trial_id="S00", seed=881000, stage="S")
        self.assertIn("static_geometry", result["failure_causes"])
        self.assertIn("fault_or_exception", result["failure_causes"])

    def test_wilson_has_fixed_denominator(self):
        low, high = wilson_95(1, 20)
        self.assertLess(low, .05)
        self.assertGreater(high, .05)

    def test_extra_or_mutated_raw_fails_full_manifest(self):
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            path = root / "S00" / "attempt-01" / "events.jsonl"
            path.parent.mkdir(parents=True)
            path.write_bytes(b'{"kind":"arm"}\n')
            data = path.read_bytes()
            manifest = {"files": [{"path": path.relative_to(root).as_posix(),
                                   "sha256": hashlib.sha256(data).hexdigest(),
                                   "bytes": len(data), "record_count": 1}]}
            (root / "raw-manifest.json").write_text(json.dumps(manifest))
            self.assertEqual(manifest_check(root)["result"], "PASS")
            path.write_bytes(data + b"{}\n")
            self.assertEqual(manifest_check(root)["result"], "FAIL")
            path.write_bytes(data)
            (root / "unlisted.log").write_text("junk")
            self.assertEqual(manifest_check(root)["result"], "FAIL")

    def test_fault_stop_blocks_clean_true_negative(self):
        rows = clean_raw()
        rows.append({"kind": "control_publish", "timestamp_ns": 1_500_000_000,
                     "watchdog_state": "fault", "stop": True,
                     "neural_origin": False, "transport": "robot.stop"})
        result = score_raw(rows, trial_id="S00", seed=881000, stage="S")
        self.assertFalse(result["false_neural_stop"])
        self.assertFalse(result["clean_true_negative"])
        self.assertIn("fault_stop", result["failure_causes"])

    def test_recovery_is_audit_only(self):
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            journal = {"ids": [{"trial_id": "S00", "attempts": [
                {"name": "attempt-01", "status": "TRIAL_CHILD_STARTED", "armed": False}]}]}
            path = root / "batch-journal.json"
            path.write_text(json.dumps(journal))
            data = path.read_bytes()
            (root / "raw-manifest.json").write_text(json.dumps({"files": [{
                "path": "batch-journal.json", "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data), "record_count": 1}]}))
            result = recover_only(root)
            self.assertEqual(result["in_flight_unknown_arm"], ["S00/attempt-01"])
            self.assertEqual(path.read_bytes(), data)


if __name__ == "__main__":
    unittest.main()
