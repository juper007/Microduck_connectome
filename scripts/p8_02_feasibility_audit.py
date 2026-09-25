"""Read-only P8-02 frozen-chain feasibility audit; never sends a robot command."""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from microduck_connectome.graph import ConnectomeGraph
from microduck_connectome.looming_scenario import (
    evaluator_truth, load_config, make_trial, render_pixels,
)
from scripts.p6_telemetry_runtime_fixture import FullChain, git_head


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(root, cache, output):
    manifest_path = root / "config/steering_experiment_v4.json"
    manifest = json.loads(manifest_path.read_text())
    key = manifest["graph_key"]
    graph_file = cache / (key + ".json")
    graph = ConnectomeGraph.from_cache(cache, key)
    ids = set(graph.body_ids)
    sensory = json.loads((root / "config/sensory_mapping_v1.json").read_text())
    readout = json.loads((root / "config/dn_readout_v1.json").read_text())
    escape_ids = readout["populations"]["escape"]["body_ids"]
    lplc2_ids = sorted(
        body_id for name in ("lplc2_left", "lplc2_right")
        for body_id in sensory["populations"][name]["body_ids"]
    )
    config = load_config(root / "config/looming_scenario_v1.json")
    pose = {"x_m": 0.0, "y_m": 0.0, "heading_rad": 0.0, "trunk_z_m": 0.116}
    conditions = {}
    for motion, seed in (("approaching", 80101), ("static", 80102), ("receding", 80103)):
        chain = FullChain(root, graph)
        trial = make_trial(config, trial_id="audit-" + motion, seed=seed,
                           motion=motion, initial_pose=pose)
        maximum = {"looming": 0.0, "lplc2": 0.0, "escape": 0.0}
        counts = Counter()
        first_stop = None
        first_nonzero_looming = None
        for index in range(201):
            elapsed = index * 0.02
            now_ns = 1_000_000_000 + index * 20_000_000
            pixels = render_pixels(config, trial, pose=pose, elapsed_s=elapsed)
            frame = chain.pipeline.process(
                pixels, camera_timestamp_ns=now_ns, camera_frame_id=index + 1,
                tof_left_mm=config["tof_mm"], tof_center_mm=config["tof_mm"],
                tof_right_mm=config["tof_mm"], tof_timestamp_ns=now_ns,
                tof_frame_id=index + 1, now_ns=now_ns,
            )
            update = chain.neural(frame, now_ns)
            channels = update.trace["stimulus_channels"]
            looming = frame["looming"]
            lplc2 = max(channels["lplc2_left"], channels["lplc2_right"])
            escape = update.readout["escape"]
            maximum["looming"] = max(maximum["looming"], looming)
            maximum["lplc2"] = max(maximum["lplc2"], lplc2)
            maximum["escape"] = max(maximum["escape"], escape)
            counts["nonzero_looming_ticks"] += looming > 0
            counts["nonzero_lplc2_ticks"] += lplc2 > 0
            counts["total_graph_spikes"] += update.trace["male_cns"]["spike_count"]
            counts["stop_intent_ticks"] += update.behavior_intent["stop"]
            if looming > 0 and first_nonzero_looming is None:
                first_nonzero_looming = elapsed
            if update.behavior_intent["stop"] and first_stop is None:
                first_stop = elapsed
        truth = evaluator_truth(config, trial, pose=pose, elapsed_s=4.0)
        conditions[motion] = {
            "seed": seed, "ticks": 201, "tick_ms": 20,
            "max": maximum, "counts": dict(counts),
            "first_nonzero_looming_s": first_nonzero_looming,
            "first_neural_stop_intent_s": first_stop,
            "final_virtual_distance_to_boundary_m": truth["distance_to_boundary_m"],
        }
    policy = manifest["walking_policy"]
    artifact = Path(policy["artifact_path"])
    if sha(artifact) != policy["sha256"]:
        raise RuntimeError("merged P7 policy artifact hash mismatch")
    result = {
        "schema_version": "p8-02-feasibility-audit-v1",
        "status": "BLOCKED_PENDING_INDEPENDENT_REVIEW",
        "scope": "offline frozen P4-to-P5 chain, no robotd command or P8-02 final trial",
        "source_head": git_head(root),
        "graph_key": key,
        "graph_file": str(graph_file),
        "graph_file_sha256": sha(graph_file),
        "graph_node_count": len(ids),
        "graph_body_id_membership_sha256": hashlib.sha256(
            json.dumps(sorted(ids), separators=(",", ":")).encode()).hexdigest(),
        "configured_escape_dn_ids": escape_ids,
        "escape_dn_present_in_graph": {str(v): v in ids for v in escape_ids},
        "configured_lplc2_count": len(lplc2_ids),
        "lplc2_present_in_graph_count": sum(v in ids for v in lplc2_ids),
        "scenario_config_sha256": sha(root / "config/looming_scenario_v1.json"),
        "p7_manifest_sha256": sha(manifest_path),
        "sensory_config_sha256": sha(root / "config/sensory_mapping_v1.json"),
        "dn_readout_config_sha256": sha(root / "config/dn_readout_v1.json"),
        "escape_decoder_config_sha256": sha(root / "config/escape_decoder_v1.json"),
        "motion_adapter_config_sha256": sha(root / "config/motion_adapter_v1.json"),
        "stop_transport": json.loads((root / "config/motion_adapter_v1.json").read_text())["stop_transport"],
        "walking_policy_sha256": policy["sha256"],
        "conditions": conditions,
        "conclusion": "Both configured DNp01 IDs are absent from selected graph. The frozen FullChain projects absent readout IDs to False, so neural escape remains zero and no stimulus-triggered stop is possible without a separately reviewed graph/readout change.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({"status": result["status"], "graph_key": key,
                      "escape_dn_present_in_graph": result["escape_dn_present_in_graph"],
                      "conditions": conditions}, sort_keys=True))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--graph-cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.root.resolve(), args.graph_cache.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
