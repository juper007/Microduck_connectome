"""P7 gain is bounded, lateralized, fresh-only, and target-only."""

from pathlib import Path
import unittest

from microduck_connectome.perception_frame import make_perception_frame
from microduck_connectome.sensory_mapping import load_sensory_mapping_config
from microduck_connectome.target_stimulus_gain import (
    TargetDriveSensoryMapper, TargetGainSensoryMapper,
    load_target_stimulus_drive, load_target_stimulus_gain,
)


ROOT = Path(__file__).resolve().parents[1]


class TargetStimulusGainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sensory = load_sensory_mapping_config(ROOT / "config/sensory_mapping_v1.json")
        gain = load_target_stimulus_gain(ROOT / "config/target_stimulus_gain_v1.json")
        ids = tuple(sorted(body_id for spec in sensory["populations"].values()
                           for body_id in spec["body_ids"]))
        cls.mapper = TargetGainSensoryMapper(ids, sensory, gain)

    def frame(self, **changes):
        values = dict(timestamp_ns=1_000_000_000, frame_id=1, target_x=-0.5,
                      target_area=0.035, looming=0.0, proximity_left=0.0,
                      proximity_center=0.0, proximity_right=0.0,
                      confidence=1.0, valid=True)
        values.update(changes)
        return make_perception_frame(**values)

    def test_left_target_amplifies_lc10a_without_changing_looming(self):
        channels = self.mapper.map_channels(self.frame(looming=0.2), now_ns=1_000_000_000)
        self.assertAlmostEqual(channels["lc10a_left"], 0.7875)
        self.assertAlmostEqual(channels["lc10a_right"], 0.2625)
        self.assertEqual((channels["lplc2_left"], channels["lplc2_right"]), (0.2, 0.2))

    def test_bound_and_neutrality(self):
        saturated = self.mapper.map_channels(self.frame(target_area=1.0), now_ns=1_000_000_000)
        self.assertLessEqual(max(saturated.values()), 1.0)
        invalid = self.mapper.build_external(self.frame(valid=False), now_ns=1_000_000_000)
        stale = self.mapper.build_external(self.frame(), now_ns=1_100_000_001)
        no_target = self.mapper.build_external(self.frame(target_area=0.0), now_ns=1_000_000_000)
        self.assertEqual((invalid, stale, no_target), ({}, {}, {}))

    def test_v2_side_drive_is_bounded_and_neutral_when_stale(self):
        sensory = load_sensory_mapping_config(ROOT / "config/sensory_mapping_v1.json")
        drive = load_target_stimulus_drive(ROOT / "config/target_stimulus_drive_v2.json")
        ids = tuple(sorted(body_id for spec in sensory["populations"].values()
                           for body_id in spec["body_ids"]))
        mapper = TargetDriveSensoryMapper(ids, sensory, drive)
        left = mapper.map_channels(self.frame(target_x=-0.17), now_ns=1_000_000_000)
        right = mapper.map_channels(self.frame(target_x=0.17), now_ns=1_000_000_000)
        self.assertEqual((left["lc10a_left"], left["lc10a_right"]), (1.0, 0.0))
        self.assertEqual((right["lc10a_left"], right["lc10a_right"]), (0.0, 1.0))
        self.assertEqual(mapper.build_external(self.frame(), now_ns=1_100_000_001), {})
        self.assertEqual(mapper.build_external(self.frame(target_area=0.0), now_ns=1_000_000_000), {})

    def test_v3_drives_moderate_noise_target_at_bounded_amplitude(self):
        sensory = load_sensory_mapping_config(ROOT / "config/sensory_mapping_v1.json")
        drive = load_target_stimulus_drive(ROOT / "config/target_stimulus_drive_v3.json")
        ids = tuple(sorted(body_id for spec in sensory["populations"].values()
                           for body_id in spec["body_ids"]))
        mapper = TargetDriveSensoryMapper(ids, sensory, drive)
        channels = mapper.map_channels(
            self.frame(target_x=0.75, target_area=0.028), now_ns=1_000_000_000,
        )
        self.assertEqual((channels["lc10a_left"], channels["lc10a_right"]), (0.0, 1.0))


if __name__ == "__main__":
    unittest.main()
