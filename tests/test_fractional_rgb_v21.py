"""Contracts for the separate V2.1 RGB representation, without neural results."""

import unittest
from pathlib import Path

from microduck_connectome.camera_target import CameraTargetDetector, CameraTargetError
from microduck_connectome.fractional_rgb_v21 import FractionalRedTargetDetector, render_fractional_pixels
from microduck_connectome.looming_scenario import load_config, make_trial
from microduck_connectome.looming_v2 import LoomingEstimatorV2
from microduck_connectome.perception_compositor import PerceptionPipeline


ROOT = Path(__file__).resolve().parents[1]
POSE = {"x_m": 0.0, "y_m": 0.0, "heading_rad": 0.0, "trunk_z_m": 0.125}


class FractionalRGBV21Tests(unittest.TestCase):
    def test_weighted_area_and_centroid(self):
        pixels = (((0, 0, 0), (128, 0, 0), (255, 0, 0)),)
        frame = FractionalRedTargetDetector().detect(pixels, timestamp_ns=0, frame_id=1)
        self.assertAlmostEqual(frame["target_area"], 383 / (255 * 3))
        self.assertAlmostEqual(frame["target_x"], 2 * (128 + 2 * 255) / 383 / 2 - 1)
        self.assertTrue(frame["valid"])

    def test_binary_rgb_matches_legacy_area_and_centroid(self):
        pixels = (((255, 0, 0), (0, 0, 0), (255, 0, 0)),
                  ((0, 0, 0), (255, 0, 0), (0, 0, 0)))
        weighted = FractionalRedTargetDetector().detect(pixels, timestamp_ns=0, frame_id=1)
        legacy = CameraTargetDetector().detect(pixels, timestamp_ns=0, frame_id=1)
        self.assertEqual((weighted["target_area"], weighted["target_x"]),
                         (legacy["target_area"], legacy["target_x"]))

    def test_renderer_is_deterministic_and_stays_rgb_only(self):
        config = load_config(ROOT / "config/looming_scenario_v1.json")
        trial = make_trial(config, trial_id="fractional-unit", seed=1,
                           motion="static", initial_pose=POSE)
        first = render_fractional_pixels(config, trial, pose=POSE, elapsed_s=0)
        self.assertEqual(first, render_fractional_pixels(config, trial, pose=POSE, elapsed_s=0))
        self.assertEqual((len(first), len(first[0])),
                         (config["image_height_px"], config["image_width_px"]))
        self.assertTrue(any(0 < pixel[0] < 255 for row in first for pixel in row))
        self.assertTrue(all(pixel[1:] == (0, 0) for row in first for pixel in row))

    def test_injected_pipeline_static_stays_neutral(self):
        config = load_config(ROOT / "config/looming_scenario_v1.json")
        trial = make_trial(config, trial_id="fractional-static-unit", seed=1,
                           motion="static", initial_pose=POSE)
        pipeline = PerceptionPipeline(camera_detector=FractionalRedTargetDetector(),
                                      looming_estimator=LoomingEstimatorV2())
        for i in range(3):
            pixels = render_fractional_pixels(config, trial, pose=POSE, elapsed_s=i * 0.1)
            now = (i + 1) * 100_000_000
            frame = pipeline.process(
                pixels, camera_timestamp_ns=now, camera_frame_id=i + 1,
                tof_left_mm=2000, tof_center_mm=2000, tof_right_mm=2000,
                tof_timestamp_ns=now, tof_frame_id=i + 1, now_ns=now,
            )
            self.assertTrue(frame["valid"])
            self.assertEqual(frame["looming"], 0)

    def test_invalid_and_missing_rgb_are_neutral(self):
        detector = FractionalRedTargetDetector()
        missing = detector.detect((((0, 0, 0),),), timestamp_ns=0, frame_id=1)
        self.assertEqual((missing["target_area"], missing["confidence"]), (0, 0))
        lost = detector.detect((), timestamp_ns=0, frame_id=1, source_valid=False)
        self.assertFalse(lost["valid"])
        for pixels in ((), (((256, 0, 0),),), (((1, 2, 3),), ((1, 2, 3), (1, 2, 3)))):
            with self.subTest(pixels=pixels), self.assertRaises(CameraTargetError):
                detector.detect(pixels, timestamp_ns=0, frame_id=1)


if __name__ == "__main__":
    unittest.main()
