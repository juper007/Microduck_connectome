import math
import unittest

from microduck_connectome.command_logger import CommandLoggerError, CommandTrace
from microduck_connectome.control_contracts import make_behavior_intent

def neural(ts=10,seq=1,healthy=True):
    return {"timestamp_ns":ts,"sequence":seq,"steering_left":0.1,"steering_right":0.3,"escape":0.0,"runtime_healthy":healthy}

def safety(ts=10,seq=1,*,vyaw=0.1,clamped=False,reasons=None,stop=False):
    return {
        "intent":make_behavior_intent(timestamp_ns=ts,sequence=seq,vyaw=0.0 if stop else vyaw,stop=stop,confidence=0.8),
        "clamp_applied":clamped,
        "reasons":list(reasons or []),
    }

def watchdog(ts=20,seq=1,*,vyaw=0.1,state="healthy",reason=None,alive=True,stop=False):
    return {
        "intent":make_behavior_intent(timestamp_ns=ts,sequence=seq,vyaw=0.0 if stop else vyaw,stop=stop,confidence=0.0 if state=="safe_stop" else 0.8),
        "watchdog_state":state,
        "stale_reason":reason,
        "decoder_alive":alive,
    }

class CommandLoggerTests(unittest.TestCase):
    def new(self):
        return CommandTrace({"project_commit":"fixture","controller_config":"p5-test-v1"})

    def test_nominal_record_and_jsonl_are_deterministic(self):
        trace=self.new()
        pre=make_behavior_intent(timestamp_ns=10,sequence=1,vyaw=0.1,confidence=0.8)
        trace.append(neural_readout=neural(),pre_safety_intent=pre,
                     safety_result=safety(),watchdog_result=watchdog())
        row=trace.records()[0]
        self.assertEqual(row["pre_safety_intent"]["vyaw"],0.1)
        self.assertEqual(row["post_safety_intent"]["vyaw"],0.1)
        self.assertEqual(row["watchdog_intent"]["vyaw"],0.1)
        self.assertFalse(row["clamp_applied"])
        self.assertEqual(row["config_identity"]["controller_config"],"p5-test-v1")
        self.assertEqual(trace.to_jsonl(),trace.to_jsonl())

    def test_clamp_reason_is_reconstructible(self):
        trace=self.new()
        pre=make_behavior_intent(timestamp_ns=10,sequence=1,vyaw=0.5)
        trace.append(neural_readout=neural(),pre_safety_intent=pre,
                     safety_result=safety(vyaw=0.15,clamped=True,reasons=["vyaw_slew"]),
                     watchdog_result=watchdog(vyaw=0.15))
        row=trace.records()[0]
        self.assertTrue(row["clamp_applied"])
        self.assertEqual(row["clamp_reasons"],["vyaw_slew"])
        self.assertEqual(row["post_safety_intent"]["vyaw"],0.15)

    def test_watchdog_neutralization_and_stop_are_logged(self):
        trace=self.new()
        pre=make_behavior_intent(timestamp_ns=10,sequence=1,vyaw=0.2)
        trace.append(neural_readout=neural(),pre_safety_intent=pre,
                     safety_result=safety(vyaw=0.2),
                     watchdog_result=watchdog(ts=200,seq=1,state="safe_stop",reason="stale_neural",stop=True))
        row=trace.records()[0]
        self.assertTrue(row["stop_state"])
        self.assertEqual(row["stale_reason"],"stale_neural")
        self.assertEqual(row["watchdog_intent"]["vyaw"],0.0)

    def test_internal_stop_record_is_preserved(self):
        trace=self.new()
        pre=make_behavior_intent(timestamp_ns=10,sequence=1,stop=True)
        trace.append(neural_readout=neural(),pre_safety_intent=pre,
                     safety_result=safety(stop=True,clamped=True,reasons=["stop_override"]),
                     watchdog_result=watchdog(stop=True))
        row=trace.records()[0]
        self.assertTrue(row["pre_safety_intent"]["stop"])
        self.assertTrue(row["post_safety_intent"]["stop"])
        self.assertTrue(row["watchdog_intent"]["stop"])

    def test_records_are_detached_from_caller_and_reader(self):
        trace=self.new()
        source=neural()
        pre=make_behavior_intent(timestamp_ns=10,sequence=1)
        safe=safety()
        wd=watchdog()
        trace.append(neural_readout=source,pre_safety_intent=pre,safety_result=safe,watchdog_result=wd)
        source["steering_left"]=0.9
        safe["reasons"].append("later")
        copy=trace.records()
        copy[0]["config_identity"]["project_commit"]="changed"
        self.assertEqual(trace.records()[0]["neural_readout"]["steering_left"],0.1)
        self.assertEqual(trace.records()[0]["clamp_reasons"],[])
        self.assertEqual(trace.records()[0]["config_identity"]["project_commit"],"fixture")

    def test_malformed_records_are_rejected(self):
        trace=self.new()
        bad_neural=neural(); bad_neural["escape"]=math.nan
        with self.assertRaises(CommandLoggerError):
            trace.append(neural_readout=bad_neural,pre_safety_intent=None,safety_result=None,watchdog_result=watchdog())
        with self.assertRaises(CommandLoggerError):
            trace.append(neural_readout=neural(),pre_safety_intent=None,
                         safety_result={"intent":make_behavior_intent(timestamp_ns=10,sequence=1),"clamp_applied":False,"reasons":["vx_slew"]},
                         watchdog_result=watchdog())
        with self.assertRaises(CommandLoggerError):
            trace.append(neural_readout=neural(),pre_safety_intent=None,safety_result=None,
                         watchdog_result=watchdog(state="safe_stop",reason=None,stop=True))

    def test_trace_order_must_increase(self):
        trace=self.new()
        trace.append(neural_readout=None,pre_safety_intent=None,safety_result=None,
                     watchdog_result=watchdog(ts=20,seq=2,state="safe_stop",reason="decoder_crash",alive=False,stop=True))
        with self.assertRaises(CommandLoggerError):
            trace.append(neural_readout=None,pre_safety_intent=None,safety_result=None,
                         watchdog_result=watchdog(ts=20,seq=3,state="safe_stop",reason="decoder_crash",alive=False,stop=True))
        with self.assertRaises(CommandLoggerError):
            trace.append(neural_readout=None,pre_safety_intent=None,safety_result=None,
                         watchdog_result=watchdog(ts=30,seq=2,state="safe_stop",reason="decoder_crash",alive=False,stop=True))

    def test_identity_rejects_obvious_secret_and_local_path_fields(self):
        for identity in (
            {"api_token":"abc"},
            {"config_path":"/home/user/private.json"},
            {"config_path":"C:\\Users\\name\\private.json"},
        ):
            with self.subTest(identity=identity), self.assertRaises(CommandLoggerError):
                CommandTrace(identity)

if __name__=="__main__":
    unittest.main()
