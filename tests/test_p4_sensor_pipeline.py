from pathlib import Path
import unittest

from microduck_connectome.perception_compositor import PerceptionPipeline
from microduck_connectome.sensory_mapping import SensoryMapper, load_sensory_mapping_config
from microduck_connectome.stimulus_visualizer import StimulusTrace

ROOT=Path(__file__).resolve().parents[1]
CONFIG_PATH=ROOT/"config"/"sensory_mapping_v1.json"

B=(0,0,0)
R=(255,0,0)


def runtime_ids(config):
    return tuple(sorted(
        body_id
        for spec in config["populations"].values()
        for body_id in spec["body_ids"]
    ))


class P4SensorPipelineTests(unittest.TestCase):
    def setUp(self):
        self.pipeline=PerceptionPipeline()
        self.config=load_sensory_mapping_config(CONFIG_PATH)
        self.mapper=SensoryMapper(runtime_ids(self.config),self.config)

    def process(self,pixels,ts,fid,*,tof_ts=None,tof_fid=None,now=None,
                left=500,center=500,right=500,camera_valid=True,tof_valid=True):
        return self.pipeline.process(
            pixels,
            camera_timestamp_ns=ts,
            camera_frame_id=fid,
            tof_left_mm=left,
            tof_center_mm=center,
            tof_right_mm=right,
            tof_timestamp_ns=ts if tof_ts is None else tof_ts,
            tof_frame_id=(100+fid) if tof_fid is None else tof_fid,
            now_ns=ts if now is None else now,
            camera_source_valid=camera_valid,
            tof_source_valid=tof_valid,
        )

    def test_real_components_drive_left_center_right_sensory_mapping(self):
        fixtures=[
            ([[R,B,B]],0,1,("lc10a_left","lc10a_right"),(1/3,0.0)),
            ([[B,R,B]],100_000_000,2,("lc10a_left","lc10a_right"),(1/6,1/6)),
            ([[B,B,R]],200_000_000,3,("lc10a_left","lc10a_right"),(0.0,1/3)),
        ]
        for pixels,ts,fid,names,expected in fixtures:
            with self.subTest(fid=fid):
                frame=self.process(pixels,ts,fid)
                self.assertTrue(frame["valid"])
                channels=self.mapper.map_channels(frame,now_ns=frame["timestamp_ns"])
                self.assertAlmostEqual(channels[names[0]],expected[0])
                self.assertAlmostEqual(channels[names[1]],expected[1])

    def test_real_looming_estimator_reaches_bilateral_lplc2(self):
        first=self.process([[R,B,B,B]],0,1)
        second=self.process([[R,R,B,B]],100_000_000,2)
        self.assertEqual(first["looming"],0.0)
        self.assertGreater(second["looming"],0.0)
        channels=self.mapper.map_channels(second,now_ns=second["timestamp_ns"])
        self.assertGreater(channels["lplc2_left"],0.0)
        self.assertEqual(channels["lplc2_left"],channels["lplc2_right"])

    def test_no_target_resets_looming_and_does_not_replay_prior_target(self):
        self.process([[R,B,B,B]],0,1)
        approaching=self.process([[R,R,B,B]],100_000_000,2)
        self.assertGreater(approaching["looming"],0.0)

        missing=self.process([[B,B,B,B]],200_000_000,3)
        self.assertTrue(missing["valid"])
        self.assertEqual((missing["target_x"],missing["target_area"],missing["confidence"],missing["looming"]),
                         (0.0,0.0,0.0,0.0))
        self.assertEqual(self.mapper.build_external(missing,now_ns=missing["timestamp_ns"]),{})

        reacquired=self.process([[R,R,R,B]],300_000_000,4)
        self.assertEqual(reacquired["looming"],0.0)

    def test_camera_or_tof_loss_fails_neutral_and_sensory_injection_is_empty(self):
        good=self.process([[B,B,R]],0,1)
        self.assertTrue(self.mapper.build_external(good,now_ns=good["timestamp_ns"]))

        lost_camera=self.process(None,100_000_000,2,camera_valid=False)
        self.assertFalse(lost_camera["valid"])
        self.assertEqual(self.mapper.build_external(lost_camera,now_ns=lost_camera["timestamp_ns"]),{})
        self.assertEqual((lost_camera["target_area"],lost_camera["looming"],lost_camera["proximity_left"]),(0.0,0.0,0.0))

        fresh=PerceptionPipeline()
        self.pipeline=fresh
        lost_tof=self.process([[R,B,B]],200_000_000,3,left=None)
        self.assertFalse(lost_tof["valid"])
        self.assertEqual(self.mapper.build_external(lost_tof,now_ns=lost_tof["timestamp_ns"]),{})

    def test_stale_visual_sample_resets_looming_and_next_fresh_target_rebaselines(self):
        self.process([[R,B,B]],0,1)
        invalid=self.process([[R,R,B]],100_000_000,2,now=200_000_001,
                             tof_ts=100_000_000)
        self.assertFalse(invalid["valid"])
        self.assertEqual(invalid["looming"],0.0)
        self.assertEqual(self.mapper.build_external(invalid,now_ns=invalid["timestamp_ns"]),{})

        fresh=self.process([[R,R,R]],300_000_000,3)
        self.assertTrue(fresh["valid"])
        self.assertEqual(fresh["looming"],0.0)

    def test_stimulus_trace_does_not_resurrect_channels_after_sensor_loss(self):
        trace=StimulusTrace()
        frames=[
            self.process([[R,B,B]],0,1),
            self.process([[B,R,B]],100_000_000,2),
            self.process([[B,B,R]],200_000_000,3),
        ]
        for frame in frames:
            channels=self.mapper.map_channels(frame,now_ns=frame["timestamp_ns"])
            trace.append(frame,channels)

        lost=self.process([[B,B,R]],300_000_000,4,left=None)
        channels=self.mapper.map_channels(lost,now_ns=lost["timestamp_ns"])
        trace.append(lost,channels)
        self.assertEqual(channels,{
            "lc10a_left":0.0,"lc10a_right":0.0,
            "lplc2_left":0.0,"lplc2_right":0.0,
        })
        last=trace.records()[-1]
        self.assertFalse(last["frame"]["valid"])
        self.assertTrue(all(value==0.0 for value in last["channels"].values()))
        self.assertTrue(trace.to_jsonl())
        self.assertIn("<svg",trace.to_svg())


if __name__=="__main__":
    unittest.main()
