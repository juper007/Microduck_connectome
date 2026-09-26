"""No-seed adversarial checks for the prospective R1 supervisor."""
from __future__ import annotations

from argparse import Namespace
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts.p8_02_r1_batch import (checkpoint, inventory, planned_rows, preflight,
                                     recover_only, require_development_gate, run)
from scripts.p8_02_r1_score import score_batch
from scripts.p8_02_r1_trial import (append_progress, validate_r1_material,
                                    validate_r1_selection, write_arm_marker)


ROOT = Path(__file__).resolve().parents[1]
R1 = json.loads((ROOT / "config/p8_02_r1_protocol_v1.json").read_text())


class R1HarnessTests(unittest.TestCase):
    def test_frozen_d_b_selection_rejects_seed_change(self):
        for stage in "db":
            config = json.loads((ROOT / f"config/p8_02_r1_{stage}_execution_v1.json").read_text())
            self.assertEqual(validate_r1_selection(config)[1], 20)
            config["ordered_official_runs"][0]["seed"] += 1
            with self.assertRaisesRegex(RuntimeError, "matrix"):
                validate_r1_selection(config)

    def test_r1_material_rejects_selected_threshold_change_before_external_checks(self):
        config=json.loads((ROOT/"config/p8_02_r1_d_execution_v1.json").read_text())
        config["escape_threshold"]=0.4
        with self.assertRaisesRegex(RuntimeError,"selected A controller"):
            validate_r1_material(ROOT,config)

    def test_fixed_planned_ids_reject_relabeling(self):
        for stage in "DB":
            data = json.loads(json.dumps(R1))
            self.assertEqual(len(planned_rows(data, stage)), 3 if stage == "D" else 20)
            key = "development_gate" if stage == "D" else None
            rows = data[key]["ordered_runs"] if key else data["ordered_official_runs"]
            rows[0]["seed"] += 1
            with self.assertRaisesRegex(RuntimeError, "seed"):
                planned_rows(data, stage)

    def test_wrong_operator_path_aborts_before_output_or_ids_and_audits(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            source = parent / "source"
            (source / "config").mkdir(parents=True)
            expected_upstream = parent / "expected-microduck"
            supplied_upstream = parent / "wrong-microduck"
            for path in (expected_upstream, supplied_upstream, parent / "rl"):
                path.mkdir()
            protocol = json.loads(json.dumps(R1))
            protocol["official_execution"]["source_path"] = str(source)
            protocol["official_execution"]["microduck_path"] = str(expected_upstream)
            protocol["official_execution"]["preflight_audit_log_path"] = str(parent / "external-audit.jsonl")
            protocol_path = source / "config/p8_02_r1_protocol_v1.json"
            protocol_path.write_text(json.dumps(protocol))
            execution_path = source / "config/p8_02_r1_d_execution_v1.json"
            execution_path.write_text("{}")
            output = parent / "must-not-exist"
            args = Namespace(stage="D", root=source, protocol=protocol_path,
                execution=execution_path, microduck=supplied_upstream,
                microduck_rl=parent / "rl", graph=parent/"graph",policy=parent/"policy",
                sim_executable=parent/"sim", output=output, audit=parent / "wrong-audit.jsonl",
                sim_state=parent / "state", body_port=7893, reviewed_head="a" * 40)
            with (mock.patch("scripts.p8_02_r1_batch.socket.gethostname", return_value="jetsonthor01"),
                  mock.patch("scripts.p8_02_r1_batch.platform.python_version_tuple", return_value=("3","12","0")),
                  mock.patch("scripts.p8_02_r1_batch.FROZEN_PREFLIGHT_AUDIT",
                             parent / "external-audit.jsonl"),
                  mock.patch("scripts.p8_02_r1_batch.git_head", return_value="a" * 40),
                  mock.patch("scripts.p8_02_r1_batch.subprocess.check_output", return_value="")):
                with self.assertRaisesRegex(RuntimeError, "operator microduck path mismatch"):
                    preflight(args)
            self.assertFalse(output.exists())
            audit = json.loads((parent / "external-audit.jsonl").read_text().splitlines()[0])
            self.assertEqual(audit["assigned_ids"], 0)
            self.assertEqual(audit["result"], "FAIL")
            self.assertIn("microduck path mismatch", audit["failure"])
            self.assertFalse((parent / "wrong-audit.jsonl").exists())

    def test_checkpoint_manifest_and_recovery_never_modify_raw(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / "D00/attempt-01"
            folder.mkdir(parents=True)
            raw = folder / "trace.jsonl"
            raw.write_bytes(b'{"a":1}\n{"b":2}\n')
            journal = {"stage":"D","source_head":"a"*40,"ids":[
                {"trial_id":"D00","seed":886020,"attempts":[
                    {"name":"attempt-01","status":"TRIAL_CHILD_STARTED","armed":False}]}]}
            checkpoint(root,journal)
            before = inventory(root)
            report = recover_only(root)
            self.assertEqual(report["mode"], "AUDIT_ONLY_NO_RETRY")
            self.assertEqual(report["in_flight_unknown_arm"], ["D00/attempt-01"])
            self.assertEqual(before, inventory(root))
            self.assertEqual(report["journal_projection"]["ids"][0]["attempts"][0]["status"],
                             "INTERRUPTED_UNKNOWN_ARM")
            self.assertEqual(raw.read_bytes(), b'{"a":1}\n{"b":2}\n')

    def test_wrong_reviewed_head_aborts_before_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent=Path(temporary)
            for name in ("source/config", "microduck", "rl"):
                (parent/name).mkdir(parents=True)
            source=parent/"source"
            protocol=source/"config/p8_02_r1_protocol_v1.json"
            protocol.write_text(json.dumps(R1))
            execution=source/"config/p8_02_r1_d_execution_v1.json"
            execution.write_text("{}")
            output=parent/"output"
            args=Namespace(stage="D",root=source,protocol=protocol,execution=execution,
                microduck=parent/"microduck",microduck_rl=parent/"rl",output=output,
                graph=parent/"graph",policy=parent/"policy",sim_executable=parent/"sim",
                audit=output/"audit.jsonl",sim_state=parent/"state",body_port=7893,
                reviewed_head="b"*40)
            with (mock.patch("scripts.p8_02_r1_batch.socket.gethostname",return_value="jetsonthor01"),
                  mock.patch("scripts.p8_02_r1_batch.platform.python_version_tuple",return_value=("3","12","0")),
                  mock.patch("scripts.p8_02_r1_batch.FROZEN_PREFLIGHT_AUDIT",parent/"audit.jsonl"),
                  mock.patch("scripts.p8_02_r1_batch.git_head",return_value="a"*40)):
                with self.assertRaisesRegex(RuntimeError,"reviewed head"):
                    preflight(args)
            self.assertFalse(output.exists())
            audit=json.loads((parent/"audit.jsonl").read_text().splitlines()[0])
            self.assertEqual(audit["assigned_ids"],0)

    def test_sigint_checkpoints_stop_then_down_and_probe_without_next_id(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent=Path(temporary)
            root=parent/"source"
            root.mkdir()
            output=parent/"output"
            audit=parent/"audit.jsonl"
            audit.write_text("preflight\n")
            args=Namespace(stage="D",root=root,execution=root/"config/p8_02_r1_d_execution_v1.json",
                output=output,audit=audit,reviewed_head="a"*40,sim_state=parent/"state",
                body_port=7893,microduck=parent/"microduck",microduck_rl=parent/"rl",
                recover_only=False)
            execution={"walking_policy_path":"/policy","walking_policy_sha256":"a"*64,
                       "selected_v2":"looming_v2_log_area"}
            record={"hashes":{"protocol":"b"*64,"execution":"c"*64},
                    "commits":{"source":"a"*40},"resolved":{"source":str(root)}}
            calls=[]
            def fake_child(command,log,env):
                calls.append(("child",command[-1]))
                log.write_text("interrupted\n")
                return 130, True
            def fake_down(command,log,env):
                calls.append(("down",command[-1]))
                log.write_text("down\n")
                return 0,False
            def fake_probe(*_a,**_kw):
                calls.append(("probe",None))
                return {"result":"PASS"}
            with (mock.patch("scripts.p8_02_r1_batch.preflight",return_value=(R1,execution,record)),
                  mock.patch("scripts.p8_02_r1_batch.run_child",side_effect=lambda cmd,log,env,**kw:
                    fake_child(cmd,log,env) if log.name!="final-down.log" else fake_down(cmd,log,env)),
                  mock.patch("scripts.p8_02_r1_batch.emergency_stop",side_effect=lambda _:
                    calls.append(("stop",None)) or {"result":"PASS"}),
                  mock.patch("scripts.p8_02_r1_batch.probe_final_sim_state",side_effect=fake_probe)):
                report=run(args)
            self.assertEqual(report["result"],"FAIL")
            journal=json.loads((output/"batch-journal.json").read_text())
            self.assertEqual(journal["ids"][0]["status"],"INTERRUPTED_UNKNOWN_ARM")
            self.assertEqual(journal["ids"][1]["status"],"PENDING")
            self.assertEqual(journal["interrupt_stop"]["result"],"PASS")
            self.assertEqual(journal["final_sim_down"]["state_probe_result"],"PASS")
            self.assertEqual([x[0] for x in calls],["child","stop","down","probe"])

    def test_b_gate_rejects_missing_or_failed_d(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            with self.assertRaises(FileNotFoundError):
                require_development_gate(root,R1,"a"*40,"b"*64)
            (root/"batch-journal.json").write_text(json.dumps({"stage":"D","result":"FAIL",
                "source_head":"a"*40,"execution_sha256":"b"*64}))
            (root/"batch-summary.json").write_text(json.dumps({"stage":"D","result":"FAIL"}))
            with self.assertRaisesRegex(RuntimeError,"D 3/3 gate"):
                require_development_gate(root,R1,"a"*40,"b"*64)

    def test_raw_scorer_cannot_accept_summary_or_id_without_armed_raw(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rows = planned_rows(R1,"D")
            journal = {"stage":"D","ids":[{"trial_id":r["trial_id"],"seed":r["seed"],
                "attempts":[{"name":"attempt-01","armed":True,"status":"TRIAL_EXITED"}]}
                for r in rows]}
            for row in rows:
                folder = root / row["trial_id"] / "attempt-01"
                folder.mkdir(parents=True)
                (folder / "summary.json").write_text(json.dumps({"result":"PASS",
                    "trial_id":f"p8-02-r1-{row['trial_id']}","seed":row["seed"],
                    "arm_elapsed_s":row["arm_elapsed_s"],
                    "schema_version":"p8-02-r1-trial-v1"}))
            score = score_batch(root,R1,journal)
            self.assertEqual(score["result"],"FAIL")
            self.assertEqual(score["successes"],0)
            self.assertFalse(score["all_raw_accounted"])
            journal["ids"][0]["seed"] = 99
            with self.assertRaisesRegex(ValueError,"ID/seed"):
                score_batch(root,R1,journal)

    def test_child_arm_marker_and_progress_are_durable_single_id(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary)
            marker=folder/"armed.json"
            progress=folder/"progress.jsonl"
            append_progress(progress,"MOTION_CONFIRMED",123)
            write_arm_marker(marker,"p8-02-r1-D00",886020,456)
            append_progress(progress,"NEURAL_OBSERVATION_ARMED",456)
            self.assertEqual(json.loads(marker.read_text())["seed"],886020)
            self.assertEqual([json.loads(x)["state"] for x in progress.read_text().splitlines()],
                             ["MOTION_CONFIRMED","NEURAL_OBSERVATION_ARMED"])
            with self.assertRaisesRegex(RuntimeError,"already exists"):
                write_arm_marker(marker,"p8-02-r1-D00",886020,457)


if __name__ == "__main__":
    unittest.main()
