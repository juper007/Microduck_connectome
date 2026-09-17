import math
from pathlib import Path
import unittest

from microduck_connectome.command_logger import CommandTrace
from microduck_connectome.control_contracts import make_behavior_intent
from microduck_connectome.dn_aggregator import DNActivityAggregator, dn_readout_config_sha256, load_dn_readout_config
from microduck_connectome.escape_decoder import EscapeDecoder, EscapeDecoderConfig
from microduck_connectome.safety_clamp import SafetyClamp
from microduck_connectome.steering_decoder import SteeringDecoder, SteeringDecoderConfig
from microduck_connectome.watchdog import ControllerWatchdog

ROOT=Path(__file__).resolve().parents[1]
DN_PATH=ROOT/"config"/"dn_readout_v1.json"
WATCHDOG_PATH=ROOT/"config"/"watchdog_v1.json"

def runtime_ids(config):
    return tuple(sorted(body for spec in config["populations"].values() for body in spec["body_ids"]))

def spike_vector(ids,active):
    active=set(active)
    return tuple(body in active for body in ids)

def logger(config):
    return CommandTrace({
        "dn_readout_sha256":dn_readout_config_sha256(config),
        "steering_sign":"test-only:+1",
        "phase":"p5-integration",
    })

class Phase5IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.config=load_dn_readout_config(DN_PATH)
        self.ids=runtime_ids(self.config)
        self.steering=SteeringDecoder(SteeringDecoderConfig(1,0.5))
        self.escape=EscapeDecoder(EscapeDecoderConfig(1.0,0.5))

    def test_nominal_steering_flows_through_safety_watchdog_and_log(self):
        agg=DNActivityAggregator(self.ids,self.config)
        safety=SafetyClamp()
        zero=agg.update(spike_vector(self.ids,[]),timestamp_ns=0,sequence=0)
        zero_pre=self.escape.apply(zero,self.steering.decode(zero))
        safety.apply(zero_pre,now_ns=0,fallback_sequence=0)

        right=self.config["populations"]["steering_right"]["body_ids"][0]
        neural=agg.update(spike_vector(self.ids,[right]),timestamp_ns=100_000_000,sequence=1)
        pre=self.escape.apply(neural,self.steering.decode(neural))
        safe=safety.apply(pre,now_ns=100_000_000,fallback_sequence=1)
        self.assertAlmostEqual(safe["intent"]["vyaw"],0.1)
        self.assertFalse(safe["intent"]["stop"])

        wd=ControllerWatchdog(WATCHDOG_PATH)
        wd.observe_neural(neural); wd.observe_behavior(safe["intent"])
        final=wd.tick(now_ns=100_000_000,output_sequence=0)
        trace=logger(self.config)
        trace.append(neural_readout=neural,pre_safety_intent=pre,safety_result=safe,watchdog_result=final)
        row=trace.records()[0]
        self.assertAlmostEqual(row["watchdog_intent"]["vyaw"],0.1)
        self.assertEqual(row["watchdog_state"],"healthy")
        self.assertFalse(row["stop_state"])

    def test_escape_activity_asserts_zero_motion_stop_and_is_logged(self):
        agg=DNActivityAggregator(self.ids,self.config)
        escape_ids=self.config["populations"]["escape"]["body_ids"]
        neural=None
        for i in range(3):
            neural=agg.update(spike_vector(self.ids,escape_ids),timestamp_ns=(i+1)*20_000_000,sequence=i)
        self.assertGreaterEqual(neural["escape"],0.5)
        pre=self.escape.apply(neural,self.steering.decode(neural))
        self.assertTrue(pre["stop"])
        safe=SafetyClamp().apply(pre,now_ns=neural["timestamp_ns"],fallback_sequence=neural["sequence"])
        self.assertEqual((safe["intent"]["vx"],safe["intent"]["vy"],safe["intent"]["vyaw"]),(0.0,0.0,0.0))

        wd=ControllerWatchdog(WATCHDOG_PATH)
        wd.observe_neural(neural); wd.observe_behavior(safe["intent"])
        final=wd.tick(now_ns=neural["timestamp_ns"],output_sequence=0)
        trace=logger(self.config)
        trace.append(neural_readout=neural,pre_safety_intent=pre,safety_result=safe,watchdog_result=final)
        row=trace.records()[0]
        self.assertTrue(row["stop_state"])
        self.assertEqual(row["clamp_reasons"],["stop_override"])

    def test_invalid_neural_sample_cannot_preserve_nonzero_motion(self):
        wd=ControllerWatchdog(WATCHDOG_PATH)
        bad={"timestamp_ns":0,"sequence":0,"steering_left":math.nan,"steering_right":0.0,"escape":0.0,"runtime_healthy":True}
        self.assertFalse(wd.observe_neural(bad))
        wd.observe_behavior(make_behavior_intent(timestamp_ns=0,sequence=0,vyaw=0.4))
        final=wd.tick(now_ns=1,output_sequence=0)
        self.assertTrue(final["intent"]["stop"])
        self.assertEqual(final["intent"]["vyaw"],0.0)
        trace=logger(self.config)
        trace.append(neural_readout=None,pre_safety_intent=None,safety_result=None,watchdog_result=final)
        self.assertEqual(trace.records()[0]["stale_reason"],"invalid_neural")

    def test_stale_source_stops_previous_steering_without_refresh(self):
        wd=ControllerWatchdog(WATCHDOG_PATH)
        neural={"timestamp_ns":0,"sequence":0,"steering_left":0.0,"steering_right":0.2,"escape":0.0,"runtime_healthy":True}
        safe_intent=make_behavior_intent(timestamp_ns=0,sequence=0,vyaw=0.1)
        wd.observe_neural(neural); wd.observe_behavior(safe_intent)
        fresh=wd.tick(now_ns=100_000_000,output_sequence=0)
        stale=wd.tick(now_ns=100_000_001,output_sequence=1)
        self.assertEqual(fresh["intent"]["vyaw"],0.1)
        self.assertTrue(stale["intent"]["stop"])
        self.assertEqual(stale["intent"]["vyaw"],0.0)

        trace=logger(self.config)
        safe_result={"intent":safe_intent,"clamp_applied":False,"reasons":[]}
        trace.append(neural_readout=neural,pre_safety_intent=safe_intent,safety_result=safe_result,watchdog_result=fresh)
        trace.append(neural_readout=neural,pre_safety_intent=safe_intent,safety_result=safe_result,watchdog_result=stale)
        self.assertEqual(trace.records()[1]["stale_reason"],"stale_neural")

    def test_decoder_process_exit_boundary_stops_and_logs(self):
        wd=ControllerWatchdog(WATCHDOG_PATH)
        wd.mark_decoder_crashed(17)
        final=wd.tick(now_ns=1,output_sequence=0)
        self.assertTrue(final["intent"]["stop"])
        self.assertEqual(final["stale_reason"],"decoder_crash")
        trace=logger(self.config)
        trace.append(neural_readout=None,pre_safety_intent=None,safety_result=None,watchdog_result=final)
        row=trace.records()[0]
        self.assertFalse(row["decoder_alive"])
        self.assertEqual(row["watchdog_intent"]["vyaw"],0.0)

if __name__=="__main__":
    unittest.main()
