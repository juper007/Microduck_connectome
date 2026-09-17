"""Reproduce a bounded MDN research report from pinned public MaleCNS sources."""

import argparse
from collections import Counter
import json
from pathlib import Path
import re

import hashlib

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data/manifests/pathway-source-v1.json"
G1 = ROOT / "docs/evidence/g1/pathway-report.json"
G1_SHA = "5eeed1f5fb5c43af80f08f42c8eaebac97e3d8c8c4c39f7d70d6902b9d7d6407"
ALIAS_FIELDS = ["type", "instance", "synonyms", "hemibrainType", "flywireType", "mancType"]
FIELDS = ["bodyId", "type", "instance", "somaSide", "class", "superclass", "somaNeuromere",
          "status", "statusLabel", *ALIAS_FIELDS[2:]]
PATTERN = r"(?i)(?<![A-Za-z0-9])(?:MDN|DNp50|LBL40|LUL130|Pair1)(?![A-Za-z0-9])"
CONFIG = {"schema_version": "mdn-evidence-v1", "readout_type": "MDN",
          "downstream_exact_types": ["LBL40", "LUL130"], "alias_fields": ALIAS_FIELDS,
          "alias_pattern": PATTERN, "top_targets_per_readout": 10,
          "selection": "all outgoing rows from every exact-type MDN; no additional threshold",
          "weight_semantics": "raw source connection counts; duplicates summed; no normalization",
          "side_semantics": "literal somaSide L/R only; no functional/projection-side inference"}


def identity(rows):
    selected = sorted((r for r in rows if r["type"] == "MDN"), key=lambda r: r["bodyId"])
    if (len(selected) != 4 or len({r["bodyId"] for r in selected}) != 4
            or any(type(r["bodyId"]) is not int or r["bodyId"] <= 0 for r in selected)
            or Counter(r.get("somaSide") for r in selected) != {"L": 2, "R": 2}
            or any(r.get("superclass") != "descending_neuron" for r in selected)):
        raise ValueError("MDN requires four distinct positive IDs, two explicit L/two R descending neurons")
    return selected


def summarize(rows, edges):
    if len({r["bodyId"] for r in rows}) != len(rows):
        raise ValueError("Duplicate annotation body ID")
    by_id = {r["bodyId"]: r for r in rows}
    readouts = identity(rows)
    ids = {r["bodyId"] for r in readouts}
    totals = Counter()
    for pre, post, weight in edges:
        if any(type(v) is not int or v <= 0 for v in (pre, post, weight)):
            raise ValueError("Invalid positive integer edge")
        if pre not in ids:
            raise ValueError("Edge source outside exact MDN population")
        totals[pre, post] += weight
    outgoing = []
    for source in sorted(ids):
        subset = [(post, w) for (pre, post), w in totals.items() if pre == source]
        groups = {}
        for target, weight in subset:
            row = by_id.get(target)
            key = (row is not None, row.get("superclass") if row else None)
            item = groups.setdefault(key, {"annotated": key[0], "superclass": key[1], "bodies": 0, "weight": 0})
            item["bodies"] += 1
            item["weight"] += weight
        outgoing.append({"body_pre": source, "target_bodies": len(subset), "weight": sum(w for _, w in subset),
                         "target_superclasses": sorted(groups.values(), key=lambda r: (r["annotated"], r["superclass"] or "")),
                         "top_targets": [{"body_post": b, "weight": w, "annotation": by_id.get(b)}
                                         for b, w in sorted(subset, key=lambda p: (-p[1], p[0]))[:10]]})
    downstream = []
    for typ in CONFIG["downstream_exact_types"]:
        selected = sorted((r for r in rows if r["type"] == typ), key=lambda r: r["bodyId"])
        target_ids = {r["bodyId"] for r in selected}
        direct = [{"body_pre": a, "body_post": b, "weight": w}
                  for (a, b), w in sorted(totals.items()) if b in target_ids]
        downstream.append({"type": typ, "status": "present" if selected else "absent_exact_type",
                           "source_records": selected, "direct_edges": direct,
                           "total_weight": sum(e["weight"] for e in direct)})
    aliases = []
    for row in rows:
        matches = {f: row[f] for f in ALIAS_FIELDS if row.get(f) and re.search(PATTERN, row[f])}
        if matches:
            aliases.append({"bodyId": row["bodyId"], "type": row["type"], "somaSide": row["somaSide"], "matches": matches})
    return {"readouts": readouts, "outgoing": outgoing, "downstream": downstream,
            "alias_matches": sorted(aliases, key=lambda r: r["bodyId"])}


def build(annotations_path, weights_path, output, download=False):
    # Protect source bytes for library callers as well as CLI callers.
    if Path(output).resolve() in {Path(annotations_path).resolve(), Path(weights_path).resolve(), MANIFEST.resolve(), G1.resolve()}:
        raise ValueError("Output must not overwrite an input")
    from .rebuild_pathway import acquire, annotation_table, canonical, digest, id_array, weight_batches
    manifest = json.loads(MANIFEST.read_text())
    if manifest["dataset"] != "male-cns:v1.0":
        raise ValueError("Dataset mismatch")
    if digest(G1) != G1_SHA:
        raise ValueError("G1 digest mismatch")
    g1_report = json.loads(G1.read_text())
    if manifest != g1_report["source_manifest"]:
        raise ValueError("Source manifest differs from pinned G1 manifest")
    for path, key in [(annotations_path, "annotations"), (weights_path, "weights")]:
        acquire(path, manifest[key], download)
    annotation_table(annotations_path, manifest["annotations"]["expected_rows"])
    import pyarrow.compute as pc
    import pyarrow.feather as feather
    rows = feather.read_table(annotations_path, columns=FIELDS).to_pylist()
    readouts = identity(rows)
    expected = g1_report["candidate_inventory"]["MDN"]["source_records"]
    if [{k: row[k] for k in expected[0]} for row in readouts] != expected:
        raise ValueError("MDN source differs from committed G1 identity")
    selected_ids = id_array(r["bodyId"] for r in readouts)
    edges = []
    for batch in weight_batches(weights_path, manifest["weights"]["expected_rows"]):
        selected = batch.filter(pc.is_in(batch["body_pre"], value_set=selected_ids))
        edges.extend(zip(*(selected[n].to_pylist() for n in ["body_pre", "body_post", "weight"])))
    result = {"dataset": manifest["dataset"], "config": CONFIG, "g1_pathway_sha256": G1_SHA,
              "source_manifest": manifest, "source_manifest_sha256": digest(MANIFEST),
              "producer_files_sha256": {f: digest(ROOT / f) for f in [
                  "microduck_connectome/mdn_evidence.py", "microduck_connectome/rebuild_pathway.py", "uv.lock"]},
              "outgoing_source_rows": len(edges), **summarize(rows, edges)}
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_bytes(canonical(result) + b"\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    build(args.annotations, args.weights, args.output, args.download)
    print(hashlib.sha256(args.output.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
