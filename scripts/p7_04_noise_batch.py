"""Official P7-04 paired clean/moderate target batch."""
from __future__ import annotations
import argparse, hashlib, json, math, os, platform, random, socket, statistics, subprocess, sys, time
from collections import Counter
from dataclasses import fields
from pathlib import Path
from microduck_connectome.target_scenario import TargetTrial, evaluator_truth, load_target_scenario_config, wrap_angle
from scripts.p7_pretrial_acquisition import acquire, run_logged, sha256_file
from scripts.p7_target_batch import percentile, wilson_interval
from scripts.p7_target_batch_v4 import collect_started_trial, ensure_sim_down, started_trial_failed
from scripts.p7_04_preregister import BOOTSTRAP_SEED, BOOTSTRAP_REPLICATES, SOURCE_SHA256, HISTORICAL_SHA256, SCENARIO_SHA256, NOISE_SEMANTICS, generate
MANIFEST="config/steering_noise_p7_04_v1.json"; HARNESS="scripts/p7_04_noise_batch.py"; VALID={"correct","incorrect","no_response"}

def validate_specs(e):
    specs=e["target_trials"]; block=e["p7_04"]
    if e["schema_version"]!="steering-experiment-v4" or e["experiment_version"]!="p7-04-noise-paired-v1" or len(specs)!=120 or e["target_trial_count"]!=120 or len(block["pairs"])!=60 or block["pair_count"]!=60 or block["noise_semantics"]!=NOISE_SEMANTICS or block["performance_threshold"] is not None: raise ValueError("P7-04 design mismatch")
    by={s["trial_id"]:s for s in specs}; cells=Counter(); seeds=set()
    if len(by)!=120 or Counter(s["visual_noise_level"] for s in specs)!={"clean":60,"moderate":60} or len({p["pair_id"] for p in block["pairs"]})!=60: raise ValueError("P7-04 trial/pair count mismatch")
    for pair in block["pairs"]:
        if set(pair["condition_order"])!={"clean","moderate"} or pair["seed"] in seeds: raise ValueError("pair order/seed mismatch")
        seeds.add(pair["seed"]); cells[(pair["target_side"],pair["target_eccentricity"],pair["target_motion"])]+=1
        for noise in ("clean","moderate"):
            s=by[pair[f"{noise}_trial_id"]]
            if s["visual_noise_level"]!=noise or s["seed"]!=pair["seed"] or any(s[k]!=pair[k] for k in ("target_side","target_eccentricity","target_motion")): raise ValueError("pair mismatch")
    if len(cells)!=12 or set(cells.values())!={5}: raise ValueError("cell imbalance")
    return specs

def verify_measure(trace,summary_path,spec_path,config,manifest_sha,policy_sha,spec_sha,trace_sha,summary_sha):
    s=json.loads(summary_path.read_text()); a=s["artifact"]; data=trace.read_bytes(); digest=hashlib.sha256(data).hexdigest()
    if digest!=trace_sha or digest!=a["sha256"] or sha256_file(summary_path)!=summary_sha or sha256_file(spec_path)!=spec_sha or s["trial_spec_sha256"]!=spec_sha or s["experiment_sha256"]!=manifest_sha or s["walking_policy_sha256"]!=policy_sha or s["scenario_config_sha256"]!=SCENARIO_SHA256: raise ValueError("trace/spec/manifest/policy SHA mismatch")
    rows=[json.loads(x) for x in data.decode("ascii").splitlines()]
    if not rows or type(a["record_count"]) is not int or len(rows)!=a["record_count"] or rows[0]["timestamp_ns"]!=a["start_timestamp_ns"] or rows[-1]["timestamp_ns"]!=a["end_timestamp_ns"] or any(int(b["timestamp_ns"])<=int(x["timestamp_ns"]) for x,b in zip(rows,rows[1:])): raise ValueError("trace rows/timing mismatch")
    spec=json.loads(spec_path.read_text())
    if any(s["trial"][k]!=v for k,v in spec.items()) or s["outcome"] not in VALID or s["safety_limit_violations"]!=0: raise ValueError("trial metadata/outcome mismatch")
    trial=TargetTrial(**{f.name:s["trial"][f.name] for f in fields(TargetTrial)})
    truth=evaluator_truth(config,trial,elapsed_s=trial.trial_timeout_s)
    error=abs(wrap_angle(truth["target_world_bearing_rad"]-s["final_body"]["heading_rad"]))
    if not math.isfinite(error): raise ValueError("nonfinite heading error")
    response=s["response"]
    return {"verified_artifact_sha256":digest,"verified_record_count":len(rows),"terminal_abs_target_bearing_error_rad":error,"response_latency_s":None if response is None else response["latency_s"],"first_response_heading_magnitude_rad":None if response is None else abs(response["heading_delta_rad"])}

