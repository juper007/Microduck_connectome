import json
import math
from pathlib import Path
import unittest

from microduck_connectome.steering_decoder import (
    SteeringDecoder,
    SteeringDecoderConfig,
    SteeringDecoderError,
    load_steering_decoder_config,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "steering_decoder_v1.json"


def readout(left=0.0, right=0.0, *, healthy=True):
    return {
        "timestamp_ns": 10,
        "sequence": 2,
        "steering_left": left,
        "steering_right": right,
        "escape": 0.0,
        "runtime_healthy": healthy,
    }


class SteeringDecoderTests(unittest.TestCase):
    def test_committed_config_is_explicitly_uncalibrated(self):
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        self.assertIsNone(raw["steering_yaw_sign"])
        config = load_steering_decoder_config(CONFIG_PATH)
        with self.assertRaises(SteeringDecoderError):
            SteeringDecoder(config).decode(readout(right=1.0))

    def test_abstract_demand_uses_right_minus_left(self):
        decoder = SteeringDecoder(SteeringDecoderConfig(1, 0.5))
        self.assertEqual(decoder.abstract_demand(readout(left=1.0)), -1.0)
        self.assertEqual(decoder.abstract_demand(readout(right=1.0)), 1.0)
        self.assertEqual(decoder.abstract_demand(readout(left=0.4, right=0.4)), 0.0)

    def test_zero_and_equal_activity_are_neutral(self):
        decoder = SteeringDecoder(SteeringDecoderConfig(1, 0.5))
        for sample in (readout(), readout(left=0.8, right=0.8)):
            result = decoder.decode(sample)
            self.assertEqual(result["vyaw"], 0.0)
            self.assertEqual(result["vy"], 0.0)

    def test_yaw_sign_inverts_direction_exactly(self):
        sample = readout(left=0.2, right=0.8)
        positive = SteeringDecoder(SteeringDecoderConfig(1, 0.5)).decode(sample)
        negative = SteeringDecoder(SteeringDecoderConfig(-1, 0.5)).decode(sample)
        self.assertAlmostEqual(positive["vyaw"], 0.3)
        self.assertAlmostEqual(negative["vyaw"], -0.3)
        self.assertAlmostEqual(positive["vyaw"], -negative["vyaw"])

    def test_high_gain_saturates_at_frozen_limit(self):
        decoder = SteeringDecoder(SteeringDecoderConfig(1, 10.0, 0.5))
        self.assertEqual(decoder.decode(readout(right=1.0))["vyaw"], 0.5)
        self.assertEqual(decoder.decode(readout(left=1.0))["vyaw"], -0.5)

    def test_unhealthy_runtime_is_neutral_even_when_sign_uncalibrated(self):
        decoder = SteeringDecoder(SteeringDecoderConfig(None, 0.5))
        result = decoder.decode(readout(left=1.0, healthy=False))
        self.assertEqual((result["vx"], result["vy"], result["vyaw"]), (0.0, 0.0, 0.0))
        self.assertEqual(result["confidence"], 0.0)

    def test_invalid_neural_activity_is_rejected(self):
        for value in (-0.1, 1.1, math.nan, math.inf, True):
            with self.subTest(value=value):
                sample = readout()
                sample["steering_left"] = value
                with self.assertRaises(SteeringDecoderError):
                    SteeringDecoder(SteeringDecoderConfig(1, 0.5)).decode(sample)

    def test_config_validation(self):
        for args in (
            (0, 0.5, 0.5),
            (True, 0.5, 0.5),
            (1, 0.0, 0.5),
            (1, math.inf, 0.5),
            (1, 0.5, 0.51),
        ):
            with self.subTest(args=args):
                with self.assertRaises(SteeringDecoderError):
                    SteeringDecoderConfig(*args)

    def test_deterministic_output(self):
        decoder = SteeringDecoder(SteeringDecoderConfig(1, 0.5))
        sample = readout(left=0.25, right=0.75)
        self.assertEqual(decoder.decode(sample), decoder.decode(sample))


if __name__ == "__main__":
    unittest.main()
