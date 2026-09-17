import unittest

from microduck_connectome.camera_target import CameraTargetConfig, CameraTargetDetector, CameraTargetError


B = (0, 0, 0)
R = (255, 0, 0)


class CameraTargetTests(unittest.TestCase):
    def setUp(self):
        self.detector = CameraTargetDetector()

    def test_left_center_right_coordinate_convention(self):
        cases = [
            ([[R, B, B]], -1.0),
            ([[B, R, B]], 0.0),
            ([[B, B, R]], 1.0),
        ]
        for frame, expected in cases:
            with self.subTest(expected=expected):
                result = self.detector.detect(frame, timestamp_ns=10, frame_id=1)
                self.assertEqual(result["target_x"], expected)
                self.assertTrue(result["valid"])

    def test_area_is_bounded_fraction(self):
        frame = [[R, R], [B, B]]
        result = self.detector.detect(frame, timestamp_ns=1, frame_id=2)
        self.assertEqual(result["target_area"], 0.5)
        self.assertEqual(result["confidence"], 1.0)
        self.assertGreaterEqual(result["target_x"], -1.0)
        self.assertLessEqual(result["target_x"], 1.0)

    def test_no_target_is_neutral_not_last_value(self):
        first = self.detector.detect([[B, B, R]], timestamp_ns=1, frame_id=1)
        second = self.detector.detect([[B, B, B]], timestamp_ns=2, frame_id=2)
        self.assertEqual(first["target_x"], 1.0)
        self.assertEqual(second["target_x"], 0.0)
        self.assertEqual(second["target_area"], 0.0)
        self.assertEqual(second["confidence"], 0.0)
        self.assertTrue(second["valid"])

    def test_invalid_source_is_neutral_and_does_not_require_frame(self):
        result = self.detector.detect(None, timestamp_ns=3, frame_id=4, source_valid=False)
        self.assertFalse(result["valid"])
        self.assertEqual(result["target_x"], 0.0)
        self.assertEqual(result["target_area"], 0.0)

    def test_tolerance_and_min_pixels(self):
        detector = CameraTargetDetector(CameraTargetConfig(target_rgb=R, tolerance=5, min_pixels=2))
        result = detector.detect([[(251, 3, 2), R, B]], timestamp_ns=1, frame_id=1)
        self.assertEqual(result["target_area"], 2 / 3)
        missing = detector.detect([[R, B, B]], timestamp_ns=2, frame_id=2)
        self.assertEqual(missing["target_area"], 0.0)

    def test_malformed_frames_fail_clearly(self):
        for frame in (None, [], [[R], [R, R]], [[(256, 0, 0)]], [["rgb"]]):
            with self.subTest(frame=frame):
                with self.assertRaises(CameraTargetError):
                    self.detector.detect(frame, timestamp_ns=1, frame_id=1)

    def test_config_validation(self):
        for config in (
            {"target_rgb": (256, 0, 0)},
            {"target_rgb": (True, 0, 0)},
            {"tolerance": -1},
            {"min_pixels": 0},
        ):
            with self.subTest(config=config):
                with self.assertRaises(CameraTargetError):
                    CameraTargetConfig(**config)


if __name__ == "__main__":
    unittest.main()
