"""Focused tests for the committed P7 v4 no-target control harness."""

from pathlib import Path
import hashlib
import json
import tempfile
import unittest

from scripts.p7_no_target_batch_v4 import (
    false_turn_from_trace, score_trace, summarize, validate_control_specs,
    verify_and_score_trace,
)


RULE = {
    "false_turn_rate_max": .05,
    "min_abs_robot_facing_vyaw_radps": .1,
    "min_sustained_duration_s": .2,
    "warmup_excluded_s": .6,
}


def trace(yaws):
    return [
        {"timestamp_ns": index * 20_000_000,
         "robot_facing_vyaw": yaw,
         "perception": {"timestamp_ns": index * 20_000_000}}
        for index, yaw in enumerate(yaws)
    ]


class FalseTurnTests(unittest.TestCase):
    def test_sustained_absolute_yaw_after_warmup_is_false_turn(self):
        rows = trace([.5] * 30 + [0.0] * 5 + [.1] * 11)
        score = false_turn_from_trace(rows, RULE)
        self.assertTrue(score["false_turn"])
        self.assertAlmostEqual(score["first_false_turn_window"]["duration_s"], .2)
        self.assertEqual(score["first_false_turn_window"]["start_timestamp_ns"],
                         700_000_000)

    def test_warmup_short_burst_and_subthreshold_are_excluded(self):
        rows = trace([.5] * 30 + [.099] * 12 + [.1] * 10 + [0.0])
        score = false_turn_from_trace(rows, RULE)
        self.assertFalse(score["false_turn"])
        self.assertAlmostEqual(score["max_sustained_abs_yaw_duration_s"], .18)

    def test_sign_reversal_still_counts_absolute_yaw(self):
        rows = trace([0.0] * 30 + [(-.2 if index % 2 else .2)
                                   for index in range(11)])
        self.assertTrue(false_turn_from_trace(rows, RULE)["false_turn"])

    def test_malformed_raw_trace_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "nonmonotonic"):
            false_turn_from_trace([trace([0.0])[0]] * 2, RULE)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "trace.jsonl"
            path.write_text('{"timestamp_ns":', encoding="utf-8")
            with self.assertRaises(Exception):
                score_trace(path, RULE)

    def test_summary_trace_spec_binding_rejects_mismatch(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            trace_path = folder / "trace.jsonl"
            summary_path = folder / "summary.json"
            spec_path = folder / "trial-spec.json"
            spec_path.write_text('{"seed": 1}\n', encoding="utf-8")
            rows = trace([0.0] * 45)
            payload = ("".join(json.dumps(row) + "\n" for row in rows)).encode("ascii")
            trace_path.write_bytes(payload)
            digest = hashlib.sha256(payload).hexdigest()
            spec_digest = hashlib.sha256(spec_path.read_bytes()).hexdigest()
            summary = {
                "artifact": {
                    "sha256": digest, "record_count": len(rows),
                    "start_timestamp_ns": rows[0]["timestamp_ns"],
                    "end_timestamp_ns": rows[-1]["timestamp_ns"],
                },
                "trial_spec_sha256": spec_digest,
                "experiment_sha256": "manifest",
                "walking_policy_sha256": "policy",
            }
            def checked():
                return verify_and_score_trace(
                    trace_path=trace_path, summary_path=summary_path,
                    spec_path=spec_path, rule=RULE,
                    manifest_sha256="manifest", policy_sha256="policy",
                    committed_spec_sha256=spec_digest,
                    journal_trace_sha256=digest,
                    journal_summary_sha256=summary_digest)
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            summary_digest = hashlib.sha256(summary_path.read_bytes()).hexdigest()
            self.assertFalse(checked()["false_turn"])

            tampered = trace([0.0] * 30 + [0.2] * 15)
            trace_path.write_text("".join(json.dumps(row) + "\n" for row in tampered),
                                  encoding="ascii")
            self.assertTrue(score_trace(trace_path, RULE)["false_turn"])
            with self.assertRaisesRegex(ValueError, "SHA mismatch"):
                checked()

            trace_path.write_bytes(payload)
            summary["artifact"]["record_count"] -= 1
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            summary_digest = hashlib.sha256(summary_path.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ValueError, "record count mismatch"):
                checked()

            summary["artifact"]["record_count"] = len(rows)
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            spec_path.write_text('{"seed": 2}\n', encoding="utf-8")
            summary["trial_spec_sha256"] = hashlib.sha256(spec_path.read_bytes()).hexdigest()
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            summary_digest = hashlib.sha256(summary_path.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ValueError, "SHA mismatch"):
                checked()


class ControlBatchGateTests(unittest.TestCase):
    @staticmethod
    def experiment():
        specs = [
            {"trial_id": f"p7-v4-no-target-{index:03d}", "seed": index,
             "target_present": False, "target_side": "none",
             "target_eccentricity": "none", "target_motion": "none",
             "visual_noise_level": "clean"}
            for index in range(1, 41)
        ]
        return {
            "schema_version": "steering-experiment-v4",
            "no_target_trial_count": 40,
            "no_target_trials": specs,
            "no_target_false_turn": RULE,
            "walking_policy": {"sha256": "policy"},
        }

    @staticmethod
    def rows(experiment):
        return [
            {"trial_id": spec["trial_id"], "spec": spec, "seed": spec["seed"],
             "outcome": "no_target", "trial_started": True, "trial_exit": 0,
             "summary_sha256": "summary", "trace_sha256": "trace",
             "safety_limit_violations": 0, "false_turn": False}
            for spec in experiment["no_target_trials"]
        ]

    @staticmethod
    def summarize(rows, experiment):
        return summarize(rows, experiment, head="head",
                         manifest_sha256="manifest", fixture_sha256="fixture",
                         journal_sha256="journal", started_utc="utc")

    def test_frozen_order_and_unique_seeds(self):
        experiment = self.experiment()
        self.assertEqual(len(validate_control_specs(experiment)), 40)
        experiment["no_target_trials"][1]["seed"] = 1
        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate_control_specs(experiment)

    def test_exact_40_and_at_most_two_false_turns(self):
        experiment = self.experiment()
        rows = self.rows(experiment)
        rows[0]["false_turn"] = rows[1]["false_turn"] = True
        passing = self.summarize(rows, experiment)
        self.assertEqual((passing["result"], passing["false_turn_rate"]),
                         ("PASS", .05))
        rows[2]["false_turn"] = True
        self.assertEqual(self.summarize(rows, experiment)["result"], "FAIL")
        rows[2]["false_turn"] = False
        self.assertEqual(self.summarize(rows[:-1], experiment)["result"], "FAIL")

    def test_invalid_safety_crash_or_unscored_trial_fails(self):
        experiment = self.experiment()
        rows = self.rows(experiment)
        rows[0]["outcome"] = "invalid"
        self.assertEqual(self.summarize(rows, experiment)["result"], "FAIL")
        rows[0]["outcome"] = "no_target"
        rows[0]["safety_limit_violations"] = 1
        self.assertEqual(self.summarize(rows, experiment)["result"], "FAIL")
        rows[0]["safety_limit_violations"] = 0
        rows[0]["trial_exit"] = 1
        self.assertEqual(self.summarize(rows, experiment)["result"], "FAIL")
        rows[0]["trial_exit"] = 0
        del rows[0]["false_turn"]
        self.assertEqual(self.summarize(rows, experiment)["result"], "FAIL")

    def test_reordered_controls_fail(self):
        experiment = self.experiment()
        rows = self.rows(experiment)
        rows[0], rows[1] = rows[1], rows[0]
        self.assertEqual(self.summarize(rows, experiment)["result"], "FAIL")


if __name__ == "__main__":
    unittest.main()
