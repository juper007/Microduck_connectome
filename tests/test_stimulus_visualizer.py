import json
from pathlib import Path
import unittest

from microduck_connectome.perception_frame import make_perception_frame
from microduck_connectome.sensory_mapping import SensoryMapper, load_sensory_mapping_config
from microduck_connectome.stimulus_visualizer import (
    STIMULUS_CHANNELS,
    StimulusTrace,
    StimulusVisualizerError,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "sensory_mapping_v1.json"


def runtime_ids(config):
    return tuple(sorted(
        body_id
        for spec in config["populations"].values()
        for body_id in spec["body_ids"]
    ))


def frame(frame_id, timestamp_ns, **changes):
    values = dict(
        timestamp_ns=timestamp_ns,
        frame_id=frame_id,
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


class StimulusVisualizerTests(unittest.TestCase):
    def test_records_are_validated_and_detached(self):
        trace = StimulusTrace()
        channels = {name: 0.25 for name in STIMULUS_CHANNELS}
        source_frame = frame(1, 100)
        trace.append(source_frame, channels)
        source_frame["target_x"] = 1.0
        channels["lc10a_left"] = 1.0
        record = trace.records()[0]
        self.assertEqual(record["frame"]["target_x"], 0.0)
        self.assertEqual(record["channels"]["lc10a_left"], 0.25)
        record["channels"]["lc10a_left"] = 0.9
        self.assertEqual(trace.records()[0]["channels"]["lc10a_left"], 0.25)

    def test_invalid_channels_and_nonmonotonic_trace_are_rejected(self):
        trace = StimulusTrace()
        good = {name: 0.0 for name in STIMULUS_CHANNELS}
        trace.append(frame(1, 100), good)
        with self.assertRaises(StimulusVisualizerError):
            trace.append(frame(2, 200), {"lc10a_left": 0.0})
        bad = dict(good, lc10a_left=1.1)
        with self.assertRaises(StimulusVisualizerError):
            StimulusTrace().append(frame(1, 100), bad)
        with self.assertRaises(StimulusVisualizerError):
            trace.append(frame(2, 100), good)
        with self.assertRaises(StimulusVisualizerError):
            trace.append(frame(1, 200), good)

    def test_jsonl_is_machine_readable_and_deterministic(self):
        trace = StimulusTrace()
        trace.append(frame(1, 100, target_x=-1.0), {
            "lc10a_left": 0.5,
            "lc10a_right": 0.0,
            "lplc2_left": 0.0,
            "lplc2_right": 0.0,
        })
        trace.append(frame(2, 200, looming=0.4), {
            "lc10a_left": 0.0,
            "lc10a_right": 0.0,
            "lplc2_left": 0.4,
            "lplc2_right": 0.4,
        })
        text = trace.to_jsonl()
        rows = [json.loads(line) for line in text.splitlines()]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["channels"]["lc10a_left"], 0.5)
        self.assertEqual(rows[1]["frame"]["looming"], 0.4)
        self.assertEqual(text, trace.to_jsonl())

    def test_svg_renders_all_four_channel_lanes(self):
        trace = StimulusTrace()
        trace.append(frame(1, 100), {name: 0.0 for name in STIMULUS_CHANNELS})
        trace.append(frame(2, 200), {
            "lc10a_left": 1.0,
            "lc10a_right": 0.5,
            "lplc2_left": 0.25,
            "lplc2_right": 0.75,
        })
        svg = trace.to_svg(width=640, height=320)
        self.assertIn("<svg", svg)
        self.assertEqual(svg.count("<polyline "), 4)
        for name in STIMULUS_CHANNELS:
            self.assertIn(name, svg)
        self.assertIn("time: 100..200 ns", svg)

    def test_empty_or_bad_dimensions_fail(self):
        with self.assertRaises(StimulusVisualizerError):
            StimulusTrace().to_svg()
        trace = StimulusTrace()
        trace.append(frame(1, 100), {name: 0.0 for name in STIMULUS_CHANNELS})
        with self.assertRaises(StimulusVisualizerError):
            trace.to_svg(width=100)
        with self.assertRaises(StimulusVisualizerError):
            trace.to_svg(height=100)

    def test_integration_trace_uses_real_sensory_mapper(self):
        config = load_sensory_mapping_config(CONFIG_PATH)
        mapper = SensoryMapper(runtime_ids(config), config)
        trace = StimulusTrace()
        fixtures = [
            frame(1, 100_000_000, target_x=-1.0, target_area=0.6),
            frame(2, 150_000_000, target_x=0.0, target_area=0.6),
            frame(3, 200_000_000, target_x=1.0, target_area=0.6, looming=0.5),
        ]
        for sample in fixtures:
            trace.append(sample, mapper.map_channels(sample, now_ns=sample["timestamp_ns"]))
        records = trace.records()
        self.assertEqual((records[0]["channels"]["lc10a_left"], records[0]["channels"]["lc10a_right"]), (0.6, 0.0))
        self.assertEqual((records[1]["channels"]["lc10a_left"], records[1]["channels"]["lc10a_right"]), (0.3, 0.3))
        self.assertEqual((records[2]["channels"]["lc10a_left"], records[2]["channels"]["lc10a_right"]), (0.0, 0.6))
        self.assertEqual(records[2]["channels"]["lplc2_left"], 0.5)
        self.assertEqual(records[2]["channels"]["lplc2_right"], 0.5)
        self.assertTrue(trace.to_jsonl())
        self.assertIn("<svg", trace.to_svg())


if __name__ == "__main__":
    unittest.main()
