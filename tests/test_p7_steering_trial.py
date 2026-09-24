"""Check the actual-heading sustained response classifier."""

import unittest
from pathlib import Path

from scripts.p7_target_steering_trial import (
    initial_pose_matches, score_target_response, sustained_heading_response,
)
from microduck_connectome.steering_decoder import SteeringDecoder, load_steering_decoder_config
from microduck_connectome.target_scenario import load_target_scenario_config, make_target_trial


def records(headings):
    return [
        {"timestamp_ns": index * 20_000_000,
         "robot_state": {"heading_rad": heading}}
        for index, heading in enumerate(headings)
    ]


class SteeringResponseTests(unittest.TestCase):
    def test_versioned_p7_decoder_preserves_sign_and_bound(self):
        path = Path(__file__).resolve().parents[1] / "config/steering_decoder_p7_v1.json"
        decoder = SteeringDecoder(load_steering_decoder_config(path))
        readout = dict(timestamp_ns=1, sequence=1, steering_left=0.2,
                       steering_right=0.0, escape=0.0, runtime_healthy=True)
        self.assertEqual(decoder.decode(readout)["vyaw"], 0.5)

    def test_sustained_left_and_right(self):
        left = records([0.0] * 30 + [0.003 * index for index in range(20)])
        right = records([0.0] * 30 + [-0.003 * index for index in range(20)])
        self.assertEqual(sustained_heading_response(left, stimulus_ns=600_000_000)["direction"], "left")
        self.assertEqual(sustained_heading_response(right, stimulus_ns=600_000_000)["direction"], "right")

    def test_noise_spike_and_stationary_are_no_response(self):
        stationary = records([0.0] * 50)
        spike = records([0.0] * 30 + [0.03, 0.0] + [0.0] * 18)
        self.assertIsNone(sustained_heading_response(stationary, stimulus_ns=600_000_000))
        self.assertIsNone(sustained_heading_response(spike, stimulus_ns=600_000_000))

    def test_crossing_scores_bearing_at_response_not_initial_side(self):
        root = Path(__file__).resolve().parents[1]
        config = load_target_scenario_config(root / "config/target_scenario_v1.json")
        trial = make_target_trial(
            config, trial_id="crossing", seed=1, target_present=True,
            target_side="left", target_eccentricity="far", target_motion="slow_crossing",
            visual_noise_level="clean", initial_robot_heading_rad=0.0,
        )
        row = {"timestamp_ns": 2_200_000_000,
               "robot_state": {"heading_rad": 0.0},
               "perception": {"target_area": 0.03}}
        right, enriched = score_target_response(
            config, trial, {"direction": "right"}, row,
            started_ns=0, center_tolerance_rad=0.05,
        )
        left, _ = score_target_response(
            config, trial, {"direction": "left"}, row,
            started_ns=0, center_tolerance_rad=0.05,
        )
        self.assertEqual((right, left), ("correct", "incorrect"))
        self.assertEqual(enriched["target_side_at_response"], "right")

    def test_pose_reset_tolerance_rejects_drift(self):
        reference = dict(heading_rad=0.1188, trunk_z_m=0.1159,
                         heading_tolerance_rad=0.02, trunk_z_tolerance_m=0.01)
        self.assertTrue(initial_pose_matches(dict(heading_rad=0.117, trunk_z=0.116), reference))
        self.assertFalse(initial_pose_matches(dict(heading_rad=0.21, trunk_z=0.116), reference))


if __name__ == "__main__":
    unittest.main()
