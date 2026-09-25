"""Source-only checks for the P7-03 preregistration and control batch."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts.p7_03_preregister import ROOT, SOURCE_SHA256, generate
from scripts.p7_03_no_target_batch import (
    false_turn_from_trace, summarize, validate_control_specs,
    validate_reused_target_evidence, verify_and_score_trace,
)


SOURCE = ROOT / "config/steering_experiment_v4.json"
MANIFEST = ROOT / "config/steering_no_target_p7_03_v1.json"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class P703PreregTests(unittest.TestCase):
    def setUp(self):
        self.source = json.loads(SOURCE.read_text(encoding="utf-8"))
        self.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def test_new_manifest_is_exact_deterministic_generation(self):
        self.assertEqual(sha(SOURCE), SOURCE_SHA256)
        self.assertEqual(self.manifest, generate(self.source, source_sha256=sha(SOURCE)))
        self.assertEqual(self.manifest["experiment_version"], "p7-03-no-target-v1")
        self.assertEqual(len(validate_control_specs(self.manifest)), 40)

    def test_new_controls_disjoint_balanced_and_frozen(self):
        old = self.source["target_trials"] + self.source["no_target_trials"]
        new = self.manifest["no_target_trials"]
        self.assertFalse({row["seed"] for row in old} & {row["seed"] for row in new})
        self.assertFalse({row["trial_id"] for row in old} & {row["trial_id"] for row in new})
        self.assertEqual(sum(row["visual_noise_level"] == "clean" for row in new), 20)
        self.assertEqual(sum(row["visual_noise_level"] == "moderate" for row in new), 20)
        for field in ("target_trials", "walking_policy", "config_sha256",
                      "target_response", "no_target_false_turn", "validity",
                      "graph_key", "microduck_commit", "microduck_rl_commit"):
            self.assertEqual(self.manifest[field], self.source[field], field)
        self.assertEqual(self.manifest["p7_03"]["target_evidence_reused"]
                         ["valid_target_trials"], 120)
        self.assertEqual(self.manifest["p7_03"]["target_evidence_reused"]
                         ["correct_target_trials"], 108)

    def test_old_seed_and_changed_threshold_cannot_be_regenerated(self):
        old = self.source["no_target_trials"][0]["seed"]
        self.assertNotIn(old, [row["seed"] for row in self.manifest["no_target_trials"]])
        altered = deepcopy(self.source)
        altered["no_target_false_turn"]["false_turn_rate_max"] = .1
        with self.assertRaisesRegex(ValueError, "frozen"):
            generate(altered, source_sha256=SOURCE_SHA256)

    def test_reused_target_evidence_hash_and_result_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            summary_path = folder / "summary.json"
            journal_path = folder / "journal.jsonl"
            journal_path.write_text('{"trial_id":"target-001"}\n', encoding="utf-8")
            summary = {
                "result": "PASS", "evaluated_valid_target_trials": 120,
                "counts": {"correct": 108}, "safety_limit_violations": 0,
                "source_head": "fdde4578f0705a1a30cfe1c2ea5d5e48faf0d2aa",
                "experiment_sha256": SOURCE_SHA256,
                "walking_policy_sha256": self.manifest["walking_policy"]["sha256"],
            }
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            modified = deepcopy(self.manifest)
            ref = modified["p7_03"]["target_evidence_reused"]
            ref.update({"summary_path": str(summary_path), "summary_sha256": sha(summary_path),
                        "journal_path": str(journal_path), "journal_sha256": sha(journal_path)})
            self.assertEqual(validate_reused_target_evidence(modified), summary)
            journal_path.write_text("tampered\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "journal hash mismatch"):
                validate_reused_target_evidence(modified)


class P703BatchTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def rows(self):
        return [
            {"trial_id": spec["trial_id"], "seed": spec["seed"], "spec": spec,
             "outcome": "no_target", "trial_started": True, "trial_exit": 0,
             "summary_sha256": "summary", "trace_sha256": "trace",
             "safety_limit_violations": 0, "false_turn": False}
            for spec in self.manifest["no_target_trials"]
        ]

    def result(self, rows):
        return summarize(rows, self.manifest, head="head",
                         manifest_sha256="manifest", fixture_sha256="fixture",
                         journal_sha256="journal", started_utc="utc")

    def test_frozen_rate_and_fail_closed_batch_gate(self):
        rows = self.rows()
        rows[0]["false_turn"] = rows[1]["false_turn"] = True
        self.assertEqual(self.result(rows)["result"], "PASS")
        self.assertEqual(self.result(rows)["false_turn_rate"], .05)
        rows[2]["false_turn"] = True
        self.assertEqual(self.result(rows)["result"], "FAIL")
        rows[2]["false_turn"] = False
        rows[0]["trial_exit"] = 1
        self.assertEqual(self.result(rows)["result"], "FAIL")
        rows[0]["trial_exit"] = 0
        rows[0]["safety_limit_violations"] = 1
        self.assertEqual(self.result(rows)["result"], "FAIL")
        self.assertEqual(self.result(rows[:-1])["result"], "FAIL")

    def test_sustained_abs_yaw_rule(self):
        rule = self.manifest["no_target_false_turn"]
        records = [
            {"timestamp_ns": index * 20_000_000,
             "robot_facing_vyaw": .2 if index >= 30 else 0.,
             "perception": {"timestamp_ns": index * 20_000_000}}
            for index in range(41)
        ]
        self.assertTrue(false_turn_from_trace(records, rule)["false_turn"])
        self.assertFalse(false_turn_from_trace(records[:40], rule)["false_turn"])

    def test_scored_trace_must_match_trial_artifact_and_spec(self):
        rule = self.manifest["no_target_false_turn"]
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            spec_path = folder / "trial-spec.json"
            trace_path = folder / "trace.jsonl"
            summary_path = folder / "summary.json"
            spec_path.write_text('{"seed":1}\n', encoding="utf-8")
            records = [
                {"timestamp_ns": index * 20_000_000,
                 "robot_facing_vyaw": 0.,
                 "perception": {"timestamp_ns": index * 20_000_000}}
                for index in range(41)
            ]
            trace_path.write_text("".join(json.dumps(row) + "\n" for row in records),
                                  encoding="ascii")
            summary = {
                "artifact": {"sha256": sha(trace_path), "record_count": len(records),
                             "start_timestamp_ns": 0,
                             "end_timestamp_ns": records[-1]["timestamp_ns"]},
                "trial_spec_sha256": sha(spec_path),
                "experiment_sha256": "manifest", "walking_policy_sha256": "policy",
            }
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            def checked():
                return verify_and_score_trace(
                    trace_path=trace_path, summary_path=summary_path, spec_path=spec_path,
                    rule=rule, manifest_sha256="manifest", policy_sha256="policy",
                    committed_spec_sha256=sha(spec_path),
                    journal_trace_sha256=summary["artifact"]["sha256"],
                    journal_summary_sha256=sha(summary_path))
            self.assertFalse(checked()["false_turn"])
            summary["artifact"]["record_count"] -= 1
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "record count"):
                checked()
            summary["artifact"]["record_count"] = len(records)
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            records[-1]["robot_facing_vyaw"] = .2
            trace_path.write_text("".join(json.dumps(row) + "\n" for row in records),
                                  encoding="ascii")
            with self.assertRaisesRegex(ValueError, "SHA mismatch"):
                checked()


if __name__ == "__main__":
    unittest.main()
