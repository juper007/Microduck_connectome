#!/usr/bin/env python3
"""Exercise frozen LPLC2→graph-v2→DNp01→stop without neural shortcuts."""

import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from microduck_connectome.dn_aggregator import DNActivityAggregator, load_dn_readout_config
from microduck_connectome.escape_decoder import EscapeDecoder, load_escape_decoder_config
from microduck_connectome.graph import ConnectomeGraph
from microduck_connectome.neural_model import load_model_config
from microduck_connectome.perception_frame import make_perception_frame
from microduck_connectome.safety_clamp import SafetyClamp, load_safety_envelope
from microduck_connectome.sensory_mapping import SensoryMapper, load_sensory_mapping_config
from microduck_connectome.sparse_runtime import SparseNeuralRuntime
from microduck_connectome.watchdog import ControllerWatchdog


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run_case(graph, model, sensory, dn_config, escape_config, safety_envelope,
             protocol, case):
    runtime = SparseNeuralRuntime(graph, model)
    mapper = SensoryMapper(graph.body_ids, sensory)
    aggregator = DNActivityAggregator(graph.body_ids, dn_config)
    decoder = EscapeDecoder(escape_config)
    clamp = SafetyClamp(safety_envelope)
    watchdog = ControllerWatchdog(ROOT / "config/watchdog_v1.json")
    dn_ids = set(dn_config["populations"]["escape"]["body_ids"])
    lplc2_ids = set(sensory["populations"]["lplc2_left"]["body_ids"])
    lplc2_ids.update(sensory["populations"]["lplc2_right"]["body_ids"])
    body_index = {body_id: index for index, body_id in enumerate(graph.body_ids)}
    records = []
    total = protocol["warmup_steps"] + protocol["stimulus_steps"]
    for step in range(total):
        active = step >= protocol["warmup_steps"]
        looming = case["looming"] if active else 0.0
        target_area = protocol["target_area"] if active else 0.0
        confidence = protocol["confidence"] if active else 0.0
        timestamp_ns = (step + 1) * protocol["timestep_ms"] * 1_000_000
        sequence = step + 1
        frame = make_perception_frame(
            timestamp_ns=timestamp_ns, frame_id=sequence,
            target_x=protocol["target_x"], target_area=target_area,
            looming=looming, confidence=confidence,
        )
        external = mapper.build_external(frame, now_ns=timestamp_ns)
        snapshot = runtime.step(external)
        readout = aggregator.update(
            snapshot["spikes"], timestamp_ns=timestamp_ns, sequence=sequence,
            runtime_healthy=snapshot["healthy"],
        )
        intent = decoder.apply(readout)
        safe = clamp.apply(intent, now_ns=timestamp_ns, fallback_sequence=sequence)
        if not watchdog.observe_neural(readout) or not watchdog.observe_behavior(safe["intent"]):
            raise AssertionError("fresh healthy neural/behavior sample rejected")
        watched = watchdog.tick(now_ns=timestamp_ns, output_sequence=sequence)
        records.append({
            "step": step,
            "timestamp_ns": timestamp_ns,
            "looming": looming,
            "lplc2_external_count": sum(body_id in external for body_id in lplc2_ids),
            "lplc2_spike_count": sum(snapshot["spikes"][body_index[body_id]] for body_id in lplc2_ids),
            "dnp01_spike_count": sum(snapshot["spikes"][body_index[body_id]] for body_id in dn_ids),
            "dnp01_escape_readout": readout["escape"],
            "runtime_healthy": snapshot["healthy"],
            "decoder_stop": intent["stop"],
            "post_safety_stop": safe["intent"]["stop"],
            "watchdog_stop": watched["intent"]["stop"],
            "watchdog_state": watched["watchdog_state"],
            "watchdog_stale_reason": watched["stale_reason"],
        })
    active_records = records[protocol["warmup_steps"]:]
    neural_stops = [row for row in active_records if row["runtime_healthy"] and row["decoder_stop"]]
    end_to_end_stop = [row for row in neural_stops if row["post_safety_stop"] and row["watchdog_stop"]
                       and row["watchdog_state"] == "healthy"]
    return {
        "name": case["name"],
        "looming_amplitude": case["looming"],
        "steps": total,
        "max_escape_readout": max(row["dnp01_escape_readout"] for row in active_records),
        "total_lplc2_spikes": sum(row["lplc2_spike_count"] for row in active_records),
        "total_dnp01_spikes": sum(row["dnp01_spike_count"] for row in active_records),
        "healthy_neural_stop_count": len(neural_stops),
        "first_healthy_neural_stop_step": neural_stops[0]["step"] if neural_stops else None,
        "end_to_end_internal_stop_count": len(end_to_end_stop),
        "watchdog_fault_count": sum(row["watchdog_state"] != "healthy" for row in records),
        "records": records,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads((ROOT / "data/manifests/controller-graph-v2.json").read_text())
    artifact = Path(manifest["thor_artifact"])
    if sha256(artifact) != manifest["graph_sha256"]:
        raise ValueError("canonical graph-v2 SHA mismatch")
    protocol_path = ROOT / "config/g8_r4_recert_v1.json"
    protocol = json.loads(protocol_path.read_text())
    if protocol["schema_version"] != "g8-r4-neural-escape-fixture-v1" or protocol["timestep_ms"] != 20:
        raise ValueError("unsupported recertification fixture")
    graph = ConnectomeGraph.from_cache(artifact.parent, manifest["graph_sha256"])
    model = load_model_config(ROOT / "config/neural_model_v1.json")
    sensory = load_sensory_mapping_config(ROOT / "config/sensory_mapping_v1.json")
    dn_config = load_dn_readout_config(ROOT / "config/dn_readout_v1.json")
    escape_config = load_escape_decoder_config(ROOT / "config/escape_decoder_v1.json")
    safety_envelope = load_safety_envelope(ROOT / "config/safety_envelope_v1.json")
    for population in dn_config["populations"].values():
        if not set(population["body_ids"]) <= set(graph.body_ids):
            raise AssertionError("frozen DN readout absent from graph v2")
    cases = [run_case(graph, model, sensory, dn_config, escape_config, safety_envelope,
                      protocol, case) for case in protocol["cases"]]
    report = {
        "schema_version": "g8-r4-neural-escape-recert-v1",
        "dataset": manifest["dataset"],
        "graph_sha256": manifest["graph_sha256"],
        "source_commit_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "python_version": platform.python_version(),
        "protocol_sha256": sha256(protocol_path),
        "neural_model_sha256": sha256(ROOT / "config/neural_model_v1.json"),
        "sensory_mapping_sha256": sha256(ROOT / "config/sensory_mapping_v1.json"),
        "dn_readout_sha256": sha256(ROOT / "config/dn_readout_v1.json"),
        "escape_decoder_sha256": sha256(ROOT / "config/escape_decoder_v1.json"),
        "safety_envelope_sha256": sha256(ROOT / "config/safety_envelope_v1.json"),
        "watchdog_sha256": sha256(ROOT / "config/watchdog_v1.json"),
        "dn_body_ids": {name: spec["body_ids"] for name, spec in dn_config["populations"].items()},
        "escape_threshold": escape_config.threshold,
        "cases": cases,
        "scope": "internal frozen neural path; no official simulator/robotd behavior evidence",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n")
    print(json.dumps({case["name"]: {
        "max_escape_readout": case["max_escape_readout"],
        "total_dnp01_spikes": case["total_dnp01_spikes"],
        "healthy_neural_stop_count": case["healthy_neural_stop_count"],
        "end_to_end_internal_stop_count": case["end_to_end_internal_stop_count"],
    } for case in cases}, sort_keys=True))


if __name__ == "__main__":
    main()
