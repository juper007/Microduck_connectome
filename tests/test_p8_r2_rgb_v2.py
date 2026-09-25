"""P8-R2 visual representation checks, independent of final benchmark seeds."""

import copy
from pathlib import Path
import unittest

from microduck_connectome.looming_scenario import (
    LoomingScenarioError, evaluator_truth, load_config, make_trial, pixels_sha256,
    render_pixels,
)
from microduck_connectome.perception_compositor import PerceptionPipeline
from microduck_connectome.sensory_mapping import SensoryMapper, load_sensory_mapping_config


ROOT = Path(__file__).resolve().parents[1]
OLD = load_config(ROOT / "config/looming_scenario_v1.json")
NEW = load_config(ROOT / "config/looming_scenario_rgb_v2.json")
POSE = {"x_m": 0.0, "y_m": 0.0, "heading_rad": 0.0, "trunk_z_m": 0.125}


class P8R2RGBTests(unittest.TestCase):
    def test_only_resolution_and_version_change(self):
        self.assertEqual((NEW["image_width_px"], NEW["image_height_px"]), (129, 65))
        for key in OLD:
            if key not in ("schema_version", "image_width_px", "image_height_px"):
                self.assertEqual(OLD[key], NEW[key], key)
        self.assertEqual(NEW["safety_boundary_center_distance_m"], 0.25)

    def test_versioned_resolution_is_fixed(self):
        from tempfile import TemporaryDirectory
        import json
        with TemporaryDirectory() as tmp:
            bad = copy.deepcopy(NEW)
            bad["image_width_px"] = 65
            path = Path(tmp) / "bad.json"
            path.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaises(LoomingScenarioError):
                load_config(path)

    def test_pixels_change_but_evaluator_geometry_does_not(self):
        for motion in ("approaching", "static", "receding"):
            old_trial = make_trial(OLD, trial_id=motion, seed=884204, motion=motion, initial_pose=POSE)
            new_trial = make_trial(NEW, trial_id=motion, seed=884204, motion=motion, initial_pose=POSE)
            self.assertEqual(old_trial, new_trial)
            for elapsed in (0.5, 1.5, 2.5):
                self.assertEqual(
                    evaluator_truth(OLD, old_trial, pose=POSE, elapsed_s=elapsed),
                    evaluator_truth(NEW, new_trial, pose=POSE, elapsed_s=elapsed),
                )
                old_pixels = render_pixels(OLD, old_trial, pose=POSE, elapsed_s=elapsed)
                new_pixels = render_pixels(NEW, new_trial, pose=POSE, elapsed_s=elapsed)
                self.assertEqual(len(old_pixels), 33)
                self.assertEqual(len(new_pixels), 65)
                self.assertNotEqual(pixels_sha256(old_pixels), pixels_sha256(new_pixels))
                self.assertEqual(new_pixels, render_pixels(NEW, new_trial, pose=POSE, elapsed_s=elapsed))

    def test_rgb_derived_lplc2_and_loss_neutral(self):
        config = load_sensory_mapping_config(ROOT / "config/sensory_mapping_v1.json")
        ids = sorted({body_id for pop in config["populations"].values() for body_id in pop["body_ids"]})
        mapper = SensoryMapper(ids, config)
        trial = make_trial(NEW, trial_id="approach", seed=884201, motion="approaching", initial_pose=POSE)
        pipeline = PerceptionPipeline()
        positive = None
        for index in range(66):
            now = index * 40_000_000
            pixels = render_pixels(NEW, trial, pose=POSE, elapsed_s=0.5 + index * 0.04)
            frame = pipeline.process(
                pixels, camera_timestamp_ns=now, camera_frame_id=index + 1,
                tof_left_mm=NEW["tof_mm"], tof_center_mm=NEW["tof_mm"],
                tof_right_mm=NEW["tof_mm"], tof_timestamp_ns=now,
                tof_frame_id=index + 1, now_ns=now,
            )
            channels = mapper.map_channels(frame, now_ns=now)
            self.assertEqual(channels["lplc2_left"], frame["looming"])
            self.assertEqual(channels["lplc2_right"], frame["looming"])
            if frame["looming"] > 0 and positive is None:
                positive = frame
        self.assertIsNotNone(positive)
        self.assertTrue(mapper.build_external(positive, now_ns=positive["timestamp_ns"]))
        self.assertEqual(mapper.build_external(positive, now_ns=positive["timestamp_ns"] + 100_000_001), {})

        now += 40_000_000
        invalid = pipeline.process(
            (), camera_timestamp_ns=now, camera_frame_id=67,
            tof_left_mm=NEW["tof_mm"], tof_center_mm=NEW["tof_mm"],
            tof_right_mm=NEW["tof_mm"], tof_timestamp_ns=now,
            tof_frame_id=67, now_ns=now, camera_source_valid=False,
        )
        self.assertFalse(invalid["valid"])
        self.assertEqual(invalid["looming"], 0.0)
        self.assertEqual(mapper.build_external(invalid, now_ns=now), {})

    def test_stationary_and_receding_no_positive_looming(self):
        for motion, seed in (("static", 884204), ("receding", 884205)):
            with self.subTest(motion=motion):
                trial = make_trial(NEW, trial_id=motion, seed=seed, motion=motion, initial_pose=POSE)
                pipeline = PerceptionPipeline()
                for index in range(66):
                    now = index * 40_000_000
                    frame = pipeline.process(
                        render_pixels(NEW, trial, pose=POSE, elapsed_s=0.5 + index * 0.04),
                        camera_timestamp_ns=now, camera_frame_id=index + 1,
                        tof_left_mm=NEW["tof_mm"], tof_center_mm=NEW["tof_mm"],
                        tof_right_mm=NEW["tof_mm"], tof_timestamp_ns=now,
                        tof_frame_id=index + 1, now_ns=now,
                    )
                    self.assertEqual(frame["looming"], 0.0)


if __name__ == "__main__":
    unittest.main()
