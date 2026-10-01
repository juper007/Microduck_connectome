import unittest
from microduck_connectome.so101_sim import MockArm, SO101SimAdapter, TaskIntent, POSE


class AdapterTests(unittest.TestCase):
    def test_opposite_motion_bounded_and_hold(self):
        arm = MockArm()
        adapter = SO101SimAdapter(arm)
        for i in range(1,201):
            result = adapter.send(TaskIntent(i*20_000_000,i,1,False),now_ns=i*20_000_000)
        self.assertAlmostEqual(result["q"][0],0.4)
        self.assertEqual(result["q"][1:],POSE[1:])
        result = adapter.send(TaskIntent(4_020_000_000,201,-1,False),now_ns=4_020_000_000)
        self.assertLess(result["v"][0],0)
        result = adapter.send(TaskIntent(4_040_000_000,202,1,True),now_ns=4_040_000_000)
        self.assertTrue(result["hold"])
        self.assertEqual(result["v"][0],0)

    def test_invalid_stale_replay_gap_fail_safe_and_latch(self):
        for bad in (TaskIntent(0,2,1,False),TaskIntent(40_000_000,1,1,False),
                    TaskIntent(40_000_000,2,float("nan"),False),
                    TaskIntent(40_000_000,2,2,False),TaskIntent(40_000_000,2,1,"false"),
                    TaskIntent(300_000_000,2,1,False)):
            with self.subTest(bad=bad):
                arm = MockArm()
                adapter = SO101SimAdapter(arm)
                adapter.send(TaskIntent(20_000_000,1,1,False),now_ns=20_000_000)
                now = 300_000_000 if bad.timestamp_ns in (0,300_000_000) else 40_000_000
                with self.assertRaises(ValueError):
                    adapter.send(bad,now_ns=now)
                self.assertTrue(adapter.holding)
                self.assertIsNotNone(adapter.fault)
                result = adapter.send(TaskIntent(60_000_000,3,1,False),now_ns=60_000_000)
                self.assertTrue(result["hold"])
                self.assertEqual(result["v"][0],0)

    def test_disconnect_and_step_fault_close_or_hold(self):
        for disconnected in (True,False):
            arm = MockArm()
            adapter = SO101SimAdapter(arm)
            adapter.send(TaskIntent(20_000_000,1,1,False),now_ns=20_000_000)
            if disconnected:
                arm.close()
            else:
                def fail(*args):
                    raise RuntimeError("step fault")
                arm.step = fail
            with self.assertRaises(RuntimeError):
                adapter.send(TaskIntent(40_000_000,2,1,False),now_ns=40_000_000)
            self.assertTrue(adapter.holding)
            self.assertFalse(arm.connected)

    def test_connection_failure_never_moves(self):
        arm = MockArm()
        def fail():
            raise RuntimeError("connect fault")
        arm.connect = fail
        with self.assertRaises(RuntimeError):
            SO101SimAdapter(arm)
        self.assertEqual(tuple(arm.q),POSE)
