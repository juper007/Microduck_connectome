import copy
import hashlib
import json
import math
from pathlib import Path
import random
import socket
import tempfile
import unittest
from unittest.mock import patch

from scripts.p8_02_final_score import (
    boundary_at, pose_rows_from_events, raw_motion_geometry_audit,
    score_attempt, score_batch, wilson,
)
from microduck_connectome.g8_r5d_metrics import first_sustained, pose_speeds
from scripts.p8_02_final_batch import probe_final_sim_state
from scripts.p8_02_final_trial import validate_frozen_selection


ROOT = Path(__file__).resolve().parents[1]


class FinalApproachHarnessTests(unittest.TestCase):
    def test_raw_motion_and_boundary_audit_accepts_measured_pose_then_rejects_false_applied_vx(self):
        seed = 880000
        initial_x = .105
        distance = .85 + (random.Random(seed).random() * 2 - 1) * .01
        fixture = {"kind": "final_fixture_anchor", "trial_seed": seed,
                   "arm_elapsed_s": 2.0, "phase_started_ns": 1_600_000_000,
                   "initial_pose": {"x_m": initial_x, "y_m": 0, "heading_rad": 0},
                   "anchor_x_m": initial_x + distance, "anchor_y_m": 0,
                   "axis_x": 1, "axis_y": 0, "sphere_radius_m": .07,
                   "boundary_center_distance_m": .25,
                   "approach_speed_m_s": .2, "warmup_duration_s": .5}
        events = [fixture]
        def state(t, x, applied):
            return {"body_sample_timestamp_ns": t, "state_sample_timestamp_ns": t,
                    "trunk_x_m": x, "trunk_y_m": 0,
                    "requested_velocity": [0, 0, 0],
                    "applied_velocity": [applied, 0, 0], "limited_by": []}
        for i in range(76):
            t = i * 20_000_000
            events.append({"kind": "precondition_motion", "robot_state": state(t, .07*t/1e9, .07),
                           "request_call_started_at_ns": t-2_000_000,
                           "robot_move_ack_at_ns": t-1_000_000})
        for i in range(80, 101):
            t = i * 20_000_000
            events.append({"kind": "control_publish", "robot_state": state(t, .07*t/1e9, .07)})
        call, ack = 2_010_000_000, 2_020_000_000
        first = {"kind": "control_publish", "transport_call_started_ns": call,
                 "transport_ack_returned_ns": ack,
                 "robot_state": state(2_025_000_000, .14175, .06)}
        events.append(first)
        events.append({"kind": "positive_motion_refresh",
                       "request_call_started_at_ns": 1_990_000_000,
                       "robot_move_ack_at_ns": 2_000_000_000})
        for i in range(102, 141):
            t = i * 20_000_000
            x = .14 + .07 * min(i* .02 - 2, .2)
            applied = .07 if i < 105 else (.03 if i < 110 else 0)
            events.append({"kind": "post_ack_read_only_sample",
                           "robot_state": state(t, x, applied)})
        speeds = pose_speeds(pose_rows_from_events(events), window_ms=100,
                             max_window_ms=140)
        stopped = first_sustained(speeds, threshold_mps=.008, duration_ms=200,
                                  at_or_above=False, after_ns=ack)
        self.assertIsNotNone(stopped)
        summary = {"boundary_at_decoder_stop": boundary_at(fixture, pose_rows_from_events(events),
                                                              2_000_000_000),
                   "boundary_at_first_stop_request": boundary_at(fixture, pose_rows_from_events(events), call),
                   "boundary_at_stop_ack": boundary_at(fixture, pose_rows_from_events(events), ack),
                   "boundary_at_stopped_confirmation": boundary_at(fixture, pose_rows_from_events(events), stopped),
                   "first_applied_vx_reduction_at_ns": 2_100_000_000,
                   "first_applied_vx_near_zero_at_ns": 2_200_000_000,
                   "motion_arbiter_latch_at_ns": 2_005_000_000}
        origin = {"dn_timestamp_ns": 2_000_000_000}
        causes, raw = raw_motion_geometry_audit(events, first, origin, stopped, summary,
                                                {"seed": seed, "arm_elapsed_s": 2.0})
        self.assertEqual(causes, [])
        self.assertGreater(raw["first_stop_request"]["margin_m"], 0)
        for event in events:
            if event.get("kind") == "control_publish" and event is not first:
                event["robot_state"]["applied_velocity"][0] = 0
        causes, _ = raw_motion_geometry_audit(events, first, origin, stopped, summary,
                                              {"seed": seed, "arm_elapsed_s": 2.0})
        self.assertIn("raw_pre_stop_applied_vx", causes)
        fixture["anchor_x_m"] += .1
        causes, _ = raw_motion_geometry_audit(events, first, origin, stopped, summary,
                                              {"seed": seed, "arm_elapsed_s": 2.0})
        self.assertIn("raw_anchor_seed_geometry", causes)

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
            fake_pass = score_attempt(folder, expected)
            self.assertFalse(fake_pass["success"])
            self.assertFalse(fake_pass["raw_accounted"])
            self.assertIn("missing_or_duplicate_fixture_anchor", fake_pass["failure_causes"])
            self.assertIn("missing_final_safety_snapshot", fake_pass["failure_causes"])
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
            files["events.jsonl"][1]["ack_at_ns"] = 620_000_000
            summary["stopped_confirmed_at_ns"] = 550_000_000
            write_raw()
            summary.update(artifacts)
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            post_confirmation = score_attempt(folder, expected)
            self.assertIn("stop_ack_refresh_or_tail", post_confirmation["failure_causes"])
            self.assertEqual(post_confirmation["stop_ack_times_through_confirmation_ns"],
                             [400_000_000])

    def test_final_sim_state_probe_detects_live_body_port(self):
        with tempfile.TemporaryDirectory() as temporary:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                listener.bind(("127.0.0.1", 0))
                listener.listen()
                port = listener.getsockname()[1]
                blocked = probe_final_sim_state(Path(temporary), port)
                self.assertEqual(blocked["result"], "FAIL")
                self.assertTrue(blocked["body_port_connectable"])
            free = probe_final_sim_state(Path(temporary), port)
            self.assertEqual(free["result"], "PASS")
            self.assertFalse(free["robotd_socket_path_exists"])
            (Path(temporary) / "duck-a.sock").write_text("stale", encoding="ascii")
            stale = probe_final_sim_state(Path(temporary), port)
            self.assertEqual(stale["result"], "FAIL")
            self.assertTrue(stale["robotd_socket_path_exists"])

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
