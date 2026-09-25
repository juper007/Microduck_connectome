import json
from pathlib import Path
import unittest

from microduck_connectome.looming_scenario import (
    LoomingScenarioError, evaluator_truth, load_config, make_trial,
    pixels_sha256, render_pixels, validate_pose,
)
from microduck_connectome.perception_compositor import PerceptionPipeline

ROOT = Path(__file__).resolve().parents[1]
CONFIG = load_config(ROOT / "config/looming_scenario_v1.json")
POSE = {"x_m": 0.0, "y_m": 0.0, "heading_rad": 0.0, "trunk_z_m": 0.125}


class LoomingScenarioTests(unittest.TestCase):
    def test_manifest_and_boundary_frozen(self):
        manifest = json.loads((ROOT / "config/looming_scenario_smoke_v1.json").read_text())
        self.assertEqual([v["motion"] for v in manifest["trials"]], ["approaching", "static", "receding"])
        self.assertEqual(len({v["seed"] for v in manifest["trials"]}), 3)
        self.assertAlmostEqual(CONFIG["safety_boundary_center_distance_m"], 0.25)

    def test_replay_reset_and_separation(self):
        trial = make_trial(CONFIG, trial_id="x", seed=80101, motion="approaching", initial_pose=POSE)
        again = make_trial(CONFIG, trial_id="x", seed=80101, motion="approaching", initial_pose=POSE)
        self.assertEqual(trial, again)
        pixels = render_pixels(CONFIG, trial, pose=POSE, elapsed_s=1.2)
        self.assertEqual(pixels_sha256(pixels), pixels_sha256(render_pixels(CONFIG, again, pose=POSE, elapsed_s=1.2)))
        truth = evaluator_truth(CONFIG, trial, pose=POSE, elapsed_s=1.2)
        self.assertTrue(set(truth).isdisjoint({"target_x", "target_area", "looming"}))
        # PerceptionPipeline receives RGB pixels and far ToF only.
        frame = PerceptionPipeline().process(
            pixels, camera_timestamp_ns=1_000_000_000, camera_frame_id=1,
            tof_left_mm=CONFIG["tof_mm"], tof_center_mm=CONFIG["tof_mm"],
            tof_right_mm=CONFIG["tof_mm"], tof_timestamp_ns=1_000_000_000,
            tof_frame_id=1, now_ns=1_000_000_000)
        self.assertTrue(frame["valid"])
        self.assertGreater(frame["target_area"], 0)
        self.assertNotIn("center_distance_m", frame)

    def test_distance_and_pixels_monotonic_at_fixed_robot_pose(self):
        expected = {"approaching": -1, "static": 0, "receding": 1}
        for motion, sign in expected.items():
            trial = make_trial(CONFIG, trial_id=motion, seed=80101, motion=motion, initial_pose=POSE)
            distances = [evaluator_truth(CONFIG, trial, pose=POSE, elapsed_s=t)["distance_to_boundary_m"] for t in (0.5, 1.5, 2.5)]
            self.assertEqual((distances[-1] > distances[0]) - (distances[-1] < distances[0]), sign)
            areas = [sum(pixel == (255, 0, 0) for row in render_pixels(CONFIG, trial, pose=POSE, elapsed_s=t) for pixel in row) for t in (0.5, 1.5, 2.5)]
            if sign < 0:
                self.assertGreater(areas[-1], areas[0])
            elif sign > 0:
                self.assertLessEqual(areas[-1], areas[0])
            else:
                self.assertEqual(areas[-1], areas[0])

    def test_pose_truth_is_measured_and_fail_closed(self):
        trial = make_trial(CONFIG, trial_id="x", seed=1, motion="static", initial_pose=POSE)
        moved = dict(POSE, x_m=0.1)
        self.assertLess(evaluator_truth(CONFIG, trial, pose=moved, elapsed_s=1)["center_distance_m"],
                        evaluator_truth(CONFIG, trial, pose=POSE, elapsed_s=1)["center_distance_m"])
        with self.assertRaises(LoomingScenarioError):
            validate_pose(dict(POSE, x_m=float("nan")))
        with self.assertRaises(LoomingScenarioError):
            render_pixels(CONFIG, trial, pose={"heading_rad": 0}, elapsed_s=1)


if __name__ == "__main__":
    unittest.main()
