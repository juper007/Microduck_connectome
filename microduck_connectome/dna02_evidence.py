"""Offline, hash-bound DNa02 research slice; no new extraction or physiology."""

import argparse
import hashlib
import json
from pathlib import Path


G1_HASHES = {
    "pathway-report.json": "5eeed1f5fb5c43af80f08f42c8eaebac97e3d8c8c4c39f7d70d6902b9d7d6407",
    "query-report.json": "bf7cb25c774e08415f76dfc63b77d17acf2ada0671317ffb755888d38d6c5d1e",
    "source-metadata.json": "4748b141ba5a6c28f093ad225a610c59abc4a934c2318377ec8b9ad1c7ed2a99",
}
DATASET = "male-cns:v1.0"


def resolve_sides(records):
    """Accept only explicit raw somaSide L/R, never IDs/order/name suffixes."""
    selected = [r for r in records if r["type"] == "DNa02"]
    if len(selected) != 2 or len({r["bodyId"] for r in selected}) != 2:
        raise ValueError("DNa02 requires exactly two distinct source bodies")
    sides = {}
    for row in selected:
        side = {"L": "left", "R": "right"}.get(row.get("somaSide"))
        if side is None or side in sides:
            raise ValueError("DNa02 requires one explicit L and one explicit R")
        if row.get("superclass") != "descending_neuron":
            raise ValueError("DNa02 source superclass mismatch")
        sides[side] = row
    return {side: sides[side] for side in sorted(sides)}


def build_evidence(g1_directory):
    reports = {}
    for name, expected in G1_HASHES.items():
        raw = (Path(g1_directory) / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError(f"Pinned G1 evidence digest mismatch: {name}")
        reports[name] = json.loads(raw)
    pathway = reports["pathway-report.json"]
    query = reports["query-report.json"]
    metadata = reports["source-metadata.json"]
    if any(r["dataset"] != DATASET for r in reports.values()):
        raise ValueError("Dataset mismatch")
    sides = resolve_sides(metadata["records"])
    inventory = resolve_sides(pathway["candidate_inventory"]["DNa02"]["source_records"])
    if sides != inventory:
        raise ValueError("DNa02 source/inventory mismatch")
    by_id = {r["bodyId"]: r for r in metadata["records"]}
    paths = query["path_query"]
    summaries = []
    for side, record in sides.items():
        body = record["bodyId"]
        reachable = [p for p in paths["pairs"]
                     if p["target_body_id"] == body and p["shortest_path"] is not None]
        two_hop = [p for p in paths["simple_two_hop_paths"] if p[-1] == body]
        example = min(two_hop)
        summaries.append({
            "side": side, "body_id": body, "raw_source_record": record,
            "reachable_LC10a_body_count": len(reachable),
            "simple_two_edge_path_count": len(two_hop),
            "example_two_edge_path": [by_id[b] for b in example],
        })
    return {
        "schema_version": "dna02-evidence-v1", "dataset": DATASET,
        "source_g1_sha256": G1_HASHES,
        "source_manifest": pathway["source_manifest"],
        "g1_producer_commit": pathway["code_commit"],
        "graph_cache_key": query["root_key"],
        "side_rule": "literal source somaSide L -> left, R -> right; no fallback",
        "path_scope": "G1 selected LC10a induced graph; directed <=2 hops, raw weight >=1",
        "example_rule": "lexicographically first two-edge path; no strength or functional ranking",
        "readouts": summaries,
        "limitations": [
            "No new raw-data extraction; inherits reviewed G1 source provenance.",
            "G1 graph excludes VNC intrinsic population; not a full DNa02 output census.",
            "Connectivity is structural, not causal function or signed efficacy.",
        ],
    }


def canonical(value):
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--g1", type=Path, default=Path("docs/evidence/g1"))
    parser.add_argument("--check", type=Path, required=True,
                        help="compare committed evidence byte-for-byte; never writes")
    args = parser.parse_args()
    expected = canonical(build_evidence(args.g1))
    if args.check.read_bytes() != expected:
        raise SystemExit("DNa02 evidence differs from deterministic G1 slice")
    print(f"DNa02 evidence valid: sha256={hashlib.sha256(expected).hexdigest()}")


if __name__ == "__main__":
    main()
