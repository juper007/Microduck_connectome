"""Bounded DNp01 identity/connectivity evidence from the pinned public flat files."""

import argparse
from collections import Counter
import json
from pathlib import Path
import re

import pyarrow.compute as pc
import pyarrow.feather as feather

from .rebuild_pathway import acquire, annotation_table, canonical, digest, id_array, weight_batches

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data/manifests/pathway-source-v1.json"
ALIAS_FIELDS = ["type", "instance", "synonyms", "hemibrainType", "flywireType", "mancType"]
DETAIL_FIELDS = ["bodyId", "type", "instance", "somaSide", "class", "superclass",
                 "somaNeuromere", "status", "statusLabel", *ALIAS_FIELDS[2:]]
ALIAS_PATTERN = r"(?i)(?<![A-Za-z0-9])(?:GF|giant[ _-]?fib(?:er|re))(?![A-Za-z0-9])"
CONFIG = {"schema_version": "dnp01-evidence-v1", "input_types": ["LC4", "LPLC2"],
          "readout_type": "DNp01", "alias_fields": ALIAS_FIELDS,
          "alias_pattern": ALIAS_PATTERN, "top_outgoing_per_readout": 20,
          "edge_filter": "all source rows incident to exact-type DNp01; no additional threshold",
          "side_semantics": "somaSide only; no projection or functional side inferred"}


def identity(rows):
    """Record exact fields; never use an alias to silently select a readout."""
    selected = sorted((r for r in rows if r["type"] == "DNp01"), key=lambda r: r["bodyId"])
    if (len(selected) != 2 or {r["somaSide"] for r in selected} != {"L", "R"}
            or any(r["superclass"] != "descending_neuron" for r in selected)):
        raise ValueError("Expected two source-sided descending DNp01 neurons")
    hits = []
    for r in rows:
        matches = {f: r[f] for f in ALIAS_FIELDS if r.get(f) and re.search(ALIAS_PATTERN, r[f])}
        if matches:
            hits.append({"bodyId": r["bodyId"], "type": r["type"], "somaSide": r["somaSide"], "matches": matches})
    return {"readouts": selected, "alias_matches": sorted(hits, key=lambda r: r["bodyId"]),
            "exact_GF_type_body_ids": sorted(r["bodyId"] for r in rows if r["type"] == "GF")}


def summarize(rows, edges):
    annotations = {r["bodyId"]: r for r in rows}
    info = identity(rows)
    readouts = {r["bodyId"] for r in info["readouts"]}
    inputs = [r for r in rows if r["type"] in CONFIG["input_types"]]
    input_ids = {r["bodyId"] for r in inputs}
    # Aggregate duplicate source rows explicitly; stable sorting makes batch order immaterial.
    totals = Counter()
    for pre, post, weight in edges:
        if type(weight) is not int or weight <= 0:
            raise ValueError("Invalid connection weight")
        if pre in readouts or post in readouts:
            totals[pre, post] += weight
    direct = [{"body_pre": a, "body_post": b, "weight": w}
              for (a, b), w in sorted(totals.items()) if a in input_ids and b in readouts]
    summary = []
    for target in sorted(readouts):
        for typ in CONFIG["input_types"]:
            subset = [e for e in direct if e["body_post"] == target and annotations[e["body_pre"]]["type"] == typ]
            summary.append({"body_post": target, "input_type": typ,
                            "connected_input_bodies": len(subset), "weight": sum(e["weight"] for e in subset)})
    outgoing = []
    for source in sorted(readouts):
        subset = [(b, w) for (a, b), w in totals.items() if a == source]
        groups = {}
        for body, weight in subset:
            target = annotations.get(body)
            label = target.get("superclass") if target else None
            # Distinguish absent annotation from an annotated body with null superclass.
            key = (target is not None, label)
            item = groups.setdefault(key, {"annotated": key[0], "superclass": label, "target_bodies": 0, "weight": 0})
            item["target_bodies"] += 1
            item["weight"] += weight
        outgoing.append({"body_pre": source, "target_bodies": len(subset),
                         "weight": sum(w for _, w in subset),
                         "target_superclasses": sorted(groups.values(), key=lambda r: (r["annotated"], r["superclass"] or "")),
                         "top_targets": [{"body_post": b, "weight": w, "annotation": annotations.get(b)}
                                         for b, w in sorted(subset, key=lambda p: (-p[1], p[0]))[:20]]})
    return {**info, "input_records": sorted(inputs, key=lambda r: r["bodyId"]),
            "direct_visual_edges": direct, "direct_visual_summary": summary,
            "outgoing": outgoing}


def build(annotations_path, weights_path, output, download=False):
    manifest = json.loads(MANIFEST.read_text())
    for path, key in [(annotations_path, "annotations"), (weights_path, "weights")]:
        acquire(path, manifest[key], download)
    annotation_table(annotations_path, manifest["annotations"]["expected_rows"])
    rows = feather.read_table(annotations_path, columns=DETAIL_FIELDS).to_pylist()
    selected = identity(rows)
    ids = id_array(r["bodyId"] for r in selected["readouts"])
    edges = []
    for batch in weight_batches(weights_path, manifest["weights"]["expected_rows"]):
        selected_batch = batch.filter(pc.or_(pc.is_in(batch["body_pre"], value_set=ids),
                                             pc.is_in(batch["body_post"], value_set=ids)))
        edges.extend(zip(*(selected_batch[n].to_pylist() for n in ["body_pre", "body_post", "weight"])))
    report = {"dataset": manifest["dataset"], "config": CONFIG,
              "source_manifest": manifest, "source_manifest_sha256": digest(MANIFEST),
              "producer_files_sha256": {f: digest(ROOT / f) for f in [
                  "microduck_connectome/dnp01_evidence.py", "microduck_connectome/rebuild_pathway.py", "uv.lock"]},
              "incident_source_rows": len(edges), **summarize(rows, edges)}
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_bytes(canonical(report) + b"\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    if args.output.resolve() in {args.annotations.resolve(), args.weights.resolve()}:
        parser.error("Output must not overwrite a source")
    build(args.annotations, args.weights, args.output, args.download)
    print(digest(args.output))


if __name__ == "__main__":
    main()
