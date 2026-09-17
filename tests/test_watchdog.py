import math
from pathlib import Path
import unittest

from microduck_connectome.control_contracts import make_behavior_intent
from microduck_connectome.watchdog import ControlWatchdog, WatchdogError, load_watchdog_config

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "watchdog_v1.json"


def neural(ts=0, seq=0, healthy=True, **changes):
    value = {
        "timestamp_ns": ts,
        "sequence": seq,
        "steering_left": 0.0,
        "steering_right": 0.0,
        "escape": 0.0,
        "runtime_healthy": healthy,
    }
    value.update(changes)
    return value


def intent(ts=0, seq=0, **changes):
    value = dict(
        timestamp_ns=ts,
        sequence=seq,
        vx=0.0,
        vy=0.0,
        vyaw=0.0,
        stop=False,
        confidence=1.0,
    )
    value.update(changes)
    return make_behavior_intent(**value)


class WatchdogTests(unittest.TestCase):
    def test_config_ttls_are_frozen(self):
        cfg = load_watchdog_config(CONFIG_PATH)
        self.assertEqual((cfg.neural_readout_ttl_ms, cfg.behavior_intent_ttl_ms), (100, 100))

    def test_exact_100ms_is_fresh_and_plus_one_ns_is_stale(self):
        wd = ControlWatchdog()
        n = neural(ts=1_000_000_000, seq=1)
        b = intent(ts=1_000_000_000, seq=1, vx=0.02)
        fresh = wd.evaluate(n, b, now_ns=1_100_000_000, fallback_sequence=1)
        self.assertFalse(fresh["watchdog_triggered"])
        stale = wd.evaluate(n, b, now_ns=1_100_000_001, fallback_sequence=2)
        self.assertTrue(stale["watchdog_triggered"])
        self.assertIn("stale_neural", stale["reasons"])
        self.assertIn("stale_behavior", stale["reasons"])
        self.assertTrue(stale["intent"]["stop"])
        self.assertEqual(
            (stale["intent"]["vx"], stale["intent"]["vy"], stale["intent"]["vyaw"]),
            (0.0, 0.0, 0.0),
        )

    def test_missing_inputs_and_decoder_unavailable_are_safe(self):
        cases = [
            (None, intent(ts=10, seq=1), "missing_neural"),
            (neural(ts=10, seq=1), None, "missing_behavior"),
        ]
        for n, b, reason in cases:
            with self.subTest(reason=reason):
                result = ControlWatchdog().evaluate(
                    n, b, now_ns=10, fallback_sequence=2
                )
                self.assertTrue(result["intent"]["stop"])
                self.assertIn(reason, result["reasons"])
        unavailable = ControlWatchdog().evaluate(
            neural(ts=10, seq=1),
            intent(ts=10, seq=1, vx=0.08),
            now_ns=10,
            fallback_sequence=2,
            decoder_available=False,
        )
        self.assertTrue(unavailable["intent"]["stop"])
        self.assertIn("decoder_unavailable", unavailable["reasons"])

    def test_runtime_unhealthy_is_safe(self):
        result = ControlWatchdog().evaluate(
            neural(ts=10, seq=1, healthy=False),
            intent(ts=10, seq=1, vx=0.08),
            now_ns=10,
            fallback_sequence=2,
        )
        self.assertTrue(result["intent"]["stop"])
        self.assertIn("runtime_unhealthy", result["reasons"])

    def test_malformed_future_and_mismatched_inputs_fail_closed(self):
        bad = neural(ts=10, seq=1)
        bad["steering_left"] = math.nan
        malformed = ControlWatchdog().evaluate(
            bad, intent(ts=10, seq=1), now_ns=10, fallback_sequence=2
        )
        self.assertIn("invalid_neural", malformed["reasons"])

        future = ControlWatchdog().evaluate(
            neural(ts=20, seq=2),
            intent(ts=20, seq=2),
            now_ns=10,
            fallback_sequence=3,
        )
        self.assertIn("future_neural", future["reasons"])
        self.assertIn("future_behavior", future["reasons"])

        mismatch = ControlWatchdog().evaluate(
            neural(ts=10, seq=1),
            intent(ts=11, seq=2),
            now_ns=11,
            fallback_sequence=3,
        )
        self.assertIn("metadata_mismatch", mismatch["reasons"])

    def test_repeated_same_fresh_sample_is_allowed_until_ttl(self):
        wd = ControlWatchdog()
        n = neural(ts=10, seq=1)
        b = intent(ts=10, seq=1, vx=0.02)
        first = wd.evaluate(n, b, now_ns=10, fallback_sequence=1)
        second = wd.evaluate(n, b, now_ns=50_000_010, fallback_sequence=1)
        self.assertFalse(first["watchdog_triggered"])
        self.assertFalse(second["watchdog_triggered"])

    def test_regressing_metadata_fails_closed(self):
        wd = ControlWatchdog()
        wd.evaluate(
            neural(ts=100, seq=2),
            intent(ts=100, seq=2),
            now_ns=100,
            fallback_sequence=2,
        )
        result = wd.evaluate(
            neural(ts=90, seq=1),
            intent(ts=90, seq=1),
            now_ns=110,
            fallback_sequence=3,
        )
        self.assertIn("nonmonotonic_neural", result["reasons"])
        self.assertIn("nonmonotonic_behavior", result["reasons"])
        self.assertTrue(result["intent"]["stop"])

    def test_recovery_after_fault_with_advancing_sample(self):
        wd = ControlWatchdog()
        wd.evaluate(
            neural(ts=100, seq=1),
            intent(ts=100, seq=1, vx=0.02),
            now_ns=100,
            fallback_sequence=1,
        )
        failed = wd.evaluate(
            None,
            None,
            now_ns=200,
            fallback_sequence=2,
            decoder_available=False,
        )
        self.assertTrue(failed["intent"]["stop"])
        recovered = wd.evaluate(
            neural(ts=300, seq=3),
            intent(ts=300, seq=3, vx=0.03),
            now_ns=300,
            fallback_sequence=3,
        )
        self.assertFalse(recovered["watchdog_triggered"])
        self.assertEqual(recovered["intent"]["vx"], 0.03)

    def test_fallback_metadata_cannot_move_backward(self):
        wd = ControlWatchdog()
        wd.evaluate(None, None, now_ns=100, fallback_sequence=5)
        with self.assertRaises(WatchdogError):
            wd.evaluate(None, None, now_ns=99, fallback_sequence=6)
        with self.assertRaises(WatchdogError):
            wd.evaluate(None, None, now_ns=101, fallback_sequence=4)


if __name__ == "__main__":
    unittest.main()
