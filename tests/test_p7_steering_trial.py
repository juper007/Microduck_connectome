"""Check the actual-heading sustained response classifier."""

import unittest

from scripts.p7_target_steering_trial import sustained_heading_response


def records(headings):
    return [
        {"timestamp_ns": index * 20_000_000,
         "robot_state": {"heading_rad": heading}}
        for index, heading in enumerate(headings)
    ]


class SteeringResponseTests(unittest.TestCase):
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
