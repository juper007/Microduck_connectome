"""Regression checks for retaining a failed Thor batch's aggregate manifest."""

from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import g8_r5c_batch as batch


class G8R5cBatchTests(unittest.TestCase):
    def run_fake_batch(self, *, trial_exit=0, trial_summary="{invalid", trial_raises=False):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "config").mkdir()
            (root / "config/g8_r5c_neural_stop_v1.json").write_text(json.dumps({
                "scenario_seeds": [80101, 80111, 80121],
                "required_successful_independent_trials": 3,
                "walking_policy_path": "/pinned/policy.onnx",
                "walking_policy_sha256": "pinned",
            }))
            microduck = root / "microduck"
            (microduck / "scripts").mkdir(parents=True)
            output = root / "output"
            argv = ["g8_r5c_batch.py", "--root", str(root), "--microduck", str(microduck),
                    "--microduck-rl", str(root / "rl"), "--output", str(output),
                    "--sim-state", str(root / "sim"), "--body-port", "18801",
                    "--development-probe"]

            def run_logged(command, log, **kwargs):
                log = Path(log)
                log.parent.mkdir(parents=True, exist_ok=True)
                log.write_text("{}" if log.name == "policy-readback.json" else "test log\n")
                if log.name == "trial.log":
                    (log.parent / "summary.json").write_text(trial_summary)
                    if trial_raises:
                        raise OSError("trial launcher failed")
                    return trial_exit
                return 0

            with (patch.object(batch.socket, "gethostname", return_value="jetsonthor-test"),
                  patch.object(batch.platform, "python_version_tuple", return_value=("3", "12", "0")),
                  patch.object(batch.subprocess, "check_output", return_value="fixture-head\n"),
                  patch.object(batch, "run_logged", side_effect=run_logged),
                  patch.object(batch, "validate_loaded_walk_policy"),
                  patch.object(batch.time, "sleep"),
                  patch.object(batch.sys, "argv", argv),
                  redirect_stdout(io.StringIO())):
                with self.assertRaises(SystemExit) as exit_result:
                    batch.main()
            self.assertEqual(exit_result.exception.code, 1)
            return json.loads((output / "batch-summary.json").read_text())

    def test_malformed_started_trial_keeps_aggregate_and_raw_summary(self):
        report = self.run_fake_batch()
        self.assertEqual(report["result"], "PROBE_ERROR")
        self.assertEqual(report["completed_trials"], 1)
        self.assertTrue(report["trials"][0]["trial_started"])
        self.assertIn("JSONDecodeError", report["trials"][0]["failure"])
        self.assertIn("summary_sha256", report["trials"][0])

    def test_trial_launcher_exception_keeps_aggregate(self):
        report = self.run_fake_batch(trial_raises=True)
        self.assertIn("trial launcher failed", report["trials"][0]["failure"])
        self.assertEqual(report["final_sim_down"]["exit"], 0)

    def test_nonzero_trial_exit_cannot_pass_even_with_pass_summary(self):
        report = self.run_fake_batch(trial_exit=7, trial_summary='{"result":"PASS"}')
        self.assertEqual(report["result"], "PROBE_ERROR")
        self.assertEqual(report["trials"][0]["trial_exit"], 7)

    def test_pass_summary_requires_hashed_raw_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            with self.assertRaisesRegex(ValueError, "missing trace_artifact"):
                batch.validate_trial_artifacts({"result": "PASS"}, folder)


if __name__ == "__main__":
    unittest.main()
