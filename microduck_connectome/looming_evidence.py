"""Bounded P2-01 structural evidence, reusing the G1 pinned-source adapter."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

import pyarrow.compute as pc

from .rebuild_pathway import acquire, annotation_table, canonical, digest, id_array, weight_batches

CONFIG = {
    "input_types": ["LC4", "LPLC2"],
    "target_type": "DNp01",
    "selection": "all exact-type flat annotations; all direct input-to-target rows; sum duplicate pairs",
    "denominator": "all outgoing source weights for each input type, including unannotated targets",
    "side": "raw somaSide annotation; no inferred hemisphere or projection side",
}


def build(annotations, weights, manifest, inventory_path, code_commit):
    """Hash-check sources and G1 identities before scanning all weights once."""
    if manifest["dataset"] != "male-cns:v1.0":
        raise ValueError("Unsupported dataset")
    if not isinstance(code_commit, str) or not re.fullmatch(r"[0-9a-f]{40}", code_commit):
        raise ValueError("code_commit must be a full lowercase Git SHA")
    inventory = json.loads(Path(inventory_path).read_bytes())
    if inventory["dataset"] != manifest["dataset"]:
        raise ValueError("G1 dataset mismatch")
    if inventory["source_manifest"] != manifest:
        raise ValueError("G1 source manifest mismatch")
    acquire(annotations, manifest["annotations"])
    acquire(weights, manifest["weights"])
    table = annotation_table(annotations, manifest["annotations"]["expected_rows"])
    populations = {}
    for name in CONFIG["input_types"] + [CONFIG["target_type"]]:
        rows = table.filter(pc.equal(table["type"], name)).sort_by("bodyId").to_pylist()
        if not rows or rows != inventory["candidate_inventory"][name]["source_records"]:
            raise ValueError(f"G1 identity mismatch for {name}")
        populations[name] = rows
    inputs = {row["bodyId"]: row for name in CONFIG["input_types"] for row in populations[name]}
    targets = {row["bodyId"]: row for row in populations[CONFIG["target_type"]]}
    source_array = id_array(inputs)
    edges, outgoing, source_rows = Counter(), Counter(), 0
    for batch in weight_batches(weights, manifest["weights"]["expected_rows"]):
        rows = batch.filter(pc.is_in(batch["body_pre"], value_set=source_array)).to_pylist()
        source_rows += len(rows)
        for row in rows:
            pre, post, weight = row["body_pre"], row["body_post"], row["weight"]
            outgoing[inputs[pre]["type"]] += weight
            if post in targets:
                edges[pre, post] += weight
    summary = []
    for name in CONFIG["input_types"]:
        sides = sorted({row["somaSide"] for row in populations[name]}, key=lambda v: str(v))
        for side in sides:
            members = {row["bodyId"] for row in populations[name] if row["somaSide"] == side}
            for target in sorted(targets):
                selected = {(pre, post): weight for (pre, post), weight in edges.items()
                            if pre in members and post == target}
                summary.append({"input_type": name, "input_soma_side": side,
                                "input_population_count": len(members), "target_body_id": target,
                                "target_soma_side": targets[target]["somaSide"],
                                "connected_input_count": len(selected),
                                "raw_synapse_weight": sum(selected.values())})
    return {
        "schema_version": "looming-direct-evidence-v1", "dataset": manifest["dataset"],
        "code_commit": code_commit, "source_manifest": manifest,
        "source_manifest_sha256": hashlib.sha256(canonical(manifest)).hexdigest(),
        "g1_inventory_sha256": digest(inventory_path),
        "config": CONFIG, "config_sha256": hashlib.sha256(canonical(CONFIG)).hexdigest(),
        "populations": populations,
        "direct_edges": [{"body_pre": pre, "body_post": post, "weight": edges[pre, post]}
                         for pre, post in sorted(edges)],
        "summary_by_input_side_and_target": summary,
        "all_outgoing_weight_by_input_type": dict(sorted(outgoing.items())),
        "selected_source_row_count": source_rows,
        "scanned_weight_rows": manifest["weights"]["expected_rows"],
        "limits": "Direct chemical connectivity to exact source type DNp01 only; no functional, sign, GF homology, laterality-of-projection, or robot-readout inference.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=Path("data/manifests/pathway-source-v1.json"))
    parser.add_argument("--inventory", type=Path, default=Path("docs/evidence/g1/pathway-report.json"))
    parser.add_argument("--code-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.resolve() in {p.resolve() for p in
                                (args.annotations, args.weights, args.manifest, args.inventory)}:
        raise ValueError("output must not overwrite an input")
    report = build(args.annotations, args.weights, json.loads(args.manifest.read_bytes()),
                   args.inventory, args.code_commit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical(report) + b"\n")
    print(json.dumps({"sha256": digest(args.output), "direct_edge_count": len(report["direct_edges"])}))


if __name__ == "__main__":
    main()
