"""Focused R1 evidence-durability and unchanged-science checks."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.p8_03_r1_durability import (checkpoint, classify_attempt,
                                         create_arm_marker, load_protocol,
                                         reconcile, run_child, stop_orphan_children)
from scripts.p8_03_score import manifest_check, planned
from scripts.p8_03_r1_remote import start, status
from scripts.p8_03_batch import recover_only


class DurabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root / "RS00" / "attempt-01"
        self.folder.mkdir(parents=True)
        self.identity = {"task": "P8-03-R1", "trial_id": "RS00",
                         "seed": 887200, "attempt": 1,
                         "source_head": "a" * 40, "config_sha256": "b" * 64}
        self.attempt = {"name": "attempt-01", "status": "ACQUIRING", "armed": False}

    def marker(self):
        return create_arm_marker(self.folder / "armed.json",
                                 task=self.identity["task"],
                                 trial_id=self.identity["trial_id"],
                                 seed=self.identity["seed"],
                                 attempt=self.identity["attempt"],
                                 source_head=self.identity["source_head"],
                                 config_hash=self.identity["config_sha256"],
                                 arm_ns=123456)

    def test_prearm_and_durable_arm(self):
        self.assertEqual(classify_attempt(self.folder, self.attempt,
                                          self.identity), "PRE_ARM")
        marker = self.marker()
        self.assertEqual(marker["state"], "ARMED")
        self.assertEqual(classify_attempt(self.folder, self.attempt,
                                          self.identity), "ARMED")
        with self.assertRaises(FileExistsError):
            self.marker()

    def test_active_or_untracked_child_cannot_be_prearm(self):
        (self.folder / "trial.log").touch()
        self.attempt["status"] = "TRIAL_CHILD_STARTED"
        self.assertEqual(classify_attempt(self.folder, self.attempt,
                                          self.identity), "UNKNOWN_ARM")
        record = {"pid": 456, "proc_start_ticks": "789"}
        (self.folder / "trial.log.process.json").write_text(json.dumps(record))
        with patch("scripts.p8_03_r1_durability.process_start_ticks",
                   return_value="789"):
            self.assertEqual(classify_attempt(self.folder, self.attempt,
                                              self.identity), "ACTIVE")

    def test_marker_disagreement_and_unknown_arm(self):
        self.marker()
        wrong = dict(self.identity, seed=887201)
        self.assertEqual(classify_attempt(self.folder, self.attempt,
                                          wrong), "UNKNOWN_ARM")
        self.attempt["status"] = "PREARM_FAILED"
        self.assertEqual(classify_attempt(self.folder, self.attempt,
                                          self.identity), "UNKNOWN_ARM")
        (self.folder / "armed.json").unlink()
        self.attempt["armed"] = True
        self.assertEqual(classify_attempt(self.folder, self.attempt,
                                          self.identity), "UNKNOWN_ARM")

    def test_recovery_never_retries_armed(self):
        self.marker()
        journal = {"schema_version": "p8-03-r1-batch-journal-v1",
                   "stage": "S", "source_head": "a" * 40,
                   "config_sha256": "b" * 64, "result": "RUNNING",
                   "ids": [{"trial_id": "RS00", "seed": 887200,
                            "attempts": [self.attempt]}]}
        checkpoint(self.root, journal, artifact_state="RUNNING")
        report = reconcile(self.root, journal)
        self.assertEqual(report["states"]["RS00/attempt-01"], "ARMED")
        self.assertEqual(report["retry_prohibited"], ["RS00/attempt-01"])

    def test_zero_byte_artifact_and_manifest_reconciliation(self):
        (self.folder / "down.log").touch()
        journal = {"schema_version": "p8-03-r1-batch-journal-v1",
                   "stage": "S", "source_head": "a" * 40,
                   "result": "RUNNING", "ids": []}
        checkpoint(self.root, journal, artifact_state="ACQUIRING")
        manifest = json.loads((self.root / "raw-manifest.json").read_text())
        row = next(x for x in manifest["files"] if x["path"] ==
                   "RS00/attempt-01/down.log")
        self.assertEqual((row["bytes"], row["record_count"],
                          row["artifact_class"], row["attempt"]),
                         (0, 0, "trial", "attempt-01"))
        self.assertEqual(manifest_check(self.root)["result"], "PASS")
        (self.folder / "down.log").write_bytes(b"partial")
        self.assertEqual(manifest_check(self.root)["result"], "FAIL")
        checkpoint(self.root, journal, artifact_state="RECOVERED_PARTIAL")
        self.assertEqual(manifest_check(self.root)["result"], "PASS")

    def test_lost_remote_status_does_not_restart(self):
        state = self.root / "launch"
        state.mkdir()
        output = self.root / "output"
        output.mkdir()
        launch = {"pid": 99999999, "proc_start_ticks": "1",
                  "command": ["python3.12", "scripts/p8_03_batch.py",
                              "--output", str(output)]}
        (state / "launch.json").write_text(json.dumps(launch))
        with patch("scripts.p8_03_r1_remote.proc_identity", return_value=None):
            self.assertEqual(status(state)["state"], "LOST_REQUIRES_RECOVERY")
        with self.assertRaises(FileExistsError):
            start(state, ["python3.12", "scripts/p8_03_batch.py", "--r1",
                          "--output", str(output), "--reviewed-head", "a" * 40])

    def test_recovery_refuses_live_supervisor_without_writing(self):
        journal = {"schema_version": "p8-03-r1-batch-journal-v1",
                   "supervisor_pid": 1234, "supervisor_start_ticks": "42",
                   "stage": "S", "source_head": "a" * 40, "ids": []}
        raw = json.dumps(journal).encode()
        (self.root / "batch-journal.json").write_bytes(raw)
        with patch("scripts.p8_03_batch.supervisor_liveness",
                   return_value="ACTIVE"):
            report = recover_only(self.root)
        self.assertEqual(report["result"], "REFUSED_ACTIVE_SUPERVISOR")
        self.assertEqual((self.root / "batch-journal.json").read_bytes(), raw)
        self.assertFalse((self.root / "recovery-report.json").exists())

    def test_recovery_refuses_unprovable_supervisor(self):
        journal = {"schema_version": "p8-03-r1-batch-journal-v1",
                   "supervisor_pid": 1234, "supervisor_start_ticks": None}
        raw = json.dumps(journal).encode()
        (self.root / "batch-journal.json").write_bytes(raw)
        with patch("scripts.p8_03_batch.supervisor_liveness",
                   return_value="UNPROVABLE"):
            report = recover_only(self.root)
        self.assertEqual(report["result"], "REFUSED_UNPROVABLE_SUPERVISOR")
        self.assertEqual((self.root / "batch-journal.json").read_bytes(), raw)

    def test_prearm_recovery_still_stops_and_probes(self):
        source = self.root / "source"
        (source / "config").mkdir(parents=True)
        execution = {"state_dir": str(self.root / "state"), "body_port": 7895,
                     "microduck_rl_path": str(self.root / "rl"),
                     "sim_executable": str(self.root / "sim")}
        (source / "config/p8_03_r1_execution_v1.json").write_text(
            json.dumps(execution))
        journal = {"schema_version": "p8-03-r1-batch-journal-v1",
                   "supervisor_pid": 1234, "supervisor_start_ticks": "42",
                   "source_path": str(source), "stage": "S",
                   "source_head": "a" * 40, "config_sha256": "b" * 64,
                   "result": "RUNNING", "final_sim_down": None,
                   "ids": [{"trial_id": "RS00", "seed": 887200,
                            "attempts": [self.attempt]}]}
        checkpoint(self.root, journal, artifact_state="RUNNING")
        with patch("scripts.p8_03_batch.supervisor_liveness",
                   return_value="ABSENT"), patch(
                       "scripts.p8_03_batch.emergency_stop",
                       return_value={"result": "PASS"}), patch(
                       "scripts.p8_03_batch.stop_orphan_children",
                       return_value=[]), patch(
                       "scripts.p8_03_batch.r1_run_child",
                       return_value=(0, False)), patch(
                       "scripts.p8_03_batch.probe_final_sim_state",
                       return_value={"result": "PASS"}):
            report = recover_only(self.root)
        self.assertEqual(report["states"]["RS00/attempt-01"], "PRE_ARM")
        self.assertEqual(report["cleanup"]["result"], "PASS")
        self.assertEqual(report["result"], "FAIL")
        self.assertEqual(manifest_check(self.root)["result"], "PASS")

    def test_scientific_matrix_only_changes_identity(self):
        root = Path(__file__).resolve().parents[1]
        master, protocol, _ = load_protocol(root)
        self.assertEqual([r["seed"] for r in planned(master, "S")],
                         list(range(887200, 887220)))
        self.assertEqual([r["seed"] for r in planned(master, "R")],
                         list(range(887300, 887320)))
        self.assertEqual((protocol["max_false_stops_per_set"],
                          protocol["max_false_stops_pooled"],
                          protocol["max_safety_limit_violations"]), (1, 2, 0))

    def test_sigint_forwards_to_child_group_and_accounts_log(self):
        class Child:
            pid = 123
            returncode = 130

            def poll(self):
                return None

            def wait(self, timeout):
                if timeout == .05:
                    raise KeyboardInterrupt()
                return self.returncode

        checkpoints = []
        with patch("scripts.p8_03_r1_durability.subprocess.Popen",
                   return_value=Child()), patch(
                       "scripts.p8_03_r1_durability.os.killpg", create=True) as kill:
            with self.assertRaises(KeyboardInterrupt):
                run_child(["sim", "down"], self.folder / "down.log", {},
                          created=lambda: checkpoints.append(True))
        self.assertEqual(len(checkpoints), 3)
        kill.assert_called_once()
        self.assertTrue((self.folder / "down.log").is_file())

    def test_launch_bookkeeping_failure_stops_child(self):
        class Child:
            pid = 123
            def poll(self):
                return None
            def wait(self, timeout):
                return 130
        with patch("scripts.p8_03_r1_durability.subprocess.Popen",
                   return_value=Child()), patch(
                       "scripts.p8_03_r1_durability.atomic_json",
                       side_effect=OSError("disk full")), patch(
                       "scripts.p8_03_r1_durability.os.killpg",
                       create=True) as kill:
            with self.assertRaises(OSError):
                run_child(["sim", "down"], self.folder / "down.log", {})
        kill.assert_called_once()

    def test_null_process_identity_is_not_live(self):
        record = {"pid": 123, "proc_start_ticks": None,
                  "parent_pid": 1, "parent_start_ticks": "42"}
        (self.folder / "down.log.process.json").write_text(json.dumps(record))
        original_iterdir = Path.iterdir
        def limited_iterdir(path):
            return iter(()) if path == Path("/proc") else original_iterdir(path)
        with patch.object(Path, "iterdir", limited_iterdir):
            rows = stop_orphan_children(self.root)
        self.assertEqual(rows[0]["state"], "UNKNOWN_IDENTITY")

    def test_final_down_failure_is_fail_closed(self):
        from scripts.p8_03_batch import final_gate_pass
        self.assertFalse(final_gate_pass(False, {"result": "PASS"},
                                         {"exit": 1, "state_probe_result": "PASS"}))
        self.assertFalse(final_gate_pass(False, {"result": "PASS"},
                                         {"exit": 0, "state_probe_result": "FAIL"}))


if __name__ == "__main__":
    unittest.main()
