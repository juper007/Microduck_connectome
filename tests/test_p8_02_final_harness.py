import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.p8_02_final_score import score_attempt, score_batch, wilson
from scripts.p8_02_final_trial import validate_frozen_selection


ROOT = Path(__file__).resolve().parents[1]


class FinalApproachHarnessTests(unittest.TestCase):
    def test_frozen_twenty_run_matrix_rejects_replacement_and_rate_change(self):
        protocol = json.loads((ROOT / "config/p8_02_final_approach_v1.json").read_text())
        self.assertEqual(validate_frozen_selection(protocol)[1], 20)
        replaced = copy.deepcopy(protocol)
        replaced["ordered_official_runs"][19]["seed"] = 880020
        with self.assertRaisesRegex(RuntimeError, "seed matrix"):
            validate_frozen_selection(replaced)
        changed = copy.deepcopy(protocol)
        changed["visual_hz"] = 10
        with self.assertRaisesRegex(RuntimeError, "20 Hz"):
            validate_frozen_selection(changed)

    def test_raw_scorer_detects_age_and_ack_tail_tampering(self):
        expected = {"trial_id": "A00", "seed": 880000, "arm_elapsed_s": 2.0}
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            files = {
                "events.jsonl": [
                    {"kind": "control_publish", "watchdog_state": "healthy",
                     "robot_facing_stop": True, "transport_action": "robot_stop_refreshed",
                     "transport_call_started_ns": 350_000_000,
                     "transport_ack_returned_ns": 400_000_000,
                     "neural_trace": {"male_cns": {"healthy": True},
                                      "perception_frame": {"timestamp_ns": 100_000_000,
                                                           "looming": .3},
                                      "stimulus_channels": {"lplc2_left": .2,
                                                            "lplc2_right": 0},
                                      "dn_readout": {"timestamp_ns": 200_000_000},
                                      "neural_stop_latch": {"source": "healthy_neural_escape"},
                                      "pre_safety_intent": {"stop": True},
                                      "safety_result": {"intent": {"stop": True}}}},
                    {"kind": "stop_refresh_ack", "ack_at_ns": 450_000_000},
                    {"kind": "virtual_geometry", "sphere_surface_clearance_m": 0.2}],
                "neural-ledger.jsonl": [{"input_none": False, "result_none": False,
                                          "perception_valid": True, "perception_age_ms": 20,
                                          "runtime_step": 5, "dn_sequence": 5,
                                          "dn_timestamp_ns": 300_000_000,
                                          "dn_escape": .6, "raw_decoder_stop": True,
                                          "post_safety_stop": True,
                                          "dn_runtime_healthy": True,
                                          "male_cns_healthy": True}],
                "visual-frames.jsonl": [{"timestamp_ns": 100_000_000,
                                          "perception_valid": True},
                                         {"timestamp_ns": 150_000_000,
                                          "perception_valid": True}],
                "trace.jsonl": [{"timestamp_ns": 100_000_000,
                                 "robot_facing_vx": 0.0,
                                 "robot_facing_vy": 0.0,
                                 "robot_facing_vyaw": 0.0}],
            }
            artifacts = {}
            names = {"events.jsonl": "events_artifact",
                     "neural-ledger.jsonl": "neural_ledger_artifact",
                     "visual-frames.jsonl": "visual_frame_artifact",
                     "trace.jsonl": "trace_artifact"}

            def write_raw():
                for name, data in files.items():
                    path = folder / name
                    path.write_text("".join(json.dumps(row) + "\n" for row in data),
                                    encoding="ascii", newline="\n")
                    artifacts[names[name]] = {"path": str(path),
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "record_count": len(data)}

            write_raw()
            summary = {**artifacts, "trial_id": "p8-02-final-A00", "seed": 880000,
                       "arm_elapsed_s": 2.0,
                       "schema_version": "p8-02-final-approach-trial-v1",
                       "robot_stop_rpc_ack_returned_ns": 400_000_000,
                       "stopped_confirmed_at_ns": 500_000_000,
                       "checks": {"healthy_neural_stop_first": True},
                       "r3_official_screen_result": "PASS",
                       "healthy_neural_stop_latch": {
                           "source": "healthy_neural_escape", "graph_runtime_step": 5,
                           "neural_sequence": 5, "neural_timestamp_ns": 300_000_000,
                           "first_healthy_stop_ack_ns": 400_000_000},
                       "boundary_at_decoder_stop": {"margin_m": 0.2},
                       "boundary_at_first_stop_request": {"margin_m": 0.15},
                       "fault_stop_latch": None, "scheduler_exceptions": 0,
                       "safety_limit_violations": 0,
                       "lplc2_first_nonzero_at_ns": 200_000_000,
                       "dn_escape_threshold_crossed_at_ns": 300_000_000,
                       "deadman_limiter_seen_before_stopped": False,
                       "positive_move_after_latch_count": 0,
                       "positive_move_ack_after_first_stop_ack_count": 0,
                       "looming_first_nonzero_at_ns": 100_000_000,
                       "decoder_stop_created_at_ns": 300_000_000,
                       "robot_stop_rpc_call_started_ns": 350_000_000}
            summary_path = folder / "summary.json"
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            self.assertTrue(score_attempt(folder, expected)["success"])
            files["neural-ledger.jsonl"][0]["perception_age_ms"] = 101
            write_raw()
            summary.update(artifacts)
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            self.assertIn("missing_invalid_or_stale_neural_visual_input",
                          score_attempt(folder, expected)["failure_causes"])
            files["neural-ledger.jsonl"][0]["perception_age_ms"] = 20
            files["events.jsonl"][1]["ack_at_ns"] = 380_000_000
            write_raw()
            summary.update(artifacts)
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            self.assertIn("stop_ack_refresh_or_tail",
                          score_attempt(folder, expected)["failure_causes"])

    def test_wilson_interval_has_wide_nineteen_of_twenty_uncertainty(self):
        low, high = wilson(19, 20)
        self.assertLess(low, .8)
        self.assertGreater(high, .99)

    def test_one_safety_violation_or_missing_raw_blocks_nineteen_of_twenty(self):
        final = json.loads((ROOT / "config/p8_v2_final_protocol_v1.json").read_text())
        def outcome(folder, expected):
            index = int(expected["trial_id"][1:])
            return {"trial_id": expected["trial_id"], "success": index != 19,
                    "latencies_ms": {}, "raw_accounted": True,
                    "safety_limit_violations": 1 if index == 19 else 0,
                    "margins_m": {}, "failure_causes": []}
        with patch("scripts.p8_02_final_score.score_attempt", side_effect=outcome):
            score = score_batch(Path("unused"), final)
        self.assertEqual(score["successes"], 19)
        self.assertEqual(score["result"], "FAIL")
        self.assertFalse(score["zero_safety_limit_violations"])
        def no_raw(folder, expected):
            row = outcome(folder, expected)
            row["safety_limit_violations"] = 0
            row["raw_accounted"] = expected["trial_id"] != "A19"
            return row
        with patch("scripts.p8_02_final_score.score_attempt", side_effect=no_raw):
            score = score_batch(Path("unused"), final)
        self.assertEqual(score["result"], "FAIL")
        self.assertFalse(score["all_raw_accounted"])


if __name__ == "__main__":
    unittest.main()
