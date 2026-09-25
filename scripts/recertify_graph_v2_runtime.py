#!/usr/bin/env python3
"""Recertify the frozen P3 runtime with the actual source-derived graph v2."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from microduck_connectome.determinism import verify_fixed_replay
from microduck_connectome.graph import ConnectomeGraph
from microduck_connectome.neural_model import load_model_config, model_config_sha256
from microduck_connectome.performance import percentile_nearest_rank, read_linux_process_memory
from microduck_connectome.sparse_runtime import SparseNeuralRuntime


def file_sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def stimulus(step, sensory, *, mode):
    if mode == "zero" or step % 10:
        return {}
    return {
        sensory["populations"]["lc10a_left"]["body_ids"][0]: 1.0,
        sensory["populations"]["lplc2_left"]["body_ids"][0]: 0.75,
    }


def soak(graph, config, sensory, *, mode, steps):
    runtime = SparseNeuralRuntime(graph, config)
    maximum = 0.0
    spikes = 0
    started = time.perf_counter()
    for step in range(steps):
        snapshot = runtime.step(stimulus(step, sensory, mode=mode))
        if not snapshot["healthy"]:
            raise AssertionError("runtime unhealthy")
        if any(not math.isfinite(value) for value in snapshot["state"]):
            raise AssertionError("nonfinite state")
        maximum = max(maximum, max(map(abs, snapshot["state"])))
        spikes += sum(snapshot["spikes"])
    return {
        "mode": mode,
        "steps": steps,
        "timestep_ms": config["timestep_ms"],
        "simulated_seconds": steps * config["timestep_ms"] / 1000,
        "wall_seconds": time.perf_counter() - started,
        "healthy": runtime.healthy,
        "nonfinite_detected": False,
        "max_abs_state": maximum,
        "total_spikes": spikes,
        "final_step_count": runtime.step_count,
    }


def profile(graph, config, sensory, *, warmup_steps, measured_steps):
    runtime = SparseNeuralRuntime(graph, config)
    constructed = read_linux_process_memory()
    for step in range(warmup_steps):
        runtime.step(stimulus(step, sensory, mode="bounded"))
    latencies_ns = []
    for step in range(measured_steps):
        started = time.perf_counter_ns()
        runtime.step(stimulus(step, sensory, mode="bounded"))
        latencies_ns.append(time.perf_counter_ns() - started)
    memory = read_linux_process_memory()
    p95 = percentile_nearest_rank(latencies_ns, 0.95) / 1_000_000
    return {
        "warmup_steps": warmup_steps,
        "measured_steps": measured_steps,
        "p50_ms": percentile_nearest_rank(latencies_ns, 0.50) / 1_000_000,
        "p95_ms": p95,
        "p99_ms": percentile_nearest_rank(latencies_ns, 0.99) / 1_000_000,
        "min_ms": min(latencies_ns) / 1_000_000,
        "max_ms": max(latencies_ns) / 1_000_000,
        "preferred_p95_target_ms": 18.0,
        "preferred_p95_target_met": p95 <= 18.0,
        "constructed_rss_bytes": constructed["rss_bytes"],
        "post_profile_rss_bytes": memory["rss_bytes"],
        "peak_rss_bytes": memory["peak_rss_bytes"],
        "memory_measurement_method": memory["measurement_method"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--soak-steps", type=int, default=30_000)
    parser.add_argument("--warmup-steps", type=int, default=100)
    parser.add_argument("--measured-steps", type=int, default=500)
    args = parser.parse_args()
    if min(args.soak_steps, args.warmup_steps, args.measured_steps) <= 0:
        parser.error("all step counts must be positive")
    manifest = json.loads((ROOT / "data/manifests/controller-graph-v2.json").read_text())
    artifact = args.artifact or Path(manifest["thor_artifact"])
    if file_sha256(artifact) != manifest["graph_sha256"]:
        raise ValueError("graph-v2 artifact hash mismatch")
    config = load_model_config(ROOT / "config/neural_model_v1.json")
    sensory = json.loads((ROOT / "config/sensory_mapping_v1.json").read_text())
    baseline = read_linux_process_memory()
    graph = ConnectomeGraph.from_cache(artifact.parent, manifest["graph_sha256"])
    constructed = read_linux_process_memory()
    trace = [stimulus(step, sensory, mode="bounded") for step in range(200)]
    replay = verify_fixed_replay(graph, config, trace)
    performance = profile(graph, config, sensory, warmup_steps=args.warmup_steps,
                          measured_steps=args.measured_steps)
    zero = soak(graph, config, sensory, mode="zero", steps=args.soak_steps)
    bounded = soak(graph, config, sensory, mode="bounded", steps=args.soak_steps)
    final_memory = read_linux_process_memory()
    report = {
        "schema_version": "g8-r2-runtime-recert-v1",
        "dataset": manifest["dataset"],
        "graph_sha256": manifest["graph_sha256"],
        "graph_node_count": graph.root_manifest["node_count"],
        "graph_edge_count": graph.root_manifest["edge_count"],
        "model_config_sha256": model_config_sha256(config),
        "sensory_config_sha256": file_sha256(ROOT / "config/sensory_mapping_v1.json"),
        "source_commit_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "runtime_backend": "python-cpu-float32-contract",
        "random_seed": "none",
        "stimulus_schedule": "every tenth step inject 1.0 LC10a-left first ID and 0.75 LPLC2-left first ID; zero mode injects none",
        "deterministic_replay": replay,
        "performance": performance,
        "memory": {
            "baseline_rss_bytes": baseline["rss_bytes"],
            "graph_constructed_rss_bytes": constructed["rss_bytes"],
            "post_soak_rss_bytes": final_memory["rss_bytes"],
            "peak_rss_bytes": final_memory["peak_rss_bytes"],
            "graph_rss_delta_bytes": constructed["rss_bytes"] - baseline["rss_bytes"],
            "measurement_method": final_memory["measurement_method"],
        },
        "soaks": [zero, bounded],
        "all_healthy": zero["healthy"] and bounded["healthy"],
        "nonfinite_detected": zero["nonfinite_detected"] or bounded["nonfinite_detected"],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n")
    print(json.dumps({"graph_sha256": report["graph_sha256"],
                      "p95_ms": performance["p95_ms"],
                      "preferred_p95_target_met": performance["preferred_p95_target_met"],
                      "all_healthy": report["all_healthy"],
                      "soak_steps": args.soak_steps}, sort_keys=True))


if __name__ == "__main__":
    main()
