import json
from pathlib import Path
import unittest

from microduck_connectome.perception_frame import make_perception_frame
from microduck_connectome.sensory_mapping import (
    SensoryMapper,
    load_sensory_mapping_config,
    sensory_mapping_config_sha256,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "sensory_mapping_v1.json"
TRACKING_PATH = ROOT / "docs" / "evidence" / "p2-05" / "tracking-selection-v1.json"
LOOMING_PATH = ROOT / "docs" / "evidence" / "p2-01" / "direct-evidence-v1.json"


def runtime_ids(config):
    return tuple(sorted(
        body_id
        for spec in config["populations"].values()
        for body_id in spec["body_ids"]
    ))


class SensoryMappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_sensory_mapping_config(CONFIG_PATH)
        cls.mapper = SensoryMapper(runtime_ids(cls.config), cls.config)

    def frame(self, **changes):
        values = dict(
            timestamp_ns=1_000_000_000,
            frame_id=1,
            target_x=0.0,
            target_area=0.0,
            looming=0.0,
            proximity_left=0.0,
            proximity_center=0.0,
            proximity_right=0.0,
            confidence=1.0,
            valid=True,
        )
        values.update(changes)
        return make_perception_frame(**values)

    def test_config_ids_match_phase2_evidence_exactly(self):
        tracking = json.loads(TRACKING_PATH.read_text(encoding="utf-8"))
        direct = json.loads(LOOMING_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            self.config["populations"]["lc10a_left"]["body_ids"],
            tracking["config"]["input_ids_by_soma_side"]["left"],
        )
        self.assertEqual(
            self.config["populations"]["lc10a_right"]["body_ids"],
            tracking["config"]["input_ids_by_soma_side"]["right"],
        )
        lplc = direct["populations"]["LPLC2"]
        expected_left = sorted(row["bodyId"] for row in lplc if row["somaSide"] == "L")
        expected_right = sorted(row["bodyId"] for row in lplc if row["somaSide"] == "R")
        self.assertEqual(self.config["populations"]["lplc2_left"]["body_ids"], expected_left)
        self.assertEqual(self.config["populations"]["lplc2_right"]["body_ids"], expected_right)
        self.assertEqual((len(expected_left), len(expected_right)), (94, 91))

    def test_left_and_right_image_mapping_is_explicit(self):
        left = self.mapper.map_channels(
            self.frame(target_x=-1.0, target_area=0.6), now_ns=1_000_000_000
        )
        right = self.mapper.map_channels(
            self.frame(target_x=1.0, target_area=0.6), now_ns=1_000_000_000
        )
        self.assertEqual((left["lc10a_left"], left["lc10a_right"]), (0.6, 0.0))
        self.assertEqual((right["lc10a_left"], right["lc10a_right"]), (0.0, 0.6))

    def test_center_target_splits_bilaterally(self):
        channels = self.mapper.map_channels(
            self.frame(target_x=0.0, target_area=0.8, confidence=0.5),
            now_ns=1_000_000_000,
        )
        self.assertEqual(channels["lc10a_left"], 0.2)
        self.assertEqual(channels["lc10a_right"], 0.2)

    def test_looming_maps_equally_to_explicit_lplc2_sides(self):
        channels = self.mapper.map_channels(
            self.frame(looming=0.7), now_ns=1_000_000_000
        )
        self.assertEqual(channels["lplc2_left"], 0.7)
        self.assertEqual(channels["lplc2_right"], 0.7)

    def test_external_expansion_uses_p3_injector(self):
        frame = self.frame(target_x=-1.0, target_area=0.5, looming=0.25)
        external = self.mapper.build_external(frame, now_ns=1_000_000_000)
        left_ids = self.config["populations"]["lc10a_left"]["body_ids"]
        right_ids = self.config["populations"]["lc10a_right"]["body_ids"]
        self.assertTrue(all(external[body_id] == 0.5 for body_id in left_ids))
        self.assertTrue(all(body_id not in external for body_id in right_ids))
        for name in ("lplc2_left", "lplc2_right"):
            self.assertTrue(all(external[body_id] == 0.25 for body_id in self.config["populations"][name]["body_ids"]))

    def test_invalid_or_stale_frame_maps_to_zero_external(self):
        invalid = self.frame(valid=False, target_x=-1.0, target_area=1.0, looming=1.0)
        stale = self.frame(timestamp_ns=1_000_000_000, target_x=-1.0, target_area=1.0, looming=1.0)
        self.assertEqual(self.mapper.build_external(invalid, now_ns=1_000_000_000), {})
        self.assertEqual(self.mapper.build_external(stale, now_ns=1_100_000_001), {})

    def test_exact_ttl_boundary_is_still_fresh(self):
        frame = self.frame(timestamp_ns=1_000_000_000, target_x=-1.0, target_area=0.4)
        external = self.mapper.build_external(frame, now_ns=1_100_000_000)
        self.assertTrue(external)

    def test_tof_proximity_is_not_silently_neural_mapped(self):
        frame = self.frame(proximity_left=1.0, proximity_center=1.0, proximity_right=1.0)
        self.assertEqual(self.mapper.build_external(frame, now_ns=1_000_000_000), {})

    def test_config_hash_is_deterministic(self):
        original = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        reordered = dict(reversed(list(original.items())))
        self.assertEqual(
            sensory_mapping_config_sha256(original),
            sensory_mapping_config_sha256(reordered),
        )


if __name__ == "__main__":
    unittest.main()
