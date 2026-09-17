import math
from pathlib import Path
import unittest

from microduck_connectome.control_contracts import make_behavior_intent
from microduck_connectome.watchdog import ControllerWatchdog, WatchdogError

ROOT=Path(__file__).resolve().parents[1]
CONFIG_PATH=ROOT/"config"/"watchdog_v1.json"

def neural(ts=0,seq=0,healthy=True):
    return {"timestamp_ns":ts,"sequence":seq,"steering_left":0.0,"steering_right":0.0,"escape":0.0,"runtime_healthy":healthy}

def behavior(ts=0,seq=0,vyaw=0.2):
    return make_behavior_intent(timestamp_ns=ts,sequence=seq,vyaw=vyaw,confidence=0.8)

class WatchdogTests(unittest.TestCase):
    def new(self):
        return ControllerWatchdog(CONFIG_PATH)

    def prime(self,wd,ts=0,seq=0,vyaw=0.2):
        self.assertTrue(wd.observe_neural(neural(ts,seq)))
        self.assertTrue(wd.observe_behavior(behavior(ts,seq,vyaw)))

    def test_exact_100ms_is_fresh_and_plus_one_ns_is_stale(self):
        wd=self.new(); self.prime(wd)
        fresh=wd.tick(now_ns=100_000_000,output_sequence=0)
        self.assertEqual(fresh["watchdog_state"],"healthy")
        self.assertEqual(fresh["intent"]["vyaw"],0.2)
        stale=wd.tick(now_ns=100_000_001,output_sequence=1)
        self.assertEqual(stale["stale_reason"],"stale_neural")
        self.assertTrue(stale["intent"]["stop"])
        self.assertEqual((stale["intent"]["vx"],stale["intent"]["vy"],stale["intent"]["vyaw"]),(0.0,0.0,0.0))

    def test_behavior_stale_is_detected_independently(self):
        wd=self.new()
        wd.observe_neural(neural(ts=50_000_000,seq=1))
        wd.observe_behavior(behavior(ts=0,seq=1))
        result=wd.tick(now_ns=100_000_001,output_sequence=0)
        self.assertEqual(result["stale_reason"],"stale_behavior")

    def test_missing_and_unhealthy_sources_stop(self):
        wd=self.new()
        self.assertEqual(wd.tick(now_ns=1,output_sequence=0)["stale_reason"],"missing_neural")
        wd=self.new()
        wd.observe_neural(neural(0,0,healthy=False))
        wd.observe_behavior(behavior(0,0))
        result=wd.tick(now_ns=1,output_sequence=0)
        self.assertEqual(result["stale_reason"],"runtime_unhealthy")
        self.assertTrue(result["intent"]["stop"])

    def test_future_sources_stop(self):
        wd=self.new(); self.prime(wd,ts=200,seq=0)
        result=wd.tick(now_ns=100,output_sequence=0)
        self.assertEqual(result["stale_reason"],"future_neural")
        self.assertTrue(result["intent"]["stop"])

    def test_invalid_and_nonmonotonic_samples_stop(self):
        wd=self.new()
        bad=neural(); bad["steering_left"]=math.nan
        self.assertFalse(wd.observe_neural(bad))
        self.assertEqual(wd.tick(now_ns=1,output_sequence=0)["stale_reason"],"invalid_neural")

        wd=self.new()
        wd.observe_neural(neural(10,1))
        self.assertFalse(wd.observe_neural(neural(10,2)))
        self.assertEqual(wd.tick(now_ns=20,output_sequence=0)["stale_reason"],"nonmonotonic_neural")

        wd=self.new()
        wd.observe_behavior(behavior(10,1))
        self.assertFalse(wd.observe_behavior(behavior(20,1)))
        wd.observe_neural(neural(20,2))
        self.assertEqual(wd.tick(now_ns=20,output_sequence=0)["stale_reason"],"nonmonotonic_behavior")

    def test_fault_does_not_allow_source_metadata_rollback(self):
        wd=self.new()
        wd.observe_neural(neural(100,5))
        invalid=neural(110,6); invalid["escape"]=math.nan
        self.assertFalse(wd.observe_neural(invalid))
        self.assertFalse(wd.observe_neural(neural(50,1)))
        self.assertEqual(wd.tick(now_ns=120,output_sequence=0)["stale_reason"],"nonmonotonic_neural")

    def test_repeated_ticks_do_not_refresh_source_age(self):
        wd=self.new(); self.prime(wd)
        self.assertEqual(wd.tick(now_ns=50_000_000,output_sequence=0)["watchdog_state"],"healthy")
        self.assertEqual(wd.tick(now_ns=100_000_000,output_sequence=1)["watchdog_state"],"healthy")
        result=wd.tick(now_ns=100_000_001,output_sequence=2)
        self.assertEqual(result["stale_reason"],"stale_neural")
        self.assertEqual(result["intent"]["vyaw"],0.0)

    def test_process_exit_boundary_triggers_safe_stop(self):
        wd=self.new(); self.prime(wd)
        wd.mark_decoder_crashed(17)
        result=wd.tick(now_ns=1,output_sequence=0)
        self.assertEqual(result["stale_reason"],"decoder_crash")
        self.assertFalse(result["decoder_alive"])
        self.assertTrue(result["intent"]["stop"])
        self.assertEqual((result["intent"]["vx"],result["intent"]["vy"],result["intent"]["vyaw"]),(0.0,0.0,0.0))

    def test_recovery_requires_new_healthy_data(self):
        wd=self.new(); self.prime(wd)
        wd.mark_decoder_crashed(17)
        wd.recover_decoder()
        missing=wd.tick(now_ns=10,output_sequence=0)
        self.assertEqual(missing["stale_reason"],"missing_neural")
        wd.observe_neural(neural(20,2))
        wd.observe_behavior(behavior(20,2,vyaw=-0.1))
        recovered=wd.tick(now_ns=20,output_sequence=1)
        self.assertEqual(recovered["watchdog_state"],"healthy")
        self.assertEqual(recovered["intent"]["vyaw"],-0.1)

    def test_tick_metadata_and_crash_code_are_validated(self):
        wd=self.new(); self.prime(wd)
        wd.tick(now_ns=10,output_sequence=1)
        with self.assertRaises(WatchdogError):
            wd.tick(now_ns=10,output_sequence=2)
        with self.assertRaises(WatchdogError):
            wd.tick(now_ns=20,output_sequence=1)
        for code in (0,True):
            with self.subTest(code=code), self.assertRaises(WatchdogError):
                self.new().mark_decoder_crashed(code)

if __name__=="__main__":
    unittest.main()
