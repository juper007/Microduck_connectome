"""Focused prospective local-reference and matrix contract tests."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.p8_03_local_reference import (create_durable_arm_marker,
                                            settled_reference, verify_local_reference)
from scripts.p8_03_score import planned, score_batch
from scripts.p8_03_batch import main as batch_main


CONFIG = json.loads((Path(__file__).parents[1] /
                     "config/p8_03_local_reference_v1.json").read_text())


def samples(*, drifting=False, unhealthy=False, moving=False):
    rows = []
    for i in range(12):
        t = 1_000_000_000 + i * 50_000_000
        x = .001 * i if drifting else .00001 * i
        packet = {"trunk": [x, 0.0, .116], "imu": {"quat": [1., 0., 0., 0.]},
                  "sim_time": i * .05}
        rows.append({"pose": {"request_ns": t - 1_000_000,
                              "response_ns": t, "raw_packet": json.dumps(packet),
                              "sim_time_s": packet["sim_time"], "x_m": x, "y_m": 0.,
                              "trunk_z_m": .116, "heading_rad": 0.,
                              "roll_rad": 0., "pitch_rad": 0.},
                     "state": {"policy": "stand", "safety": {"fallen": False,
                                                                 "limp": False},
                               "move": {"applied": [.01 if moving else 0., 0., 0.]}},
                     "state_received_ns": t,
                     "health": {"healthy": not unhealthy, "degraded": False,
                                "control_loop": {"ticks": i + 1}},
                     "health_received_ns": t - (i % 4) * 50_000_000})
    return rows


class SettledReferenceTests(unittest.TestCase):
    def test_first_qualifying_window_captures_last_pose(self):
        rows = samples()
        result = settled_reference(rows, CONFIG["settled_gate"], 0)
        self.assertIsNotNone(result)
        self.assertEqual(result["reference"]["x_m"], rows[10]["pose"]["x_m"])
        self.assertTrue(verify_local_reference(result, CONFIG["settled_gate"]))
        changed = copy.deepcopy(result)
        changed["reference"]["x_m"] += .1
        self.assertFalse(verify_local_reference(changed, CONFIG["settled_gate"]))

    def test_unstable_unhealthy_or_moving_startup_rejected(self):
        for kwargs in ({"drifting": True}, {"unhealthy": True}, {"moving": True}):
            self.assertIsNone(settled_reference(samples(**kwargs),
                              CONFIG["settled_gate"], 0), kwargs)

    def test_stale_state_or_discontinuous_pose_rejected(self):
        rows = samples()
        for row in rows:
            row["state_received_ns"] -= 200_000_000
        self.assertIsNone(settled_reference(rows, CONFIG["settled_gate"], 0))
        rows = samples()
        rows[5]["pose"]["response_ns"] += 200_000_000
        self.assertIsNone(settled_reference(rows, CONFIG["settled_gate"], 0))


class MatrixTests(unittest.TestCase):
    def test_fresh_unique_labels_and_behavioral_thresholds(self):
        self.assertEqual(CONFIG["reset_id_semantics"], "UNIQUE_LABEL_ONLY")
        self.assertIs(CONFIG["simulator_rng_seeded"], False)
        self.assertIs(CONFIG["behavioral_acceptance_change"], False)
        self.assertEqual((CONFIG["max_false_stops_per_set"],
                          CONFIG["max_false_stops_pooled"],
                          CONFIG["max_safety_limit_violations"]), (1, 2, 0))
        ids = [r["reset_id"] for stage in "DSR" for r in planned(CONFIG, stage)]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual((len(planned(CONFIG, "D")), len(planned(CONFIG, "S")),
                          len(planned(CONFIG, "R"))), (10, 20, 20))
        self.assertTrue(all(int(value[1:]) >= 889100 for value in ids))

    def test_reject_rng_claim_and_collision(self):
        config = copy.deepcopy(CONFIG)
        config["simulator_rng_seeded"] = True
        with self.assertRaises(ValueError):
            planned(config, "S")
        config = copy.deepcopy(CONFIG)
        config["final_static"][0]["reset_id"] = config["development_gate"]["ids"][0]["reset_id"]
        with self.assertRaises(ValueError):
            planned(config, "S")


class DurableArmTests(unittest.TestCase):
    def test_arm_marker_is_created_once_with_frozen_identity(self):
        with tempfile.TemporaryDirectory() as dirname:
            path = Path(dirname) / "armed.json"
            marker = {"schema_version": "p8-03-local-arm-v1", "state": "ARMED",
                      "reset_id": "D889100", "attempt": 1, "source_head": "a" * 40,
                      "config_sha256": "b" * 64, "armed_at_monotonic_ns": 123,
                      "armed_at_utc_ns": 456}
            create_durable_arm_marker(path, marker)
            self.assertEqual(json.loads(path.read_text()), marker)
            with self.assertRaises(FileExistsError):
                create_durable_arm_marker(path, marker)


class CompletenessTests(unittest.TestCase):
    def test_incomplete_ids_and_missing_final_down_cannot_pass(self):
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            (root / "batch-journal.json").write_text(json.dumps({
                "source_path": str(Path(__file__).parents[1]), "ids": [],
                "final_sim_down": None}))
            result = score_batch(root, CONFIG, "S")
            self.assertEqual(result["result"], "FAIL")
            self.assertFalse(result["final_down_valid"])
            self.assertEqual(result["planned"], 20)

    def test_preflight_only_never_starts_or_creates_attempts(self):
        with tempfile.TemporaryDirectory() as dirname:
            output = Path(dirname) / "development"
            argv = ["p8_03_batch", "--stage", "D", "--root", dirname,
                    "--reviewed-head", "a" * 40, "--microduck", dirname,
                    "--microduck-rl", dirname, "--graph", dirname,
                    "--policy", dirname, "--sim-executable", dirname,
                    "--output", str(output), "--audit", str(Path(dirname) / "audit"),
                    "--sim-state", dirname, "--body-port", "7894",
                    "--preflight-only"]
            with patch("sys.argv", argv), patch(
                    "scripts.p8_03_batch.preflight",
                    return_value=(None, None, None, {"result": "PASS"})) as preflight, patch(
                    "scripts.p8_03_batch.run") as run:
                batch_main()
            preflight.assert_called_once()
            run.assert_not_called()
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
