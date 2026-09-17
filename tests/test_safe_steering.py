import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from safe_steering import Readout, SteeringGate

class SteeringTests(unittest.TestCase):
    def running(self):
        gate=SteeringGate(1)
        for i in range(20): gate.tick(Readout(i*20_000_000,i,1,0),i*20_000_000)
        return gate
    def test_bounds_slew_and_sign(self):
        for sign in (-1,1):
            gate=SteeringGate(sign); prev=0
            for i in range(40):
                out=gate.tick(Readout(i*20_000_000,i,1,0),i*20_000_000)
                self.assertLessEqual(abs(out['vyaw']-prev),.030000001)
                self.assertEqual((out['vx'],out['vy']),(0,0))
                prev=out['vyaw']
            self.assertEqual(prev,sign*.5)
    def test_stale_and_future_neutralize_immediately(self):
        for stamp in (300_000_000,401_000_000):
            out=self.running().tick(Readout(stamp,20,1,0),400_000_000)
            self.assertTrue(out['stop']); self.assertEqual(out['vyaw'],0)
    def test_invalid_and_unhealthy(self):
        for value in (float('nan'),float('inf'),-1,2,'1',True):
            self.assertTrue(self.running().tick(Readout(400_000_000,20,value,0),400_000_000)['stop'])
        self.assertTrue(self.running().tick(Readout(400_000_000,20,1,0,False),400_000_000)['stop'])
    def test_emergency_missing_and_out_of_order(self):
        self.assertEqual(self.running().tick(Readout(400_000_000,20,1,0),400_000_000,True)['vyaw'],0)
        self.assertTrue(self.running().tick(None,400_000_000)['stop'])
        self.assertTrue(self.running().tick(Readout(400_000_000,1,1,0),400_000_000)['stop'])
    def test_delayed_tick_cannot_jump(self):
        gate=SteeringGate(1); gate.tick(Readout(0,0,1,0),0)
        self.assertAlmostEqual(gate.tick(Readout(1_000_000_000,1,1,0),1_000_000_000)['vyaw'],.03)
    def test_backward_clock_stops(self):
        self.assertTrue(self.running().tick(Readout(300_000_000,20,1,0),300_000_000)['stop'])
    def test_sequence_reuse_cannot_refresh_timestamp(self):
        gate=self.running()
        self.assertTrue(gate.tick(Readout(400_000_000,19,1,0),400_000_000)['stop'])
    def test_same_sample_may_be_consumed_until_expiry(self):
        gate=SteeringGate(1); sample=Readout(0,0,1,0)
        gate.tick(sample,0)
        self.assertFalse(gate.tick(sample,20_000_000)['stop'])
        self.assertTrue(gate.tick(sample,100_000_000)['stop'])

if __name__=='__main__': unittest.main()
