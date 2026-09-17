"""Frozen research input selection from merged evidence; no ETL or controller."""

import argparse
import hashlib
import json
from pathlib import Path

from .dna02_evidence import DATASET, G1_HASHES, build_evidence, canonical


EVIDENCE_HASHES = {
    **{f"g1/{name}": digest for name, digest in G1_HASHES.items()},
    "p2-01/direct-evidence-v1.json": "6a291dff90ddbe14916f814d2181135758f12d402bb05653dfc395aa3dd1d878",
    "p2-02/dna02-v1.json": "68dd6675f64d0c565171fa157207e9b72c076b44fb3862f5cf6c09e0c9d8a606",
    "p2-03/dnp01-report.json": "c42502d854a1ad9e73412ed82f5a66d4da478a0f653e84f68f10a06b260dfdc6",
    "p2-04/mdn-v1.json": "df95b7d6cc8348e04c6c0cdb6ea747ceb89e738155d6047f32f5778e362dda36",
}


def population(records, cell_type):
    """Validate exact source identities; somaSide alone determines grouping."""
    if not records:
        raise ValueError("Empty source population")
    seen = set()
    groups = {"left": [], "right": []}
    for row in records:
        body = row.get("bodyId")
        if type(body) is not int or body <= 0 or body in seen:
            raise ValueError("Invalid or duplicate source body ID")
        seen.add(body)
        side = {"L": "left", "R": "right"}.get(row.get("somaSide"))
        if side is None:
            raise ValueError("Explicit source somaSide L/R required; no fallback")
        if row.get("type") != cell_type or row.get("superclass") != "visual_projection":
            raise ValueError("Exact visual projection source type required")
        groups[side].append(body)
    if not all(groups.values()):
        raise ValueError("Both source soma sides required")
    return {side: sorted(ids) for side, ids in groups.items()}


def build_selection(evidence_directory):
    """Rebuild the frozen artifact entirely from byte-pinned committed reports."""
    root = Path(evidence_directory)
    reports = {}
    for name, digest in EVIDENCE_HASHES.items():
        raw = (root / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError(f"Pinned evidence digest mismatch: {name}")
        reports[name] = json.loads(raw)
    # Existing bounded G1 evidence API verifies identity and readout laterality.
    dna02 = build_evidence(root / "g1")
    if canonical(dna02) != (root / "p2-02/dna02-v1.json").read_bytes():
        raise ValueError("Merged DNa02 evidence disagrees with G1")
    pathway = reports["g1/pathway-report.json"]
    query = reports["g1/query-report.json"]["path_query"]
    metadata = reports["g1/source-metadata.json"]["records"]
    by_id = {row["bodyId"]: row for row in metadata}
    inventories = pathway["candidate_inventory"]
    candidate_ids = {
        kind: population(inventories[kind]["source_records"], kind)
        for kind in ("LC10a", "LC4", "LPLC2")
    }
    selected = sorted(inventories["LC10a"]["source_records"], key=lambda r: r["bodyId"])
    if any(by_id.get(row["bodyId"]) != row for row in selected):
        raise ValueError("LC10a source inventory disagrees with selected G1 metadata")
    seed_ids = sorted(row["bodyId"] for row in selected)
    if query["seed_body_ids"] != seed_ids:
        raise ValueError("G1 query does not cover exact selected seeds")
    readouts = {r["side"]: r["raw_source_record"] for r in dna02["readouts"]}
    routes = []
    for source_side, ids in candidate_ids["LC10a"].items():
        for target_side, target in readouts.items():
            pairs = [p for p in query["pairs"]
                     if p["source_body_id"] in ids and p["target_body_id"] == target["bodyId"]]
            paths = [p for p in query["simple_two_hop_paths"]
                     if p[0] in ids and p[-1] == target["bodyId"]]
            if len(pairs) != len(ids) or not paths:
                raise ValueError("Incomplete bilateral route evidence")
            routes.append({
                "source_soma_side": source_side, "readout_soma_side": target_side,
                "target_body_id": target["bodyId"],
                "reachable_input_count": sum(p["shortest_path"] is not None for p in pairs),
                "unreachable_input_ids": sorted(p["source_body_id"] for p in pairs
                                                if p["shortest_path"] is None),
                "simple_two_edge_path_count": len(paths),
                "example_source_records": [by_id[body] for body in min(paths)],
            })
    config = {
        "schema_version": "tracking-input-config-v1", "dataset": DATASET,
        "input_type": "LC10a", "input_ids_by_soma_side": candidate_ids["LC10a"],
        "readout_type": "DNa02",
        "readout_ids_by_soma_side": {side: row["bodyId"] for side, row in readouts.items()},
        "graph_cache_key": dna02["graph_cache_key"],
        "selection_rule": "all exact-type LC10a annotation records; no reachability cherry-picking",
        "scope": "research identity freeze only; controller parameters and functional laterality unresolved",
    }
    return {
        "schema_version": "tracking-selection-v1", "dataset": DATASET,
        "task": "P2-05", "base_commit": "231b27b46c37fa4f5e575212da41f8692abda557",
        "decision": "select LC10a as tracking sensory candidate for subsequent simulation",
        "source_evidence_sha256": EVIDENCE_HASHES,
        "source_manifest": pathway["source_manifest"],
        "g1_producer_commit": pathway["code_commit"],
        "config": config, "config_sha256": hashlib.sha256(canonical(config)).hexdigest(),
        "selected_source_records": selected, "readout_source_records": readouts,
        "candidate_ids_by_soma_side": candidate_ids,
        "candidate_dispositions": {
            "LC10a": "selected: tracking literature and bilateral structural routes; function unvalidated",
            "LC4": "not selected for tracking: looming/escape evidence; DNa02 route not tested",
            "LPLC2": "not selected for tracking: looming/escape evidence; DNa02 route not tested",
        },
        "route_scope": "G1 induced graph; directed <=2 hops, raw weight >=1; soma annotations only",
        "example_rule": "lexicographically first path per soma-side pair; not strongest/causal route",
        "routes": routes,
        "limitations": [
            "Soma side is not stimulus hemifield, synapse location or simulator yaw sign.",
            "Path counts are not signed efficacy, independent replicates or behavioral strength.",
            "Other candidates lack matched G1 DNa02 queries; no absent-route claim or fair efficacy ranking.",
            "LC10a experiments are state-dependent fly courtship; no MaleCNS or robot functional validation.",
            "No controller gains, normalization, neural model, robot commands or gate approval are frozen.",
        ],
    }


def validate_selection(path, evidence_directory):
    expected = canonical(build_selection(evidence_directory))
    if Path(path).read_bytes() != expected:
        raise ValueError("Tracking selection differs from frozen deterministic evidence")
    return hashlib.sha256(expected).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=Path("docs/evidence"))
    parser.add_argument("--check", type=Path, required=True)
    args = parser.parse_args()
    print(f"Tracking selection valid: sha256={validate_selection(args.check, args.evidence)}")


if __name__ == "__main__":
    main()
