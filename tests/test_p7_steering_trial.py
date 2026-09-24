"""Check the actual-heading sustained response classifier."""

import unittest
from pathlib import Path

from scripts.p7_target_steering_trial import sustained_heading_response
from microduck_connectome.steering_decoder import SteeringDecoder, load_steering_decoder_config


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


if __name__ == "__main__":
    unittest.main()
