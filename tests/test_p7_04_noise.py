"""Source-only preregistration, scoring, and trial identity tests for P7-04."""
from __future__ import annotations
from copy import deepcopy
import hashlib
import os
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from microduck_connectome.target_scenario import load_target_scenario_config, make_target_trial
from scripts.p7_04_preregister import ROOT, SOURCE, HISTORICAL, OUTPUT, SOURCE_SHA256, HISTORICAL_SHA256, SCENARIO_SHA256, generate
from scripts.p7_04_noise_batch import validate_specs, verify_measure, summarize

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()

class PreregTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.e=json.loads(OUTPUT.read_text())
    def test_deterministic_and_disjoint(self):
        self.assertEqual((sha(SOURCE),sha(HISTORICAL),sha(ROOT/"config/target_scenario_v1.json")),(SOURCE_SHA256,HISTORICAL_SHA256,SCENARIO_SHA256))
        self.assertEqual(self.e,generate(json.loads(SOURCE.read_text()),json.loads(HISTORICAL.read_text()),source_sha256=SOURCE_SHA256,historical_sha256=HISTORICAL_SHA256,scenario_sha256=SCENARIO_SHA256))
        self.assertEqual(len(validate_specs(self.e)),120)
        prior=json.loads(SOURCE.read_text()); old=json.loads(HISTORICAL.read_text())
        past={x["seed"] for m in (prior,old) for field in ("target_trials","no_target_trials") for x in m[field]}
        self.assertFalse(past & {p["seed"] for p in self.e["p7_04"]["pairs"]})
        self.assertEqual(len({p["seed"] for p in self.e["p7_04"]["pairs"]}),60)
        for key in ("walking_policy","config_sha256","target_response","validity","graph_key","microduck_commit","microduck_rl_commit"):
            self.assertEqual(self.e[key],prior[key])
    def test_manifest_pair_mismatch_rejected(self):
        modified=deepcopy(self.e);modified["target_trials"][0]["seed"]+=1
        with self.assertRaisesRegex(ValueError,"pair mismatch"):validate_specs(modified)
    def test_source_trial_accepts_new_manifest_and_verifies_hashes(self):
        spec=self.e["target_trials"][0]
        with tempfile.TemporaryDirectory() as temp:
            t=Path(temp); spec_path=t/"spec.json";spec_path.write_text(json.dumps(spec))
            args=[sys.executable,str(ROOT/"scripts/p7_target_steering_trial.py"),"--root",str(ROOT),"--graph-cache",str(t/"missing.graph"),"--graph-key",self.e["graph_key"],"--socket",str(t/"missing.sock"),"--body-port","48999","--microduck",str(t/"microduck"),"--microduck-rl",str(t/"microduck_rl"),"--source-head","test","--trial-spec",str(spec_path),"--experiment",str(OUTPUT),"--run-id","source-check","--artifact",str(t/"trace.jsonl"),"--summary",str(t/"summary.json")]
            good=subprocess.run(args,cwd=ROOT,text=True,capture_output=True,env={**os.environ,'PYTHONPATH':str(ROOT)})
            self.assertNotIn("preregistered",good.stderr)
            self.assertIn("missing.graph",good.stderr)
            altered=deepcopy(self.e);altered["walking_policy"]["sha256"]="0"*64
            path=t/"altered.json";path.write_text(json.dumps(altered))
            args[args.index(str(OUTPUT))]=str(path)
            bad=subprocess.run(args,cwd=ROOT,text=True,capture_output=True,env={**os.environ,'PYTHONPATH':str(ROOT)})
            self.assertIn("preregistered walking policy hash mismatch",bad.stderr)
            altered=deepcopy(self.e);altered["config_sha256"]["scenario"]="0"*64;path.write_text(json.dumps(altered))
            bad=subprocess.run(args,cwd=ROOT,text=True,capture_output=True,env={**os.environ,'PYTHONPATH':str(ROOT)})
            self.assertIn("preregistered scenario hash mismatch",bad.stderr)

class BatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.e=json.loads(OUTPUT.read_text())
    def rows(self):
        return [{"trial_id":s["trial_id"],"spec":s,"outcome":"correct","trial_started":True,"trial_exit":0,"summary_sha256":"a","trace_sha256":"b","verified_artifact_sha256":"b","safety_limit_violations":0,"response_latency_s":.3,"terminal_abs_target_bearing_error_rad":.1,"first_response_heading_magnitude_rad":.03} for s in self.e["target_trials"]]
    def summary(self,rows):return summarize(rows,self.e,"head","manifest","harness","journal","utc")
    def test_complete_and_paired_uncertainty(self):
        rows=self.rows(); rows[0]["outcome"]="incorrect"
        result=self.summary(rows)
        self.assertEqual(result["result"],"COMPLETE")
        self.assertEqual(result["complete_pairs"],60)
        self.assertEqual(result["condition"]["clean"]["valid"],60)
        self.assertIsNotNone(result["paired_95pct_bootstrap_ci"])
        self.assertEqual(len(result["cell_breakdown"]),12)
        self.assertEqual(self.summary(rows[:-1])["result"],"INCOMPLETE")
        rows[0]["safety_limit_violations"]=1
        self.assertEqual(self.summary(rows)["result"],"FAIL_SAFETY")
    def test_trace_bytes_and_rows_checked_before_score(self):
        config=load_target_scenario_config(ROOT/"config/target_scenario_v1.json"); spec=self.e["target_trials"][0]
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp); trace=p/"trace.jsonl"; summary=p/"summary.json"; sp=p/"spec.json"
            sp.write_text(json.dumps(spec))
            trial=make_target_trial(config,**spec,initial_robot_heading_rad=0).metadata()
            trace.write_text('{"timestamp_ns":1}\n{"timestamp_ns":2}\n')
            obj={"artifact":{"sha256":sha(trace),"record_count":2,"start_timestamp_ns":1,"end_timestamp_ns":2},"trial_spec_sha256":sha(sp),"experiment_sha256":"manifest","walking_policy_sha256":"policy","scenario_config_sha256":SCENARIO_SHA256,"trial":trial,"outcome":"correct","safety_limit_violations":0,"final_body":{"heading_rad":0},"response":{"latency_s":.3,"heading_delta_rad":.03}}
            summary.write_text(json.dumps(obj))
            kwargs=dict(trace=trace,summary_path=summary,spec_path=sp,config=config,manifest_sha="manifest",policy_sha="policy",spec_sha=sha(sp),trace_sha=sha(trace),summary_sha=sha(summary))
            self.assertGreaterEqual(verify_measure(**kwargs)["terminal_abs_target_bearing_error_rad"],0)
            trace.write_text(trace.read_text()+'{"timestamp_ns":3}\n')
            with self.assertRaisesRegex(ValueError,"SHA mismatch"):verify_measure(**kwargs)
            obj["artifact"]["sha256"]=sha(trace);summary.write_text(json.dumps(obj));kwargs["trace_sha"]=sha(trace);kwargs["summary_sha"]=sha(summary)
            with self.assertRaisesRegex(ValueError,"rows/timing mismatch"):verify_measure(**kwargs)
if __name__=="__main__":unittest.main()
