import json
import math
from pathlib import Path
import unittest

from microduck_connectome.command_logger import (
    CommandLoggerError, CommandTraceLogger,
    load_command_logger_config, phase5_config_hashes,
)
from microduck_connectome.control_contracts import make_behavior_intent

ROOT=Path(__file__).resolve().parents[1]
LOGGER_CONFIG=ROOT/"config"/"command_logger_v1.json"

def neural(ts=0,seq=0,healthy=True,**changes):
    value=dict(timestamp_ns=ts,sequence=seq,steering_left=0.0,steering_right=0.0,
               escape=0.0,runtime_healthy=healthy)
    value.update(changes)
    return value

def intent(ts=0,seq=0,**changes):
    value=dict(timestamp_ns=ts,sequence=seq,vx=0.0,vy=0.0,vyaw=0.0,
               stop=False,confidence=1.0)
    value.update(changes)
    return make_behavior_intent(**value)

def safety(value,applied=False,reasons=()):
    return {"intent":value,"clamp_applied":applied,"reasons":list(reasons)}

def watch(value,state="healthy",reason=None,alive=True):
    return {"intent":value,"watchdog_state":state,"stale_reason":reason,"decoder_alive":alive}

class CommandLoggerTests(unittest.TestCase):
    def make(self):
        return CommandTraceLogger(LOGGER_CONFIG,phase5_config_hashes(ROOT))

    def test_config_hashes_are_valid(self):
        cfg=load_command_logger_config(LOGGER_CONFIG)
        hashes=phase5_config_hashes(ROOT)
        self.assertEqual(list(hashes),cfg["required_config_hashes"])
        for digest in hashes.values():
            self.assertRegex(digest,r"^[0-9a-f]{64}$")

    def test_records_detached_and_jsonl_deterministic(self):
        logger=self.make()
        n=neural(10,1)
        pre=intent(10,1,vx=0.03)
        s=safety(pre)
        record=logger.append(neural_readout=n,pre_safety_intent=pre,
                             safety_result=s,watchdog_result=watch(pre))
        n["escape"]=1.0
        s["reasons"].append("mutated")
        record["final_intent"]["vx"]=9.0
        stored=logger.records()[0]
        self.assertEqual(stored["neural_readout"]["escape"],0.0)
        self.assertEqual(stored["clamp_reasons"],[])
        self.assertEqual(stored["final_intent"]["vx"],0.03)
        self.assertEqual(logger.to_jsonl(),logger.to_jsonl())
        self.assertEqual(json.loads(logger.to_jsonl())["controller_source"],"male-cns-controller")

    def test_clamp_stop_and_watchdog_fault_are_reconstructible(self):
        logger=self.make()
        pre=intent(100,1,vx=1.0,vy=1.0,vyaw=2.0)
        post=intent(100,1,vx=0.08,vyaw=0.5)
        record=logger.append(
            neural_readout=neural(100,1),
            pre_safety_intent=pre,
            safety_result=safety(post,True,("vx_magnitude","vy_forced_zero","vyaw_magnitude")),
            watchdog_result=watch(post),
        )
        self.assertTrue(record["clamp_applied"])
        self.assertIn("vx_magnitude",record["clamp_reasons"])

        logger2=self.make()
        stopped=intent(200,2,stop=True,confidence=0.0)
        fault=logger2.append(
            neural_readout=None,pre_safety_intent=None,safety_result=None,
            watchdog_result=watch(stopped,"safe_stop","decoder_crash",False),
        )
        self.assertTrue(fault["stop"])
        self.assertIsNone(fault["runtime_healthy"])
        self.assertEqual(fault["stale_reason"],"decoder_crash")

    def test_cross_stage_mismatches_are_rejected(self):
        logger=self.make()
        with self.assertRaises(CommandLoggerError):
            logger.append(
                neural_readout=neural(10,1),
                pre_safety_intent=intent(11,2),
                safety_result=safety(intent(11,2)),
                watchdog_result=watch(intent(11,2)),
            )

        with self.assertRaises(CommandLoggerError):
            self.make().append(
                neural_readout=neural(10,1),
                pre_safety_intent=intent(10,1),
                safety_result=safety(intent(10,1)),
                watchdog_result=watch(intent(10,1),"healthy","stale_neural",True),
            )

        with self.assertRaises(CommandLoggerError):
            self.make().append(
                neural_readout=neural(10,1),
                pre_safety_intent=intent(10,1,vx=0.02),
                safety_result=safety(intent(10,1,vx=0.02)),
                watchdog_result=watch(intent(10,1,vx=0.03)),
            )

        with self.assertRaises(CommandLoggerError):
            self.make().append(
                neural_readout=None,
                pre_safety_intent=None,
                safety_result=None,
                watchdog_result=watch(intent(10,1)),
            )

    def test_malformed_and_nonmonotonic_records_rejected(self):
        logger=self.make()
        bad=neural(10,1); bad["escape"]=math.nan
        with self.assertRaises(CommandLoggerError):
            logger.append(neural_readout=bad,pre_safety_intent=intent(10,1),
                          safety_result=safety(intent(10,1)),
                          watchdog_result=watch(intent(10,1)))
        stop=intent(10,1,stop=True,confidence=0.0)
        with self.assertRaises(CommandLoggerError):
            self.make().append(neural_readout=None,pre_safety_intent=None,safety_result=None,
                               watchdog_result=watch(stop,"safe_stop",None,True))
        logger.append(neural_readout=neural(10,1),pre_safety_intent=intent(10,1),
                      safety_result=safety(intent(10,1)),
                      watchdog_result=watch(intent(10,1)))
        with self.assertRaises(CommandLoggerError):
            logger.append(neural_readout=neural(10,2),pre_safety_intent=intent(10,2),
                          safety_result=safety(intent(10,2)),
                          watchdog_result=watch(intent(10,2)))

if __name__=="__main__":
    unittest.main()