def bootstrap(deltas):
    if not deltas:return None
    rng=random.Random(BOOTSTRAP_SEED); n=len(deltas)
    samples=sorted(sum(deltas[rng.randrange(n)] for _ in range(n))/n for _ in range(BOOTSTRAP_REPLICATES))
    return [percentile(samples,.025),percentile(samples,.975)]

def summarize(rows,e,head,manifest_sha,fixture_sha,journal_sha,started):
    specs=validate_specs(e); counts=Counter(r["outcome"] for r in rows)
    valid=[r for r in rows if r.get("trial_started") and r.get("trial_exit")==0 and r.get("outcome") in VALID and r.get("safety_limit_violations")==0 and "verified_artifact_sha256" in r]
    by={r["trial_id"]:r for r in valid}
    pairs=[(p,by[p["clean_trial_id"]],by[p["moderate_trial_id"]]) for p in e["p7_04"]["pairs"] if p["clean_trial_id"] in by and p["moderate_trial_id"] in by]
    condition={}
    for noise in ("clean","moderate"):
        group=[r for r in valid if r["spec"]["visual_noise_level"]==noise]; n=len(group); correct=sum(r["outcome"]=="correct" for r in group)
        latency=[r["response_latency_s"] for r in group if r["response_latency_s"] is not None]; errors=[r["terminal_abs_target_bearing_error_rad"] for r in group]; heading=[r["first_response_heading_magnitude_rad"] for r in group if r["first_response_heading_magnitude_rad"] is not None]
        condition[noise]={"valid":n,"correct":correct,"incorrect":sum(r["outcome"]=="incorrect" for r in group),"no_response":sum(r["outcome"]=="no_response" for r in group),"correct_rate":correct/n if n else None,"correct_95pct_wilson_ci":wilson_interval(correct,n),"response_count":len(latency),"response_latency_median_s":statistics.median(latency) if latency else None,"response_latency_p95_s":percentile(latency,.95),"terminal_abs_bearing_error_median_rad":statistics.median(errors) if errors else None,"terminal_abs_bearing_error_p95_rad":percentile(errors,.95),"first_response_heading_magnitude_median_rad":statistics.median(heading) if heading else None}
    deltas=[int(m["outcome"]=="correct")-int(c["outcome"]=="correct") for _,c,m in pairs]
    discord={"both_correct":sum(c["outcome"]=="correct" and m["outcome"]=="correct" for _,c,m in pairs),"clean_only":sum(c["outcome"]=="correct" and m["outcome"]!="correct" for _,c,m in pairs),"moderate_only":sum(c["outcome"]!="correct" and m["outcome"]=="correct" for _,c,m in pairs),"neither_correct":sum(c["outcome"]!="correct" and m["outcome"]!="correct" for _,c,m in pairs)}
    cells={}
    for side in ("left","right"):
      for ecc in ("near_center","medium","far"):
       for motion in ("static","slow_crossing"):
        match=[(c,m) for p,c,m in pairs if (p["target_side"],p["target_eccentricity"],p["target_motion"])==(side,ecc,motion)]
        cells[f"{side}/{ecc}/{motion}"]={"complete_pairs":len(match),"clean_correct":sum(c["outcome"]=="correct" for c,m in match),"moderate_correct":sum(m["outcome"]=="correct" for c,m in match)}
    safety=sum(r.get("safety_limit_violations",0) for r in rows); failures=[r["trial_id"] for r in rows if started_trial_failed(r)]
    complete=len(rows)==120 and len(valid)==120 and len(pairs)==60 and [r["trial_id"] for r in rows]==[s["trial_id"] for s in specs] and safety==0 and not failures
    return {"schema_version":"p7-04-noise-batch-v1","execution_target":"Thor","hostname":socket.gethostname(),"started_utc":started,"ended_utc":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),"source_head":head,"experiment_sha256":manifest_sha,"fixture_sha256":fixture_sha,"walking_policy_sha256":e["walking_policy"]["sha256"],"expected_target_trials":120,"attempted_trials":len(rows),"evaluated_valid_target_trials":len(valid),"complete_pairs":len(pairs),"counts":dict(counts),"condition":condition,"paired_moderate_minus_clean_correct_rate":statistics.mean(deltas) if deltas else None,"paired_95pct_bootstrap_ci":bootstrap(deltas),"paired_discordance":discord,"cell_breakdown":cells,"safety_limit_violations":safety,"started_trial_failures":failures,"invalid_trial_ids":[r["trial_id"] for r in rows if r["outcome"]=="invalid"],"max_heading_sample_delay_ms":max((r.get("max_heading_sample_delay_ms",0) for r in rows),default=0),"raw_journal_sha256":journal_sha,"result":"COMPLETE" if complete else ("FAIL_SAFETY" if safety else "INCOMPLETE")}

