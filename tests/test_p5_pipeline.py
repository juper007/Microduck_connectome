import math
from pathlib import Path
import unittest

from microduck_connectome.command_logger import CommandTraceLogger, phase5_config_hashes
from microduck_connectome.control_contracts import make_behavior_intent
from microduck_connectome.dn_aggregator import DNActivityAggregator, load_dn_readout_config
from microduck_connectome.escape_decoder import EscapeDecoder, load_escape_decoder_config
from microduck_connectome.safety_clamp import SafetyClamp, load_safety_envelope
from microduck_connectome.steering_decoder import SteeringDecoder, SteeringDecoderConfig
from microduck_connectome.watchdog import ControllerWatchdog

ROOT=Path(__file__).resolve().parents[1]

class Phase5PipelineTests(unittest.TestCase):
    def setUp(self):
        dn_cfg=load_dn_readout_config(ROOT/"config"/"dn_readout_v1.json")
        self.body_ids=tuple(sorted(body_id for spec in dn_cfg["populations"].values() for body_id in spec["body_ids"]))
        self.agg=DNActivityAggregator(self.body_ids,dn_cfg)
        self.steer=SteeringDecoder(SteeringDecoderConfig(1,0.5,0.5))
        self.escape=EscapeDecoder(load_escape_decoder_config(ROOT/"config"/"escape_decoder_v1.json"))
        self.safety=SafetyClamp(load_safety_envelope(ROOT/"config"/"safety_envelope_v1.json"))
        self.watchdog=ControllerWatchdog(ROOT/"config"/"watchdog_v1.json")
        self.logger=CommandTraceLogger(ROOT/"config"/"command_logger_v1.json",phase5_config_hashes(ROOT))

    def spikes(self,*active):
        selected=set(active)
        return tuple(body_id in selected for body_id in self.body_ids)

    def sample(self,active,ts,seq):
        readout=self.agg.update(self.spikes(*active),timestamp_ns=ts,sequence=seq,runtime_healthy=True)
        pre=self.escape.apply(readout,self.steer.decode(readout))
        safe=self.safety.apply(pre,now_ns=ts,fallback_sequence=seq)
        self.assertTrue(self.watchdog.observe_neural(readout))
        self.assertTrue(self.watchdog.observe_behavior(safe["intent"]))
        watched=self.watchdog.tick(now_ns=ts,output_sequence=seq)
        record=self.logger.append(neural_readout=readout,pre_safety_intent=pre,
                                  safety_result=safe,watchdog_result=watched)
        return readout,pre,safe,watched,record

    def test_nominal_steering_and_escape_stop(self):
        self.sample((),0,0)
        _,pre,safe,watched,record=self.sample((10360,),100_000_000,1)
        self.assertGreater(pre["vyaw"],0.0)
        self.assertGreater(safe["intent"]["vyaw"],0.0)
        self.assertLessEqual(abs(record["final_intent"]["vyaw"]),0.5)
        self.assertFalse(record["stop"])

        self.sample((10001,10010),200_000_000,2)
        self.sample((10001,10010),300_000_000,3)
        readout,pre,safe,watched,record=self.sample((10001,10010),400_000_000,4)
        self.assertGreaterEqual(readout["escape"],0.5)
        self.assertTrue(pre["stop"])
        self.assertTrue(safe["intent"]["stop"])
        self.assertTrue(watched["intent"]["stop"])
        self.assertTrue(record["stop"])
        self.assertEqual((record["final_intent"]["vx"],record["final_intent"]["vy"],record["final_intent"]["vyaw"]),(0.0,0.0,0.0))

    def test_stale_and_decoder_failure_cannot_preserve_motion(self):
        self.sample((),0,0)
        readout,pre,safe,watched,_=self.sample((10360,),100_000_000,1)
        self.assertGreater(watched["intent"]["vyaw"],0.0)

        stale=self.watchdog.tick(now_ns=200_000_001,output_sequence=2)
        stale_record=self.logger.append(neural_readout=readout,pre_safety_intent=pre,
                                        safety_result=safe,watchdog_result=stale)
        self.assertTrue(stale_record["stop"])
        self.assertIn(stale_record["stale_reason"],("stale_neural","stale_behavior"))
        self.assertEqual((stale_record["final_intent"]["vx"],stale_record["final_intent"]["vy"],stale_record["final_intent"]["vyaw"]),(0.0,0.0,0.0))

        self.watchdog.mark_decoder_crashed(1)
        failed=self.watchdog.tick(now_ns=200_000_002,output_sequence=3)
        failed_record=self.logger.append(neural_readout=None,pre_safety_intent=None,
                                         safety_result=None,watchdog_result=failed)
        self.assertTrue(failed_record["stop"])
        self.assertEqual(failed_record["stale_reason"],"decoder_crash")
        self.assertFalse(failed_record["decoder_alive"])

    def test_invalid_neural_sample_is_neutralized_before_output(self):
        behavior=make_behavior_intent(timestamp_ns=100,sequence=1,vx=0.08,vyaw=0.5)
        self.assertTrue(self.watchdog.observe_behavior(behavior))
        bad=dict(timestamp_ns=100,sequence=1,steering_left=math.nan,
                 steering_right=0.0,escape=0.0,runtime_healthy=True)
        self.assertFalse(self.watchdog.observe_neural(bad))
        watched=self.watchdog.tick(now_ns=100,output_sequence=1)
        record=self.logger.append(neural_readout=None,pre_safety_intent=None,
                                  safety_result=None,watchdog_result=watched)
        self.assertTrue(record["stop"])
        self.assertEqual(record["stale_reason"],"invalid_neural")
        self.assertEqual((record["final_intent"]["vx"],record["final_intent"]["vy"],record["final_intent"]["vyaw"]),(0.0,0.0,0.0))

if __name__=="__main__":
    unittest.main()
