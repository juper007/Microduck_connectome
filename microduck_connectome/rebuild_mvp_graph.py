"""Build a source-derived MVP graph for both frozen sensory-to-DN paths.

The two declared path pairs and depth are fixed in config/graph_v2.json before
behavior experiments. The source-outgoing denominator is calculated by the
existing connectivity extractor over complete selected-source rows.
"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

import pyarrow.compute as pc

from .annotations import normalize_annotations
from .connectivity import extract_connectivity
from .graph_cache import store_graph
from .neuprint_client import DATASET
from .rebuild_pathway import (
    NORMALIZATION,
    acquire,
    annotation_table,
    canonical,
    counts,
    id_array,
    weight_batches,
)

ROOT = Path(__file__).resolve().parents[1]
SELECTION = (
    "all exact-type seed and readout cells for both declared pairs, plus "
    "every annotated distinct intermediate on a directed two-edge path for "
    "either pair; retain all induced source edges"
)
PAIRS = (("LC10a", "DNa02", 2), ("LPLC2", "DNp01", 2))


def _validated_pairs(config):
    if (
        config.get("schema_version") != "mvp-path-selection-v2"
        or config.get("dataset") != DATASET
        or config.get("selection") != SELECTION
        or config.get("normalization") != NORMALIZATION
        or config.get("side_authority")
        != "official annotation somaSide; never numeric body ID order"
        or [(p.get("seed_type"), p.get("readout_type"), p.get("max_edges"))
            for p in config.get("path_pairs", [])] != list(PAIRS)
    ):
        raise ValueError("Unsupported graph-v2 selection or normalization")
    return PAIRS


def select_nodes(table, weights_path, manifest, config):
    """Return source-identified IDs and counted directed reachability.

    One full source scan collects the first and second sides of every declared
    two-edge path. Direct edges are counted separately. No edge is fabricated.
    """
    pairs = _validated_pairs(config)
    populations = {}
    for name in sorted({name for pre, post, _ in pairs for name in (pre, post)}):
        rows = table.filter(pc.equal(table["type"], name)).sort_by("bodyId").to_pylist()
        if not rows:
            raise ValueError(f"Required exact source type absent: {name}")
        populations[name] = rows
    ids = {name: {row["bodyId"] for row in rows} for name, rows in populations.items()}
    arrays = {name: id_array(values) for name, values in ids.items()}
    first_targets = {name: set() for name, _, _ in pairs}
    second_sources = {name: set() for _, name, _ in pairs}
    first_counts = {name: Counter() for name, _, _ in pairs}
    second_counts = {name: Counter() for _, name, _ in pairs}
    direct_edges = {f"{pre}->{post}": [] for pre, post, _ in pairs}
    for batch in weight_batches(weights_path, manifest["weights"]["expected_rows"]):
        for pre, post, _ in pairs:
            first = batch.filter(pc.is_in(batch["body_pre"], value_set=arrays[pre]))
            second = batch.filter(pc.is_in(batch["body_post"], value_set=arrays[post]))
            first_targets[pre].update(pc.unique(first["body_post"]).to_pylist())
            second_sources[post].update(pc.unique(second["body_pre"]).to_pylist())
            first_counts[pre].update(row["body_post"] for row in first.to_pylist())
            second_counts[post].update(row["body_pre"] for row in second.to_pylist())
            direct = first.filter(pc.is_in(first["body_post"], value_set=arrays[post]))
            direct_edges[f"{pre}->{post}"].extend(direct.to_pylist())
    annotated = set(table["bodyId"].to_pylist())
    endpoints = set().union(*ids.values())
    intermediates = set()
    paths = {}
    for pre, post, _ in pairs:
        overlap = first_targets[pre] & second_sources[post]
        internal = (overlap & annotated) - endpoints
        intermediates.update(internal)
        key = f"{pre}->{post}"
        paths[key] = {
            "direct_edge_count": len(direct_edges[key]),
            "direct_weight_sum": sum(row["weight"] for row in direct_edges[key]),
            "source_two_edge_path_count": sum(
                first_counts[pre][middle] * second_counts[post][middle]
                for middle in overlap
            ),
            "selected_two_edge_path_count": sum(
                first_counts[pre][middle] * second_counts[post][middle]
                for middle in internal
            ),
            "two_edge_intermediate_count": len(internal),
            "two_edge_intermediate_body_ids": sorted(internal),
            "unannotated_overlap_count": len(overlap - annotated),
        }
    selected = endpoints | intermediates
    return selected, populations, paths, intermediates


def rebuild(annotations_path, weights_path, manifest, config, code_commit, output_dir):
    if manifest["dataset"] != DATASET:
        raise ValueError("Unsupported source dataset")
    _validated_pairs(config)
    output_dir = Path(output_dir)
    if output_dir.resolve() in (Path(annotations_path).resolve(), Path(weights_path).resolve()):
        raise ValueError("Output must not replace source")
    acquire(annotations_path, manifest["annotations"])
    acquire(weights_path, manifest["weights"])
    table = annotation_table(annotations_path, manifest["annotations"]["expected_rows"])
    selected, populations, paths, intermediates = select_nodes(
        table, weights_path, manifest, config
    )
    selected_array = id_array(selected)
    raw_records = table.filter(pc.is_in(table["bodyId"], value_set=selected_array)).sort_by("bodyId").to_pylist()
    projected = [
        {
            "bodyId": row["bodyId"],
            "type": row["type"] or None,
            "instance": row["instance"] or None,
            "class": row["class"] or None,
            "somaSide": {"L": "left", "R": "right"}.get(row["somaSide"]),
        }
        for row in raw_records
    ]
    config_hash = hashlib.sha256(canonical(config)).hexdigest()
    annotations = normalize_annotations(
        projected,
        dataset=DATASET,
        source_note=(
            f"public flat annotations sha256:{manifest['annotations']['sha256']}; "
            f"selection sha256:{config_hash}; raw fields in G8-R1 source report"
        ),
        extraction_commit=code_commit,
    )
    outgoing_rows = []
    for batch in weight_batches(weights_path, manifest["weights"]["expected_rows"]):
        outgoing_rows.extend(batch.filter(pc.is_in(batch["body_pre"], value_set=selected_array)).to_pylist())
    graph = extract_connectivity(
        annotations,
        outgoing_rows,
        dataset=DATASET,
        source_sha256=manifest["weights"]["sha256"],
        confidence_filter=manifest["confidence_filter"],
        extraction_commit=code_commit,
        created_utc=config["created_utc"],
        query_or_extraction_config=canonical(config).decode(),
        seed_populations=[pre for pre, _, _ in PAIRS],
        readout_populations=[post for _, post, _ in PAIRS],
        selection_rules=config["selection"],
    )
    key = store_graph(output_dir / "graphs", graph)
    report = {
        "schema_version": "mvp-graph-report-v2",
        "dataset": DATASET,
        "source_manifest_sha256": hashlib.sha256(canonical(manifest)).hexdigest(),
        "source_annotations_sha256": manifest["annotations"]["sha256"],
        "source_weights_sha256": manifest["weights"]["sha256"],
        "selection_config_sha256": config_hash,
        "selection_config": config,
        "code_commit": code_commit,
        "populations": {
            name: {
                "body_ids": [row["bodyId"] for row in rows],
                "left_body_ids": [row["bodyId"] for row in rows if row["somaSide"] == "L"],
                "right_body_ids": [row["bodyId"] for row in rows if row["somaSide"] == "R"],
                "soma_side_counts": counts(rows, "somaSide"),
            }
            for name, rows in populations.items()
        },
        "paths": paths,
        "intermediate_body_ids": sorted(intermediates),
        "selected_body_ids": sorted(selected),
        "graph": {"cache_key": key, "relative_path": f"graphs/{key}.json", "manifest": graph["manifest"]},
        "normalization": NORMALIZATION,
        "complete_selected_source_rows": len(outgoing_rows),
        "scope": "structural connectivity only; no behavioral or biological causality claim",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "reachability-report-v1.json").write_bytes(canonical(report) + b"\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--code-commit", required=True)
    parser.add_argument("--manifest", type=Path, default=ROOT / "data/manifests/pathway-source-v1.json")
    parser.add_argument("--config", type=Path, default=ROOT / "config/graph_v2.json")
    args = parser.parse_args()
    report = rebuild(args.annotations, args.weights, json.loads(args.manifest.read_text()),
                     json.loads(args.config.read_text()), args.code_commit, args.output_dir)
    print(json.dumps({"graph_cache_key": report["graph"]["cache_key"],
                      "node_count": report["graph"]["manifest"]["node_count"],
                      "edge_count": report["graph"]["manifest"]["edge_count"],
                      "paths": {k: {"direct": v["direct_edge_count"],
                                     "two_edge_intermediates": v["two_edge_intermediate_count"]}
                                for k, v in report["paths"].items()}}, sort_keys=True))


if __name__ == "__main__":
    main()
