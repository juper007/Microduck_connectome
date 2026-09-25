#!/usr/bin/env python3
"""Verify frozen P4 sensory channels on the actual graph-v2 neural runtime."""

import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from microduck_connectome.graph import ConnectomeGraph
from microduck_connectome.neural_model import load_model_config, model_config_sha256
from microduck_connectome.perception_frame import make_perception_frame
from microduck_connectome.sensory_mapping import (
    SensoryMapper,
    load_sensory_mapping_config,
    sensory_mapping_config_sha256,
)
from microduck_connectome.sparse_runtime import SparseNeuralRuntime


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run(artifact):
    manifest = json.loads((ROOT / "data/manifests/controller-graph-v2.json").read_text())
    if sha256(artifact) != manifest["graph_sha256"]:
        raise ValueError("graph-v2 artifact SHA mismatch")
    graph = ConnectomeGraph.from_cache(artifact.parent, manifest["graph_sha256"])
    sensory = load_sensory_mapping_config(ROOT / "config/sensory_mapping_v1.json")
    model = load_model_config(ROOT / "config/neural_model_v1.json")
    mapper = SensoryMapper(graph.body_ids, sensory)
    all_ids = set(graph.body_ids)
    coverage = {}
    for name, spec in sensory["populations"].items():
        present = set(spec["body_ids"]) & all_ids
        if len(present) != len(spec["body_ids"]):
            raise AssertionError(f"missing graph-v2 sensory body IDs: {name}")
        coverage[name] = {"configured": len(spec["body_ids"]), "present": len(present)}

    timestamp_ns = 1_000_000_000
    fresh = make_perception_frame(
        timestamp_ns=timestamp_ns, frame_id=1,
        target_x=-0.5, target_area=0.4, looming=0.8, confidence=0.9,
    )
    channels = mapper.map_channels(fresh, now_ns=timestamp_ns)
    if abs(channels["lc10a_left"] - 0.27) > 1e-12 or abs(channels["lc10a_right"] - 0.09) > 1e-12:
        raise AssertionError("frozen LC10a lateral mapping changed")
    if channels["lplc2_left"] != 0.8 or channels["lplc2_right"] != 0.8:
        raise AssertionError("frozen bilateral looming mapping changed")
    external = mapper.build_external(fresh, now_ns=timestamp_ns)
    expected = set().union(*(set(spec["body_ids"]) for spec in sensory["populations"].values()))
    if set(external) != expected:
        raise AssertionError("mapped stimuli did not reach all configured graph nodes")
    lplc2_ids = set(sensory["populations"]["lplc2_left"]["body_ids"])
    lplc2_ids |= set(sensory["populations"]["lplc2_right"]["body_ids"])
    if any(external[body_id] != 0.8 for body_id in lplc2_ids):
        raise AssertionError("LPLC2 external amplitude mismatch")

    runtime = SparseNeuralRuntime(graph, model)
    first = runtime.step(external)
    index = {body_id: i for i, body_id in enumerate(first["body_ids"])}
    received = sum(first["state"][index[body_id]] > 0.79 for body_id in lplc2_ids)
    if received != len(lplc2_ids):
        raise AssertionError("LPLC2 runtime nodes did not receive looming stimulus")
    second = runtime.step(external)
    lplc2_spikes = sum(second["spikes"][index[body_id]] for body_id in lplc2_ids)

    stale_at_ns = timestamp_ns + 101_000_000
    stale_external = mapper.build_external(fresh, now_ns=stale_at_ns)
    invalid = make_perception_frame(
        timestamp_ns=timestamp_ns, frame_id=2,
        target_x=-0.5, target_area=0.4, looming=0.8, confidence=0.9,
        valid=False,
    )
    invalid_external = mapper.build_external(invalid, now_ns=timestamp_ns)
    if stale_external or invalid_external:
        raise AssertionError("stale/invalid perception replayed neural stimulus")
    recovery = make_perception_frame(
        timestamp_ns=2_000_000_000, frame_id=3,
        target_x=-0.5, target_area=0.4, looming=0.8, confidence=0.9,
    )
    if mapper.build_external(recovery, now_ns=2_000_000_000) != external:
        raise AssertionError("fresh input did not restore the expected sensory mapping")
    return {
        "schema_version": "g8-r3-sensory-recert-v1",
        "dataset": manifest["dataset"],
        "graph_sha256": manifest["graph_sha256"],
        "source_commit_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "python_version": platform.python_version(),
        "sensory_config_sha256": sensory_mapping_config_sha256(sensory),
        "neural_model_config_sha256": model_config_sha256(model),
        "population_coverage": coverage,
        "fresh_frame": fresh,
        "channels": channels,
        "external_count": len(external),
        "lplc2_external_count": len(lplc2_ids),
        "lplc2_amplitude": 0.8,
        "lplc2_runtime_received_count": received,
        "lplc2_second_step_spike_count": lplc2_spikes,
        "stale_external_count": len(stale_external),
        "invalid_external_count": len(invalid_external),
        "fresh_recovery_identical": True,
        "runtime_healthy": runtime.healthy,
        "scope": "sensory injection and graph runtime receipt only; not DN readout or robot behavior",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--artifact", type=Path)
    args = parser.parse_args()
    manifest = json.loads((ROOT / "data/manifests/controller-graph-v2.json").read_text())
    report = run(args.artifact or Path(manifest["thor_artifact"]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n")
    print(json.dumps({"graph_sha256": report["graph_sha256"],
                      "external_count": report["external_count"],
                      "lplc2_runtime_received_count": report["lplc2_runtime_received_count"],
                      "stale_external_count": report["stale_external_count"]}, sort_keys=True))


if __name__ == "__main__":
    main()
