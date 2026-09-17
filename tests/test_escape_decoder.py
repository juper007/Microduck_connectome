import math
from pathlib import Path
import unittest

from microduck_connectome.control_contracts import make_behavior_intent
from microduck_connectome.escape_decoder import (
    EscapeDecoder, EscapeDecoderConfig, EscapeDecoderError, load_escape_decoder_config
)

ROOT=Path(__file__).resolve().parents[1]
CONFIG_PATH=ROOT/"config"/"escape_decoder_v1.json"

def readout(escape, healthy=True):
    return {
        "timestamp_ns":10,"sequence":2,
        "steering_left":0.0,"steering_right":0.0,
        "escape":escape,"runtime_healthy":healthy,
    }

class EscapeDecoderTests(unittest.TestCase):
    def test_config_loads(self):
        config=load_escape_decoder_config(CONFIG_PATH)
        self.assertEqual((config.gain,config.threshold),(1.0,0.5))

    def test_below_threshold_passes_base_intent(self):
        decoder=EscapeDecoder(EscapeDecoderConfig(1.0,0.5))
        base=make_behavior_intent(timestamp_ns=10,sequence=2,vyaw=0.2,confidence=0.7)
        self.assertEqual(decoder.apply(readout(0.49),base),base)

    def test_threshold_and_above_assert_stop_with_zero_motion(self):
        decoder=EscapeDecoder(EscapeDecoderConfig(1.0,0.5))
        for value in (0.5,1.0):
            with self.subTest(value=value):
                base=make_behavior_intent(timestamp_ns=10,sequence=2,vx=0.08,vyaw=0.4)
                result=decoder.apply(readout(value),base)
                self.assertTrue(result["stop"])
                self.assertEqual((result["vx"],result["vy"],result["vyaw"]),(0.0,0.0,0.0))

    def test_gain_is_applied_before_threshold(self):
        decoder=EscapeDecoder(EscapeDecoderConfig(2.0,0.5))
        self.assertTrue(decoder.apply(readout(0.25))["stop"])

    def test_unhealthy_runtime_is_safe_stop(self):
        result=EscapeDecoder(EscapeDecoderConfig()).apply(readout(0.0,healthy=False))
        self.assertTrue(result["stop"])
        self.assertEqual((result["vx"],result["vy"],result["vyaw"]),(0.0,0.0,0.0))
        self.assertEqual(result["confidence"],0.0)

    def test_existing_stop_is_never_cleared(self):
        base=make_behavior_intent(timestamp_ns=10,sequence=2,stop=True)
        self.assertTrue(EscapeDecoder(EscapeDecoderConfig()).apply(readout(0.0),base)["stop"])

    def test_invalid_activity_and_metadata_are_rejected(self):
        for value in (-0.1,1.1,math.nan,math.inf,True):
            sample=readout(0.0); sample["escape"]=value
            with self.subTest(value=value), self.assertRaises(EscapeDecoderError):
                EscapeDecoder(EscapeDecoderConfig()).apply(sample)
        mismatched=make_behavior_intent(timestamp_ns=11,sequence=2)
        with self.assertRaises(EscapeDecoderError):
            EscapeDecoder(EscapeDecoderConfig()).apply(readout(0.0),mismatched)

    def test_config_validation(self):
        for args in ((0,0.5),(math.inf,0.5),(1.0,0),(1.0,1.1),(1.0,True)):
            with self.subTest(args=args), self.assertRaises(EscapeDecoderError):
                EscapeDecoderConfig(*args)

    def test_deterministic(self):
        decoder=EscapeDecoder(EscapeDecoderConfig())
        sample=readout(0.7)
        self.assertEqual(decoder.apply(sample),decoder.apply(sample))

if __name__=="__main__":
    unittest.main()
