import math
import unittest

from microduck_connectome.g8_r5c_metrics import (
    bounded_neural_lineage, causal_timeline_ok, deadman_timing, first_sustained, is_healthy_neural_stop,
    material_pre_stop_applied, neural_input_ended_by_ack, pose_speeds,
    safe_observation_horizon, stop_onset_before_deadman, valid_state_path,
)


class G8R5cMetricsTests(unittest.TestCase):
    def test_pose_speed_uses_official_displacement_not_requested_twist(self):
        rows = [{"timestamp_ns": i * 20_000_000, "x_m": i * .002,
                 "y_m": 0.0, "requested_vx": 0.0} for i in range(20)]
        speeds = pose_speeds(rows)
        self.assertIsNone(speeds[0]["pose_speed_mps"])
        self.assertAlmostEqual(speeds[10]["pose_speed_mps"], .1)

    def test_nonfinite_or_nonmonotonic_pose_rejected(self):
        with self.assertRaises(ValueError):
            pose_speeds([{"timestamp_ns": 1, "x_m": math.nan, "y_m": 0}])
        with self.assertRaises(ValueError):
            pose_speeds([{"timestamp_ns": 1, "x_m": 0, "y_m": 0},
                         {"timestamp_ns": 1, "x_m": 0, "y_m": 0}])

    def test_moving_and_stopped_confirmation(self):
        moving = [{"timestamp_ns": i * 20_000_000, "pose_speed_mps": .03}
                  for i in range(16)]
        self.assertEqual(first_sustained(moving, threshold_mps=.015,
                                         duration_ms=200, at_or_above=True), 200_000_000)
        stopped = [{"timestamp_ns": i * 20_000_000,
                    "pose_speed_mps": .003 if i >= 5 else .03} for i in range(20)]
        self.assertEqual(first_sustained(stopped, threshold_mps=.008,
                                         duration_ms=200, at_or_above=False), 300_000_000)

    def test_gap_resets_confirmation(self):
        rows = [{"timestamp_ns": i * 20_000_000, "pose_speed_mps": .03}
                for i in range(5)]
        rows += [{"timestamp_ns": 300_000_000 + i * 20_000_000,
                  "pose_speed_mps": .03} for i in range(5)]
        self.assertIsNone(first_sustained(rows, threshold_mps=.015,
                                          duration_ms=200, at_or_above=True))

    def test_shutdown_stop_cannot_be_neural_stop(self):
        record = {"male_cns": {"healthy": True},
                  "dn_activity": {"runtime_healthy": True, "escape": .6},
                  "pre_safety_intent": {"stop": True},
                  "post_safety_intent": {"stop": True},
                  "watchdog_state": "healthy", "robot_facing_stop": True,
                  "robot_facing_command_type": "robot.stop",
                  "robotd_transport_result": "robot_stop_refreshed"}
        self.assertTrue(is_healthy_neural_stop(record, threshold=.5))
        record["watchdog_state"] = "safe_stop"
        self.assertFalse(is_healthy_neural_stop(record, threshold=.5))

    def test_timing_order_rejects_missing_or_reversed_stages(self):
        self.assertTrue(causal_timeline_ok(1, 2, 3, 3, 4))
        self.assertFalse(causal_timeline_ok(1, None, 3))
        self.assertFalse(causal_timeline_ok(1, 4, 3))

    def test_state_machine_requires_order_and_complete_path_for_pass(self):
        full = ["SETUP", "MOTION_PRECONDITION", "MOTION_CONFIRMED",
                "NEURAL_OBSERVATION_ARMED", "NEURAL_LOOMING", "NEURAL_STOP_DETECTED",
                "ROBOT_STOP_SENT", "ROBOT_STOP_ACK", "MOTION_STOPPED", "COMPLETE"]
        self.assertTrue(valid_state_path(full, complete=True))
        self.assertTrue(valid_state_path(full[:3], complete=False))
        self.assertFalse(valid_state_path(full[:3], complete=True))
        self.assertFalse(valid_state_path(full[:2] + ["NEURAL_LOOMING"], complete=False))

    def test_deadman_uses_conservative_move_call_start(self):
        good = deadman_timing(0, 20_000_000, 350_000_000,
                              timeout_ms=500, minimum_margin_ms=100)
        self.assertTrue(good["valid"])
        self.assertEqual(good["margin_from_call_ms"], 150)
        # The ACK-only age would misleadingly pass this case.
        bad = deadman_timing(0, 120_000_000, 430_000_000,
                             timeout_ms=500, minimum_margin_ms=100)
        self.assertFalse(bad["valid"])

    def test_missing_or_reversed_deadman_timing_is_invalid(self):
        self.assertFalse(deadman_timing(None, 1, 2, timeout_ms=500,
                                        minimum_margin_ms=100)["valid"])
        self.assertFalse(deadman_timing(2, 1, 3, timeout_ms=500,
                                        minimum_margin_ms=100)["valid"])

    def test_material_applied_baseline_rejects_near_zero(self):
        self.assertFalse(material_pre_stop_applied(.007, .04))
        self.assertTrue(material_pre_stop_applied(.07, .04))
        self.assertFalse(material_pre_stop_applied(math.nan, .04))

    def test_actual_stop_onset_must_precede_refreshed_deadman(self):
        self.assertTrue(stop_onset_before_deadman(499, 500, []))
        self.assertFalse(stop_onset_before_deadman(500, 500, []))
        self.assertFalse(stop_onset_before_deadman(490, 500, [{"timestamp_ns": 489}]))
        self.assertTrue(stop_onset_before_deadman(490, 500, [{"timestamp_ns": 501}]))

    def test_no_neural_graph_call_can_finish_after_stop_ack(self):
        ledger = [{"neural_call_started_ns": 10, "neural_call_returned_ns": 20}]
        self.assertTrue(neural_input_ended_by_ack(ledger, 21))
        self.assertFalse(neural_input_ended_by_ack(ledger, 20))
        self.assertFalse(neural_input_ended_by_ack([{"neural_call_started_ns": 10}], 21))

    def test_geometry_requires_strict_sphere_entry_margin(self):
        safe = safe_observation_horizon(.34, .07, .2, .03,
                                        observation_ms=780, margin_ms=150)
        self.assertTrue(safe["safe"])
        unsafe = safe_observation_horizon(.34, .07, .2, .03,
                                          observation_ms=1100, margin_ms=150)
        self.assertFalse(unsafe["safe"])

    def test_bounded_temporal_lineage_allows_reservoir_lag_but_no_missing_step(self):
        def row(step, ns, looming, lplc2, escape):
            return {"neural_call_timestamp_ns": ns, "result_none": False,
                    "input_none": False, "runtime_step": step, "graph_identity": "graph-v2",
                    "male_cns_healthy": True, "dn_sequence": step,
                    "dn_timestamp_ns": ns, "dn_runtime_healthy": True,
                    "dn_escape": escape, "perception_timestamp_ns": ns - 2_000_000,
                    "perception_frame_id": step, "perception_valid": True,
                    "looming": looming, "proximity_left": 0,
                    "proximity_center": 0, "proximity_right": 0,
                    "stimulus_channels": {"lplc2_left": lplc2,
                                          "lplc2_right": lplc2,
                                          "lc10a_left": .1, "lc10a_right": .1}}

        stop = {"identities": {"graph_identity": "graph-v2"},
                "male_cns": {"runtime_step": 14},
                "dn_activity": {"sequence": 14, "timestamp_ns": 42_000_000,
                                "escape": .6}}
        source = row(13, 20_000_000, 1, 1, .4)
        later = row(14, 42_000_000, 0, 0, .6)
        ok = bounded_neural_lineage([source, later], stop,
                                    max_age_ms=100, max_runtime_step_gap=5)
        self.assertTrue(ok["valid"])
        self.assertEqual(ok["observed_steps"], [13, 14])
        missing = bounded_neural_lineage([source, row(15, 42_000_000, 0, 0, .6)],
                                         {"identities": {"graph_identity": "graph-v2"},
                                          "male_cns": {"runtime_step": 15},
                                          "dn_activity": {"sequence": 15,
                                                          "timestamp_ns": 42_000_000,
                                                          "escape": .6}},
                                         max_age_ms=100, max_runtime_step_gap=5)
        self.assertFalse(missing["valid"])
        stale = row(14, 142_000_001, 0, 0, .6)
        stale["perception_timestamp_ns"] = 20_000_000
        bad = bounded_neural_lineage([source, stale],
                                     {"identities": {"graph_identity": "graph-v2"},
                                      "male_cns": {"runtime_step": 14},
                                      "dn_activity": {"sequence": 14,
                                                      "timestamp_ns": 142_000_001,
                                                      "escape": .6}},
                                     max_age_ms=100, max_runtime_step_gap=5)
        self.assertFalse(bad["valid"])


if __name__ == "__main__":
    unittest.main()
