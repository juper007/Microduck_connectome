import unittest

from microduck_connectome.perception_compositor import (
    PerceptionCompositor,
    PerceptionCompositorError,
    make_looming_sample,
)
from microduck_connectome.perception_frame import make_perception_frame


def camera(ts=0, fid=0, *, x=0.0, area=0.0, confidence=0.0, valid=True):
    return make_perception_frame(
        timestamp_ns=ts, frame_id=fid,
        target_x=x, target_area=area, confidence=confidence, valid=valid,
    )


def tof(ts=0, fid=0, *, left=0.0, center=0.0, right=0.0, valid=True):
    return make_perception_frame(
        timestamp_ns=ts, frame_id=fid,
        proximity_left=left, proximity_center=center, proximity_right=right,
        confidence=1.0 if valid else 0.0, valid=valid,
    )


def looming(ts=0, fid=0, value=0.0, valid=True):
    return make_looming_sample(
        looming=value, timestamp_ns=ts, frame_id=fid, valid=valid
    )


class PerceptionCompositorTests(unittest.TestCase):
    def test_same_timestamp_composes_frozen_frame(self):
        comp=PerceptionCompositor()
        result=comp.compose(
            camera(100,1,x=-1.0,area=0.25,confidence=1.0),
            looming(100,1,0.4),
            tof(100,7,left=1.0,center=0.5,right=0.0),
            now_ns=100,
        )
        self.assertTrue(result["valid"])
        self.assertEqual(result["timestamp_ns"],100)
        self.assertEqual(result["frame_id"],1)
        self.assertEqual(
            (result["target_x"],result["target_area"],result["looming"]),
            (-1.0,0.25,0.4),
        )
        self.assertEqual(
            (result["proximity_left"],result["proximity_center"],result["proximity_right"]),
            (1.0,0.5,0.0),
        )

    def test_camera_or_tof_can_be_newer_within_coherence_window(self):
        first=PerceptionCompositor().compose(
            camera(100_000_000,1,area=0.2,confidence=1.0),
            looming(100_000_000,1,0.0),
            tof(50_000_000,10),
            now_ns=100_000_000,
        )
        self.assertTrue(first["valid"])
        self.assertEqual(first["timestamp_ns"],100_000_000)
        self.assertEqual(first["frame_id"],1)

        second=PerceptionCompositor().compose(
            camera(50_000_000,1,area=0.2,confidence=1.0),
            looming(50_000_000,1,0.0),
            tof(100_000_000,10),
            now_ns=100_000_000,
        )
        self.assertTrue(second["valid"])
        self.assertEqual(second["timestamp_ns"],100_000_000)
        self.assertEqual(second["frame_id"],1)

    def test_looming_must_match_exact_camera_identity(self):
        for bad in (
            looming(101,1,0.5),
            looming(100,2,0.5),
        ):
            with self.subTest(bad=bad):
                comp=PerceptionCompositor()
                result=comp.compose(camera(100,1),bad,tof(100,9),now_ns=101)
                self.assertFalse(result["valid"])
                self.assertIn("looming_camera_identity_mismatch",comp.last_reasons)

    def test_future_stale_and_source_skew_fail_neutral(self):
        future=PerceptionCompositor()
        result=future.compose(camera(200,1),looming(200,1),tof(200,1),now_ns=100)
        self.assertFalse(result["valid"])
        self.assertEqual(result["timestamp_ns"],100)
        self.assertIn("future_camera",future.last_reasons)

        stale=PerceptionCompositor()
        result=stale.compose(
            camera(0,1,x=1.0,area=1.0,confidence=1.0),
            looming(0,1,1.0),
            tof(0,1,left=1.0,center=1.0,right=1.0),
            now_ns=100_000_001,
        )
        self.assertFalse(result["valid"])
        self.assertEqual(
            (result["target_x"],result["target_area"],result["looming"],
             result["proximity_left"],result["proximity_center"],result["proximity_right"]),
            (0.0,0.0,0.0,0.0,0.0,0.0),
        )
        self.assertIn("stale_camera",stale.last_reasons)

        skew=PerceptionCompositor()
        result=skew.compose(
            camera(200_000_001,2),looming(200_000_001,2),
            tof(100_000_000,8),now_ns=200_000_001,
        )
        self.assertFalse(result["valid"])
        self.assertIn("source_skew",skew.last_reasons)

    def test_exact_100ms_is_fresh_plus_one_is_stale_and_repeat_does_not_refresh(self):
        comp=PerceptionCompositor()
        c=camera(0,1,area=0.2,confidence=1.0)
        l=looming(0,1,0.0)
        t=tof(0,4)
        fresh=comp.compose(c,l,t,now_ns=100_000_000)
        self.assertTrue(fresh["valid"])
        stale=comp.compose(c,l,t,now_ns=100_000_001)
        self.assertFalse(stale["valid"])
        self.assertIn("stale_camera",comp.last_reasons)
        later=comp.compose(c,l,t,now_ns=200_000_000)
        self.assertFalse(later["valid"])
        self.assertIn("stale_camera",comp.last_reasons)

    def test_invalid_camera_or_tof_fails_fully_neutral_but_no_target_is_valid(self):
        for c,t,reason in (
            (camera(10,1,valid=False),tof(10,2),"invalid_camera"),
            (camera(10,1),tof(10,2,valid=False),"invalid_tof"),
        ):
            with self.subTest(reason=reason):
                comp=PerceptionCompositor()
                result=comp.compose(c,looming(10,1,valid=c["valid"]),t,now_ns=10)
                self.assertFalse(result["valid"])
                self.assertIn(reason,comp.last_reasons)
                self.assertEqual(result["target_area"],0.0)
                self.assertEqual(result["looming"],0.0)
                self.assertEqual(result["proximity_left"],0.0)

        comp=PerceptionCompositor()
        result=comp.compose(
            camera(10,1,x=0.0,area=0.0,confidence=0.0,valid=True),
            looming(10,1,0.0,valid=True),
            tof(10,2,valid=True),
            now_ns=10,
        )
        self.assertTrue(result["valid"])
        self.assertEqual((result["target_x"],result["target_area"],result["confidence"]),(0.0,0.0,0.0))

    def test_duplicate_pair_may_be_rechecked_but_partial_identity_change_and_regression_fail(self):
        comp=PerceptionCompositor()
        comp.compose(camera(100,2),looming(100,2),tof(100,5),now_ns=100)
        repeat=comp.compose(camera(100,2),looming(100,2),tof(100,5),now_ns=101)
        self.assertTrue(repeat["valid"])

        mismatch=comp.compose(camera(100,3),looming(100,3),tof(100,5),now_ns=101)
        self.assertFalse(mismatch["valid"])
        self.assertIn("camera_identity_mismatch",comp.last_reasons)

        comp=PerceptionCompositor()
        comp.compose(camera(200,2),looming(200,2),tof(200,5),now_ns=200)
        regressed=comp.compose(camera(100,1),looming(100,1),tof(100,4),now_ns=200)
        self.assertFalse(regressed["valid"])
        self.assertIn("nonmonotonic_camera",comp.last_reasons)
        self.assertIn("nonmonotonic_tof",comp.last_reasons)

    def test_malformed_sources_fail_clearly(self):
        comp=PerceptionCompositor()
        with self.assertRaises(PerceptionCompositorError):
            comp.compose({},looming(1,1),tof(1,1),now_ns=1)
        with self.assertRaises(PerceptionCompositorError):
            comp.compose(camera(1,1),{"looming":0.0},tof(1,1),now_ns=1)
        with self.assertRaises(PerceptionCompositorError):
            comp.compose(camera(1,1),looming(1,1),tof(1,1),now_ns=True)


if __name__=="__main__":
    unittest.main()
