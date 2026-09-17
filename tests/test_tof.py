import math
import unittest

from microduck_connectome.tof import ToFConfig, ToFError, ToFProximityEncoder


class ToFTests(unittest.TestCase):
    def setUp(self):
        self.encoder = ToFProximityEncoder(ToFConfig(near_mm=100, far_mm=1000))

    def test_near_mid_far_mapping_is_bounded(self):
        result = self.encoder.encode(
            left_mm=100,
            center_mm=550,
            right_mm=1000,
            timestamp_ns=1,
            frame_id=2,
        )
        self.assertEqual(result["proximity_left"], 1.0)
        self.assertEqual(result["proximity_center"], 0.5)
        self.assertEqual(result["proximity_right"], 0.0)
        for key in ("proximity_left", "proximity_center", "proximity_right"):
            self.assertGreaterEqual(result[key], 0.0)
            self.assertLessEqual(result[key], 1.0)

    def test_distances_clamp_outside_calibration_span(self):
        result = self.encoder.encode(
            left_mm=50,
            center_mm=100,
            right_mm=5000,
            timestamp_ns=1,
            frame_id=1,
        )
        self.assertEqual(result["proximity_left"], 1.0)
        self.assertEqual(result["proximity_center"], 1.0)
        self.assertEqual(result["proximity_right"], 0.0)

    def test_explicit_side_order_is_preserved(self):
        result = self.encoder.encode(
            left_mm=1000,
            center_mm=550,
            right_mm=100,
            timestamp_ns=1,
            frame_id=1,
        )
        self.assertEqual(
            (result["proximity_left"], result["proximity_center"], result["proximity_right"]),
            (0.0, 0.5, 1.0),
        )

    def test_any_sensor_loss_is_fully_neutral_and_invalid(self):
        for missing in ("left_mm", "center_mm", "right_mm"):
            kwargs = dict(left_mm=200, center_mm=300, right_mm=400)
            kwargs[missing] = None
            with self.subTest(missing=missing):
                result = self.encoder.encode(**kwargs, timestamp_ns=2, frame_id=3)
                self.assertFalse(result["valid"])
                self.assertEqual(result["proximity_left"], 0.0)
                self.assertEqual(result["proximity_center"], 0.0)
                self.assertEqual(result["proximity_right"], 0.0)

    def test_invalid_source_does_not_require_readings(self):
        result = self.encoder.encode(
            left_mm=None,
            center_mm=None,
            right_mm=None,
            timestamp_ns=3,
            frame_id=4,
            source_valid=False,
        )
        self.assertFalse(result["valid"])
        self.assertEqual(result["confidence"], 0.0)

    def test_loss_never_replays_previous_values(self):
        first = self.encoder.encode(
            left_mm=100,
            center_mm=100,
            right_mm=100,
            timestamp_ns=1,
            frame_id=1,
        )
        lost = self.encoder.encode(
            left_mm=None,
            center_mm=100,
            right_mm=100,
            timestamp_ns=2,
            frame_id=2,
        )
        self.assertEqual(first["proximity_left"], 1.0)
        self.assertEqual(lost["proximity_left"], 0.0)
        self.assertFalse(lost["valid"])

    def test_bad_distances_and_config_are_rejected(self):
        for value in (0, -1, math.nan, math.inf, True, "100"):
            with self.subTest(value=value):
                with self.assertRaises(ToFError):
                    self.encoder.encode(
                        left_mm=value,
                        center_mm=200,
                        right_mm=200,
                        timestamp_ns=1,
                        frame_id=1,
                    )
        for config in (
            {"near_mm": 0},
            {"far_mm": math.inf},
            {"near_mm": 1000, "far_mm": 100},
            {"near_mm": 100, "far_mm": 100},
        ):
            with self.subTest(config=config):
                with self.assertRaises(ToFError):
                    ToFConfig(**config)


if __name__ == "__main__":
    unittest.main()
