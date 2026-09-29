"""The failed prearm attempt remains auditable without a motion journal."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.p8_03_score import manifest_check
from scripts.p8_03_timing_score import _score_trial, score_batch
from scripts.p8_03_trial import json_write, motion_journal_evidence


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FinalizationLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.folder = self.root / "TPR2A-001" / "attempt-01"
        self.folder.mkdir(parents=True)
        self.spec = {"reset_id": "TPR2A-001", "ordinal": 0}
        self.config = {"schema_version": "p8-03-timing-probe-v2",
                       "scored_window_ms": 1000, "visual_hz": 20,
                       "neural_hz": 50, "control_hz": 50,
                       "development_gate": {"ids": [
                           {"reset_id": f"TPR2A-{i:03d}", "ordinal": i - 1}
                           for i in range(1, 4)]}}
        events = [{"kind": "fixture_error", "timestamp_ns": 10,
                   "error": "RuntimeError: measured moving-body precondition failed"}]
        for filename, rows in (("events.jsonl", events),
                               ("neural-ledger.jsonl", []),
                               ("visual-frames.jsonl", []),
                               ("timing-ledger.jsonl", [])):
            (self.folder / filename).write_text(
                "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        json_write(self.folder / "local-reference.json",
                   {"result": "PASS", "reset_id": "TPR2A-001"})
        self.summary = {
            "reset_id": "TPR2A-001", "armed": False,
            "fixture_errors": [events[0]["error"]],
            "motion_coordinator_reached": False,
            "motion_journal": motion_journal_evidence(
                self.folder / "motion-request-journal.jsonl", coordinator_reached=False),
            "motion_request_journal_sha256": None,
            "event_sha256": digest(self.folder / "events.jsonl"),
            "neural_ledger_sha256": digest(self.folder / "neural-ledger.jsonl"),
            "visual_sha256": digest(self.folder / "visual-frames.jsonl"),
            "timing_ledger_sha256": digest(self.folder / "timing-ledger.jsonl")}
        json_write(self.folder / "summary.json", self.summary)

    def tearDown(self):
        self.tmp.cleanup()

    def test_precoordinator_failure_has_durable_summary_and_optional_journal(self):
        summary = json.loads((self.folder / "summary.json").read_text())
        self.assertEqual(summary["motion_journal"], {
            "present": False, "sha256": None,
            "reason": "not_created_before_precondition_failure",
            "lifecycle": "OPTIONAL_NOT_REACHED_ARTIFACT"})
        self.assertFalse((self.folder / "motion-request-journal.jsonl").exists())
        result = _score_trial(self.folder, self.spec, self.config)
        self.assertEqual(result["motion_journal_lifecycle"],
                         "OPTIONAL_NOT_REACHED_ARTIFACT")
        self.assertEqual(result["primary_fixture_errors"], self.summary["fixture_errors"])
        self.assertIn("prearm_not_armed", result["failure_causes"])
        self.assertNotIn("motion_request_journal_required_missing",
                         result["failure_causes"])
        self.assertNotIn("raw_unreadable:FileNotFoundError", result["failure_causes"])

    def test_missing_journal_after_coordinator_is_integrity_failure(self):
        self.summary["motion_coordinator_reached"] = True
        self.summary["motion_journal"] = motion_journal_evidence(
            self.folder / "motion-request-journal.jsonl", coordinator_reached=True)
        json_write(self.folder / "summary.json", self.summary)
        result = _score_trial(self.folder, self.spec, self.config)
        self.assertEqual(result["motion_journal_lifecycle"],
                         "REQUIRED_BUT_MISSING_ARTIFACT")
        self.assertIn("motion_request_journal_required_missing", result["failure_causes"])
        self.assertEqual(result["primary_fixture_errors"], self.summary["fixture_errors"])

    def test_false_optional_claim_with_coordinator_rows_is_integrity_failure(self):
        with (self.folder / "timing-ledger.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"kind": "motion_attempt", "timestamp_ns": 9}) + "\n")
        self.summary["timing_ledger_sha256"] = digest(self.folder / "timing-ledger.jsonl")
        json_write(self.folder / "summary.json", self.summary)
        result = _score_trial(self.folder, self.spec, self.config)
        self.assertIn("motion_request_journal_required_missing", result["failure_causes"])

    def test_manifest_accepts_absent_optional_journal_without_fake_file(self):
        files = []
        for path in sorted(self.root.rglob("*")):
            if path.is_file():
                files.append({"path": path.relative_to(self.root).as_posix(),
                              "sha256": digest(path), "bytes": path.stat().st_size,
                              "record_count": len(path.read_bytes().splitlines())})
        json_write(self.root / "raw-manifest.json", {
            "schema_version": "p8-03-local-raw-manifest-v1", "files": files})
        self.assertEqual(manifest_check(self.root)["result"], "PASS")

    def test_final_down_and_raw_probe_are_still_required(self):
        (self.root / "final-down.log").write_text("down\n", encoding="utf-8")
        json_write(self.root / "final-state-probe.json", {"result": "PASS"})
        journal = {"ids": [{"reset_id": "TPR2A-001", "attempts": [
            {"name": "attempt-01", "armed": False, "status": "INTERRUPTED_UNKNOWN_ARM",
             "trial_exit": 1}], "status": "INTERRUPTED_UNKNOWN_ARM"}],
            "final_sim_down": {"exit": 0, "interrupted": False,
                               "state_probe_result": "PASS",
                               "sha256": digest(self.root / "final-down.log"),
                               "state_probe_sha256": digest(
                                   self.root / "final-state-probe.json")}}
        json_write(self.root / "batch-journal.json", journal)
        score = score_batch(self.root, self.config)
        self.assertTrue(score["final_down_raw_valid"])
        self.assertEqual(score["trials"][0]["motion_journal_lifecycle"],
                         "OPTIONAL_NOT_REACHED_ARTIFACT")
        journal["final_sim_down"]["state_probe_result"] = "FAIL"
        json_write(self.root / "batch-journal.json", journal)
        self.assertFalse(score_batch(self.root, self.config)["final_down_raw_valid"])


if __name__ == "__main__":
    unittest.main()
