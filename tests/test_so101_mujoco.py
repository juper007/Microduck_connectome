"""Opt-in actual physics checks: SO101_MODEL_DIR must be a clean pinned checkout."""
import os
import unittest
from microduck_connectome.so101_sim import MujocoArm, SO101SimAdapter, TaskIntent


@unittest.skipUnless(os.environ.get("SO101_MODEL_DIR"),"requires pinned official SO-101 model")
class PhysicsTests(unittest.TestCase):
    def test_motion_hold_and_stale_fault(self):
        arm = MujocoArm(os.environ["SO101_MODEL_DIR"])
        adapter = SO101SimAdapter(arm)
        seq = 0
        def tick(bias=0,stop=False):
            nonlocal seq
            seq += 1
            return adapter.send(TaskIntent(seq*20_000_000,seq,bias,stop),now_ns=seq*20_000_000)
        try:
            start = arm.observe()[0][0]
            left = [tick(1) for _ in range(60)]
            self.assertGreater(left[-1]["q"][0]-start,0.1)
            self.assertGreater(max(r["v"][0] for r in left),0.01)
            right = [tick(-1) for _ in range(60)]
            self.assertLess(right[-1]["q"][0]-left[-1]["q"][0],-0.1)
            self.assertLess(min(r["v"][0] for r in right),-0.01)
            held = [tick(1,True) for _ in range(75)]
            self.assertLess(abs(held[-1]["v"][0]),0.01)
            self.assertEqual(held[-1]["target"],held[-25]["target"])
            self.assertLess(abs(held[-1]["q"][0]-held[-25]["q"][0]),0.002)
            with self.assertRaises(ValueError):
                adapter.send(TaskIntent(0,seq+1,1,False),now_ns=(seq+1)*20_000_000)
            self.assertTrue(adapter.holding)
            self.assertIsNotNone(adapter.fault)
            for _ in range(50):
                result = tick(1)
            self.assertTrue(result["hold"])
            self.assertLess(abs(result["v"][0]),0.01)
        finally:
            adapter.close()
