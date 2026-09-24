"""The v4 batch gate counts invalid resets and no-response trials correctly."""

import unittest

from scripts.p7_target_batch_v4 import summarize


class BatchV4GateTests(unittest.TestCase):
    def test_gate_requires_100_valid_90_percent_correct_and_zero_safety(self):
        experiment = {"target_trial_count": 120,
                      "target_response": {"correct_direction_rate_min": .90},
                      "walking_policy": {"sha256": "policy"}}
        def make(outcome, index):
            return {"trial_id": str(index), "outcome": outcome,
                    "trial_started": True, "trial_exit": 0,
                    "summary_sha256": "summary", "trace_sha256": "trace",
                    "spec": {"target_side": "left", "target_eccentricity": "medium",
                             "target_motion": "static", "visual_noise_level": "clean"},
                    "response": None, "safety_limit_violations": 0}
        rows = [make("correct", index) for index in range(108)]
        rows += [make("no_response", index) for index in range(108, 120)]
        kwargs = {"head": "head", "manifest_hash": "manifest",
                  "journal_hash": "journal", "started_utc": "utc"}
        passing = summarize(rows, experiment, **kwargs)
        self.assertEqual(passing["result"], "PASS")
        self.assertEqual(passing["correct_direction_rate"], .9)
        rows[0]["outcome"] = "invalid"
        self.assertEqual(summarize(rows, experiment, **kwargs)["result"], "FAIL")
        rows[0]["outcome"] = "correct"
        rows[0]["safety_limit_violations"] = 1
        self.assertEqual(summarize(rows, experiment, **kwargs)["result"], "FAIL")
        rows[0]["safety_limit_violations"] = 0
        invalid = [make("invalid", index) for index in range(99)]
        invalid += [make("correct", index) for index in range(99, 120)]
        self.assertEqual(summarize(invalid, experiment, **kwargs)["result"], "FAIL")

    def test_started_trial_crash_cannot_be_hidden_by_valid_trial_buffer(self):
        experiment = {"target_trial_count": 120,
                      "target_response": {"correct_direction_rate_min": .90},
                      "walking_policy": {"sha256": "policy"}}
        spec = {"target_side": "left", "target_eccentricity": "medium",
                "target_motion": "static", "visual_noise_level": "clean"}
        rows = [{"trial_id": str(index), "outcome": "correct", "spec": spec,
                 "trial_started": True, "trial_exit": 0,
                 "summary_sha256": "summary", "trace_sha256": "trace",
                 "safety_limit_violations": 0, "response": None}
                for index in range(119)]
        rows.append({"trial_id": "crashed", "outcome": "invalid", "spec": spec,
                     "trial_started": True, "trial_exit": 1})
        kwargs = {"head": "head", "manifest_hash": "manifest",
                  "journal_hash": "journal", "started_utc": "utc"}
        result = summarize(rows, experiment, **kwargs)
        self.assertEqual(result["result"], "FAIL")
        self.assertEqual(result["started_trial_failures"], ["crashed"])
        rows[-1] = {"trial_id": "pretrial-rejected", "outcome": "invalid",
                    "spec": spec, "trial_started": False}
        self.assertEqual(summarize(rows, experiment, **kwargs)["result"], "PASS")


if __name__ == "__main__":
    unittest.main()
