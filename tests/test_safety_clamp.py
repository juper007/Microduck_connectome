import math
from pathlib import Path
import unittest

from microduck_connectome.control_contracts import make_behavior_intent
from microduck_connectome.safety_clamp import SafetyClamp, SafetyClampError, load_safety_envelope

ROOT=Path(__file__).resolve().parents[1]
CONFIG_PATH=ROOT/"config"/"safety_envelope_v1.json"

def intent(ts=0,seq=0,**changes):
    values=dict(timestamp_ns=ts,sequence=seq,vx=0.0,vy=0.0,vyaw=0.0,stop=False,confidence=1.0)
    values.update(changes)
    return make_behavior_intent(**values)

class SafetyClampTests(unittest.TestCase):
    def test_config_matches_frozen_limits(self):
        cfg=load_safety_envelope(CONFIG_PATH)
        self.assertEqual((cfg.max_abs_vx_mps,cfg.max_abs_vy_mps,cfg.max_abs_vyaw_radps),(0.08,0.0,0.5))
        self.assertEqual((cfg.max_delta_vx_per_s,cfg.max_delta_vyaw_per_s2),(0.2,1.5))

    def test_magnitude_clamps_and_vy_zero(self):
        for vx,vyaw,expected in ((1.0,2.0,(0.08,0.5)),(-1.0,-2.0,(-0.08,-0.5))):
            gate=SafetyClamp()
            result=gate.apply(intent(vx=vx,vy=0.4,vyaw=vyaw),now_ns=0,fallback_sequence=0)
            safe=result["intent"]
            self.assertEqual((safe["vx"],safe["vy"],safe["vyaw"]),(expected[0],0.0,expected[1]))
            self.assertTrue(result["clamp_applied"])
            self.assertIn("vy_forced_zero",result["reasons"])

    def test_exact_100ms_slew_limits(self):
        gate=SafetyClamp()
        gate.apply(intent(ts=0,seq=0),now_ns=0,fallback_sequence=0)
        result=gate.apply(intent(ts=100_000_000,seq=1,vx=0.08,vyaw=0.5),
                          now_ns=100_000_000,fallback_sequence=1)
        self.assertAlmostEqual(result["intent"]["vx"],0.02)
        self.assertAlmostEqual(result["intent"]["vyaw"],0.15)
        self.assertIn("vx_slew",result["reasons"])
        self.assertIn("vyaw_slew",result["reasons"])

    def test_reverse_slew_is_symmetric(self):
        gate=SafetyClamp()
        gate.apply(intent(ts=0,seq=0),now_ns=0,fallback_sequence=0)
        first=gate.apply(intent(ts=100_000_000,seq=1,vx=0.08,vyaw=0.5),
                         now_ns=100_000_000,fallback_sequence=1)["intent"]
        second=gate.apply(intent(ts=200_000_000,seq=2,vx=-0.08,vyaw=-0.5),
                          now_ns=200_000_000,fallback_sequence=2)["intent"]
        third=gate.apply(intent(ts=300_000_000,seq=3,vx=-0.08,vyaw=-0.5),
                         now_ns=300_000_000,fallback_sequence=3)["intent"]
        self.assertAlmostEqual(first["vx"],0.02)
        self.assertAlmostEqual(second["vx"],0.0)
        self.assertAlmostEqual(third["vx"],-0.02)
        self.assertAlmostEqual(first["vyaw"],0.15)
        self.assertAlmostEqual(second["vyaw"],0.0)
        self.assertAlmostEqual(third["vyaw"],-0.15)

    def test_stop_override_is_immediate_zero(self):
        gate=SafetyClamp()
        gate.apply(intent(ts=0,seq=0,vx=0.08,vyaw=0.5),now_ns=0,fallback_sequence=0)
        result=gate.apply(intent(ts=1,seq=1,vx=0.08,vyaw=0.5,stop=True),now_ns=1,fallback_sequence=1)
        self.assertTrue(result["intent"]["stop"])
        self.assertEqual((result["intent"]["vx"],result["intent"]["vy"],result["intent"]["vyaw"]),(0.0,0.0,0.0))
        self.assertEqual(result["reasons"],["stop_override"])

    def test_malformed_inputs_fail_closed(self):
        valid=dict(timestamp_ns=1,sequence=1,vx=0.0,vy=0.0,vyaw=0.0,stop=False,confidence=1.0,source="male-cns-controller")
        cases=[]
        missing=dict(valid); missing.pop("vx"); cases.append(missing)
        for key,value in (("vx",math.nan),("vyaw",math.inf),("vx",True),("confidence",1.1),("source","other")):
            bad=dict(valid); bad[key]=value; cases.append(bad)
        for i,bad in enumerate(cases):
            gate=SafetyClamp()
            result=gate.apply(bad,now_ns=100+i,fallback_sequence=10+i)
            self.assertTrue(result["intent"]["stop"])
            self.assertEqual((result["intent"]["vx"],result["intent"]["vy"],result["intent"]["vyaw"]),(0.0,0.0,0.0))
            self.assertEqual(result["reasons"],["invalid_intent"])

    def test_future_and_nonmonotonic_inputs_fail_closed(self):
        gate=SafetyClamp()
        future=gate.apply(intent(ts=200,seq=1),now_ns=100,fallback_sequence=1)
        self.assertEqual(future["reasons"],["future_timestamp"])
        gate=SafetyClamp()
        gate.apply(intent(ts=100,seq=1),now_ns=100,fallback_sequence=1)
        same_ts=gate.apply(intent(ts=100,seq=2),now_ns=200,fallback_sequence=2)
        self.assertEqual(same_ts["reasons"],["nonmonotonic_timestamp"])

    def test_nonmonotonic_sequence_fails_closed(self):
        gate=SafetyClamp()
        gate.apply(intent(ts=100,seq=2),now_ns=100,fallback_sequence=2)
        result=gate.apply(intent(ts=200,seq=2),now_ns=200,fallback_sequence=3)
        self.assertEqual(result["reasons"],["nonmonotonic_sequence"])
        self.assertTrue(result["intent"]["stop"])

    def test_reset_clears_slew_history(self):
        gate=SafetyClamp()
        gate.apply(intent(ts=0,seq=0),now_ns=0,fallback_sequence=0)
        limited=gate.apply(intent(ts=100_000_000,seq=1,vx=0.08),now_ns=100_000_000,fallback_sequence=1)
        self.assertAlmostEqual(limited["intent"]["vx"],0.02)
        gate.reset()
        fresh=gate.apply(intent(ts=1,seq=0,vx=0.08),now_ns=1,fallback_sequence=0)
        self.assertEqual(fresh["intent"]["vx"],0.08)

    def test_safety_fallback_metadata_must_advance(self):
        gate=SafetyClamp()
        gate.apply(intent(ts=10,seq=1),now_ns=10,fallback_sequence=1)
        with self.assertRaises(SafetyClampError):
            gate.apply(intent(ts=20,seq=2),now_ns=10,fallback_sequence=2)
        with self.assertRaises(SafetyClampError):
            gate.apply(intent(ts=20,seq=2),now_ns=20,fallback_sequence=1)

if __name__=="__main__":
    unittest.main()
