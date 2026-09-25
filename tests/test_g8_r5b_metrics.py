import math
import unittest

from microduck_connectome.g8_r5b_metrics import (
    causal_timeline_ok, first_sustained, is_healthy_neural_stop, pose_speeds,
    valid_state_path,
)


class G8R5bMetricsTests(unittest.TestCase):
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
                "NEURAL_LOOMING", "NEURAL_STOP_DETECTED", "STOP_TRANSPORT_ACK",
                "MOTION_STOPPED", "COMPLETE"]
        self.assertTrue(valid_state_path(full, complete=True))
        self.assertTrue(valid_state_path(full[:3], complete=False))
        self.assertFalse(valid_state_path(full[:3], complete=True))
        self.assertFalse(valid_state_path(full[:2] + ["NEURAL_LOOMING"], complete=False))


if __name__ == "__main__":
    unittest.main()
