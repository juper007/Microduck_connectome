"""Development arm matrices remain bounded and disjoint from P8 final seeds."""

import json
from pathlib import Path
import unittest

from microduck_connectome.g8_r5d_metrics import safe_observation_horizon


ROOT = Path(__file__).resolve().parents[1]


class EarlyProbeProtocolTest(unittest.TestCase):
    def test_dev_arm_matrices_and_camera_entry_bound(self):
        scenario = json.loads((ROOT / "config/looming_scenario_v1.json").read_text())
        for version in (1, 2):
            protocol = json.loads((ROOT / f"config/p8_early_trigger_probe_v{version}.json").read_text())
            self.assertEqual(protocol["schema_version"], f"p8-v2-early-trigger-development-v{version}")
            self.assertEqual(len(protocol["scenario_seeds"]), len(protocol["arm_elapsed_s"]))
            self.assertEqual(protocol["stop_transport"], "robot_stop")
            self.assertEqual(protocol["graph_sha256"],
                             "c4160c42941163079b6b569d117bf67afcf8b45eaa128c444f7c96c2567593cc")
            for seed, arm in zip(protocol["scenario_seeds"], protocol["arm_elapsed_s"]):
                self.assertTrue(880900 <= seed < 881000)
                initial_distance = scenario["initial_center_distance_m"] - scenario["approach_speed_m_s"] * arm
                self.assertGreater(initial_distance, scenario["safety_boundary_center_distance_m"])
                horizon = safe_observation_horizon(
                    initial_distance, scenario["virtual_sphere_radius_m"],
                    scenario["approach_speed_m_s"], protocol["maximum_robot_forward_displacement_m"],
                    observation_ms=protocol["max_neural_observation_duration_ms"],
                    margin_ms=protocol["sphere_entry_safety_margin_ms"])
                self.assertTrue(horizon["safe"])


if __name__ == "__main__":
    unittest.main()