def preflight(root,experiment_path):
    if experiment_path!=(root/MANIFEST).resolve() or Path(__file__).resolve()!=(root/HARNESS).resolve():raise RuntimeError("tracked P7-04 path required")
    head=subprocess.check_output(["git","-C",str(root),"rev-parse","HEAD"],text=True).strip()
    if subprocess.check_output(["git","-C",str(root),"status","--porcelain"],text=True).strip():raise RuntimeError("clean checkout required")
    for relative in (MANIFEST,HARNESS):
        if (root/relative).read_bytes()!=subprocess.check_output(["git","-C",str(root),"show",f"HEAD:{relative}"]):raise RuntimeError("committed bytes mismatch")
    source=root/"config/steering_no_target_p7_03_v1.json"; historical=root/"config/steering_experiment_v4.json"; scenario=root/"config/target_scenario_v1.json"
    if (sha256_file(source),sha256_file(historical),sha256_file(scenario))!=(SOURCE_SHA256,HISTORICAL_SHA256,SCENARIO_SHA256):raise RuntimeError("source/scenario SHA mismatch")
    e=json.loads(experiment_path.read_text())
    if e!=generate(json.loads(source.read_text()),json.loads(historical.read_text()),source_sha256=SOURCE_SHA256,historical_sha256=HISTORICAL_SHA256,scenario_sha256=SCENARIO_SHA256):raise RuntimeError("frozen manifest mismatch")
    validate_specs(e)
    return head,e,load_target_scenario_config(scenario)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("root","experiment","output","graph-cache","sim-script","state-dir","microduck","microduck-rl"):parser.add_argument(f"--{name}",type=Path,required=True)
    parser.add_argument("--body-port",type=int,required=True); a=parser.parse_args()
    if not socket.gethostname().startswith("jetsonthor") or platform.python_version_tuple()[:2]!=("3","12"):raise RuntimeError("Thor Python 3.12 required")
    root=a.root.resolve(); experiment_path=a.experiment.resolve(); head,e,config=preflight(root,experiment_path); specs=validate_specs(e)
    policy_path=Path(e["walking_policy"]["artifact_path"])
    if not policy_path.is_absolute() or sha256_file(policy_path)!=e["walking_policy"]["sha256"]:
        raise RuntimeError("walking policy SHA mismatch before official simulator startup")
    for checkout, expected in ((a.microduck,e["microduck_commit"]),
                               (a.microduck_rl,e["microduck_rl_commit"])):
        actual=subprocess.check_output(["git","-C",str(checkout),"rev-parse","HEAD"],text=True).strip()
        if actual!=expected: raise RuntimeError("upstream runtime commit mismatch before official simulator startup")
    a.output.mkdir(parents=True,exist_ok=False); journal=a.output/"trial-results.jsonl"
    env=dict(os.environ);env.update({"PATH":f"{a.microduck.parent/'cargo/bin'}:{env['PATH']}","RUSTUP_HOME":str(a.microduck.parent/"rustup"),"CARGO_HOME":str(a.microduck.parent/"cargo"),"DUCK_SIM_STATE":str(a.state_dir),"DUCK_SIM_RL":str(a.microduck_rl),"DUCK_SIM_PORT":str(a.body_port),"DUCK_SIM_VIEWER":"0","PYTHONPATH":str(root)})
    rows=[]; started=time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()); final_down={}
    with ensure_sim_down(a.sim_script,a.output,env,final_down),journal.open("w",encoding="utf-8") as out:
      for index,spec in enumerate(specs,1):
        folder=a.output/spec["trial_id"];folder.mkdir();spec_path=folder/"trial-spec.json";spec_path.write_text(json.dumps(spec,sort_keys=True,indent=2)+"\n");row={"index":index,"trial_id":spec["trial_id"],"seed":spec["seed"],"spec":spec,"spec_sha256":sha256_file(spec_path),"trial_started":False}; acq=None
        try:
            acq=acquire(root=root,experiment_path=experiment_path,experiment=e,trial_dir=folder,sim_script=a.sim_script,body_port=a.body_port,env=env)
            row["pretrial_acquisition_sha256"]=sha256_file(folder/"pretrial-acquisition.json");row["pretrial_attempts_used"]=acq["attempts_used"];row["trial_started"]=acq["accepted"]
        except BaseException as ex:row.update(outcome="invalid",invalid_reasons=["pretrial_acquisition_exception"],harness_exception=f"{type(ex).__name__}: {ex}")
        if acq is not None and acq["accepted"]:
            cmd=[sys.executable,str(root/"scripts/p7_target_steering_trial.py"),"--root",str(root),"--graph-cache",str(a.graph_cache),"--graph-key",e["graph_key"],"--socket",str(a.state_dir/"duck-a.sock"),"--body-port",str(a.body_port),"--microduck",str(a.microduck),"--microduck-rl",str(a.microduck_rl),"--source-head",head,"--trial-spec",str(spec_path),"--experiment",str(experiment_path),"--run-id",f"p7-04-target-{index:03d}","--artifact",str(folder/"trace.jsonl"),"--summary",str(folder/"summary.json")]
            cmd_path=folder/"trial-command.json";cmd_path.write_text(json.dumps({"argv":cmd,"cwd":str(root),"duck_sim_state":str(a.state_dir),"duck_sim_port":a.body_port},sort_keys=True,indent=2)+"\n");row["trial_command_sha256"]=sha256_file(cmd_path)
            row.update(collect_started_trial(cmd,folder,env=env,root=root))
            if not started_trial_failed(row) and row.get("outcome") in VALID:
                try:row.update(verify_measure(folder/"trace.jsonl",folder/"summary.json",spec_path,config,sha256_file(experiment_path),e["walking_policy"]["sha256"],row["spec_sha256"],row["trace_sha256"],row["summary_sha256"]))
                except BaseException as ex:row.update(outcome="invalid",invalid_reasons=["trace_or_metric_verification_exception"],harness_exception=f"{type(ex).__name__}: {ex}")
        elif acq is not None:row.update(outcome="invalid",invalid_reasons=["pretrial_pose_acquisition_exhausted"])
        abort=acq is None or started_trial_failed(row) or (row.get("trial_started") and row.get("outcome") not in VALID) or bool(row.get("safety_limit_violations",0))
        if abort:
            log=folder/"emergency-sim-down.log"
            try:row["emergency_sim_down_exit"]=run_logged([str(a.sim_script),"down"],log,env=env)
            except BaseException as ex:row["emergency_sim_down_error"]=f"{type(ex).__name__}: {ex}"
            if log.exists():row["emergency_sim_down_sha256"]=sha256_file(log)
        out.write(json.dumps(row,sort_keys=True,allow_nan=False)+"\n");out.flush();rows.append(row);print(f"{index}/120 {spec['trial_id']} {row['outcome']}",flush=True)
        if abort:break
    batch=summarize(rows,e,head,sha256_file(experiment_path),sha256_file(Path(__file__)),sha256_file(journal),started)
    batch["final_sim_down_exit"]=final_down.get("exit");batch["final_sim_down_sha256"]=final_down.get("sha256");batch["final_sim_down_error"]=final_down.get("error")
    if final_down.get("exit")!=0:batch["result"]="FAIL_SAFETY"
    batch["raw_journal_bytes"]=journal.stat().st_size
    (a.output/"batch-summary.json").write_text(json.dumps(batch,sort_keys=True,indent=2,allow_nan=False)+"\n")
    print(json.dumps({"result":batch["result"],"attempted_trials":len(rows),"complete_pairs":batch["complete_pairs"],"condition":batch["condition"]},sort_keys=True),flush=True)
    if batch["result"]!="COMPLETE":raise SystemExit(1)
if __name__=="__main__":main()
