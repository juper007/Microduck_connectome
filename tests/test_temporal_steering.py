"""Regression checks for the measured P7 DNa02 pulse-gap failure."""

import json
from pathlib import Path
import unittest

from microduck_connectome.steering_decoder import SteeringDecoder, SteeringDecoderConfig
from microduck_connectome.safety_clamp import SafetyClamp
from microduck_connectome.temporal_steering import (
    P7TemporalSteeringDecoder, load_temporal_steering_config,
)


ROOT = Path(__file__).resolve().parents[1]


def frame(timestamp_ns, *, visible=True, valid=True):
    return {"timestamp_ns": timestamp_ns, "target_area": 0.04 if visible else 0.0,
            "valid": valid}


def readout(timestamp_ns, sequence, *, left=0.0, right=0.0, healthy=True):
    return {"timestamp_ns": timestamp_ns, "sequence": sequence,
            "steering_left": left, "steering_right": right, "escape": 0.0,
            "runtime_healthy": healthy}


class P7TemporalSteeringTests(unittest.TestCase):
    def setUp(self):
        self.config = load_temporal_steering_config(
            ROOT / "config/steering_temporal_p7_v1.json")
        self.decoder = P7TemporalSteeringDecoder(
            SteeringDecoder(SteeringDecoderConfig(-1, 2.5, 0.5)), self.config)

    def decode_at(self, milliseconds, sequence, *, visible=True, valid=True,
                  left=0.0, right=0.0, healthy=True):
        timestamp = milliseconds * 1_000_000
        self.decoder.observe_frame(frame(timestamp, visible=visible, valid=valid),
                                   now_ns=timestamp)
        return self.decoder.decode(readout(timestamp, sequence, left=left,
                                           right=right, healthy=healthy))

    def test_bridges_measured_282ms_static_target_gap_then_expires(self):
        first = self.decode_at(0, 1, left=0.2)
        bridged = self.decode_at(282, 2)
        expired = self.decode_at(322, 3)
        self.assertEqual((first["vyaw"], bridged["vyaw"], expired["vyaw"]),
                         (0.5, 0.5, 0.0))
        self.assertFalse(bridged["stop"])

    def test_opposite_dn_evidence_switches_direction_without_hold_delay(self):
        self.assertEqual(self.decode_at(0, 1, left=0.2)["vyaw"], 0.5)
        self.assertEqual(self.decode_at(280, 2, right=0.2)["vyaw"], -0.5)
        self.assertEqual(self.decode_at(500, 3)["vyaw"], -0.5)

    def test_measured_pulse_train_reaches_frozen_safety_slew_limit(self):
        safety = SafetyClamp()
        safe_yaws = []
        for index, milliseconds in enumerate(range(0, 1000, 20), 1):
            active = any(start <= milliseconds < start + 100
                         for start in (0, 380, 760))
            intent = self.decode_at(milliseconds, index,
                                    left=0.2 if active else 0.0)
            result = safety.apply(intent, now_ns=milliseconds * 1_000_000,
                                  fallback_sequence=index)
            safe_yaws.append(result["intent"]["vyaw"])
        self.assertEqual(max(safe_yaws), 0.5)
        self.assertGreater(min(safe_yaws[18:]), 0.0)
        stopped = self.decode_at(1000, 51, visible=False)
        self.assertTrue(safety.apply(stopped, now_ns=1_000_000_000,
                                     fallback_sequence=51)["intent"]["stop"])

    def test_target_loss_and_invalid_frame_stop_and_clear_hold(self):
        self.decode_at(0, 1, left=0.2)
        absent = self.decode_at(20, 2, visible=False, left=0.2)
        self.assertEqual(absent["vyaw"], 0.0)
        self.assertTrue(absent["stop"])
        self.assertEqual(self.decode_at(40, 3)["vyaw"], 0.0)
        self.decode_at(60, 4, right=0.2)
        invalid = self.decode_at(80, 5, valid=False)
        self.assertTrue(invalid["stop"])
        self.assertEqual(invalid["vyaw"], 0.0)

    def test_unhealthy_runtime_stops_and_clears_hold(self):
        self.decode_at(0, 1, left=0.2)
        unhealthy = self.decode_at(20, 2, healthy=False)
        self.assertTrue(unhealthy["stop"])
        self.assertEqual(self.decode_at(40, 3)["vyaw"], 0.0)

    def test_stale_visual_frame_stops(self):
        self.decoder.observe_frame(frame(0), now_ns=101_000_000)
        result = self.decoder.decode(readout(101_000_000, 1, left=0.2))
        self.assertTrue(result["stop"])

    def test_config_is_versioned_and_bounded(self):
        self.assertEqual(self.config["hold_ms"], 320)
        self.assertEqual(self.config["target_ttl_ms"], 100)
        raw = json.loads((ROOT / "config/steering_temporal_p7_v1.json").read_text())
        self.assertEqual(raw["schema_version"], "p7-temporal-steering-v1")


if __name__ == "__main__":
    unittest.main()
