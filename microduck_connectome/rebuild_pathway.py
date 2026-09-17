"""Rebuild a deterministic two-hop graph from hash-pinned public Feather files."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import tempfile
from urllib.request import urlopen

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.feather as feather
import pyarrow.ipc as ipc

from .annotations import normalize_annotations
from .connectivity import extract_connectivity
from .graph_cache import store_graph
from .neuprint_client import DATASET

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ["bodyId", "type", "instance", "somaSide", "class", "superclass", "somaNeuromere"]
SELECTION = "all exact-type seeds and readouts plus annotated distinct intermediate nodes on seed-to-readout directed two-edge paths; retain all induced edges"
NORMALIZATION = "all source outgoing rows for each selected node including unannotated and unselected targets; no weight threshold"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("utf-8")


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def acquire(path, spec, download=False):
    """Never replace existing bad inputs; verify downloads before publishing."""
    path = Path(path)
    if not path.exists():
        if not download:
            raise FileNotFoundError(f"Missing source {path}; supply --download to acquire")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as out:
                temporary = Path(out.name)
                with urlopen(spec["url"], timeout=60) as response:
                    while chunk := response.read(1024 * 1024):
                        out.write(chunk)
            if digest(temporary) != spec["sha256"]:
                raise ValueError("Downloaded source checksum mismatch")
            temporary.replace(path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    if digest(path) != spec["sha256"]:
        raise ValueError(f"Source checksum mismatch: {path}")


def annotation_table(path, expected_rows):
    table = feather.read_table(path, columns=FIELDS)
    for field in FIELDS:
        expected = pa.int64() if field == "bodyId" else pa.string()
        if table.schema.field(field).type != expected:
            raise ValueError(f"Invalid annotation column type: {field}")
    ids = table["bodyId"]
    if (table.num_rows != expected_rows or ids.null_count or
            pc.any(pc.less_equal(ids, 0)).as_py() or len(pc.unique(ids)) != table.num_rows):
        raise ValueError("Invalid annotation count or body IDs")
    return table


def weight_batches(path, expected_rows):
    """Feather V2 IPC batches bound memory; never materialize the full weights table."""
    with pa.memory_map(str(path), "r") as source:
        reader = ipc.open_file(source)
        names = ["body_pre", "body_post", "weight"]
        for name in names:
            if reader.schema.field(name).type != pa.int64():
                raise ValueError(f"Invalid weight column type: {name}")
        count = 0
        for index in range(reader.num_record_batches):
            batch = reader.get_batch(index).select(names)
            count += batch.num_rows
            for name in names:
                column = batch.column(name)
                if column.null_count or pc.any(pc.less_equal(column, 0)).as_py():
                    raise ValueError(f"Invalid nonpositive/null weight value: {name}")
            yield batch
        if count != expected_rows:
            raise ValueError(f"Weight row count mismatch: {count} != {expected_rows}")


def id_array(ids):
    return pa.array(sorted(ids), type=pa.int64())


def counts(rows, name):
    # JSON encodes null and empty distinctly; never infer laterality from names.
    values = Counter(json.dumps(row[name]) for row in rows)
    return [{"value": json.loads(key), "count": count} for key, count in sorted(values.items())]


def rebuild(annotations_path, weights_path, manifest, config, code_commit, output_dir,
            *, download=False):
    """Verify all bytes, select paths, then pass complete selected-source rows to extraction."""
    if manifest["dataset"] != DATASET:
        raise ValueError("Unsupported dataset")
    if (config["schema_version"] != "two-hop-selection-v1" or
            config["selection"] != SELECTION or config["normalization"] != NORMALIZATION):
        raise ValueError("Unsupported selection/normalization semantics")
    output_dir = Path(output_dir)
    report_path = output_dir / "pathway-report.json"
    metadata_path = output_dir / "source-metadata.json"
    if {report_path.resolve(), metadata_path.resolve()} & {Path(annotations_path).resolve(), Path(weights_path).resolve()}:
        raise ValueError("Report must not overwrite a source")
    acquire(annotations_path, manifest["annotations"], download)
    acquire(weights_path, manifest["weights"], download)
    table = annotation_table(annotations_path, manifest["annotations"]["expected_rows"])
    candidates = {}
    for name in config["candidate_types"]:
        rows = table.filter(pc.equal(table["type"], name)).sort_by("bodyId").to_pylist()
        candidates[name] = {"status": "present" if rows else "absent_exact_type",
                            "count": len(rows), "body_ids": [r["bodyId"] for r in rows],
                            "source_records": rows, "soma_side_counts": counts(rows, "somaSide")}
    def population(name):
        return set(table.filter(pc.equal(table["type"], name))["bodyId"].to_pylist())
    seeds, readouts = population(config["seed_type"]), population(config["readout_type"])
    if not seeds or not readouts:
        raise ValueError("Required exact seed/readout population absent")
    annotated = set(table["bodyId"].to_pylist())
    first_targets, second_sources = set(), set()
    seed_array, readout_array = id_array(seeds), id_array(readouts)
    # One vectorized scan computes both sides of the two-hop intersection.
    for batch in weight_batches(weights_path, manifest["weights"]["expected_rows"]):
        first = batch.filter(pc.is_in(batch["body_pre"], value_set=seed_array))
        second = batch.filter(pc.is_in(batch["body_post"], value_set=readout_array))
        first_targets.update(pc.unique(first["body_post"]).to_pylist())
        second_sources.update(pc.unique(second["body_pre"]).to_pylist())
    overlap = first_targets & second_sources
    intermediates = (overlap & annotated) - seeds - readouts
    selected = seeds | readouts | intermediates
    selected_array = id_array(selected)
    raw_records = table.filter(pc.is_in(table["bodyId"], value_set=selected_array)).sort_by("bodyId").to_pylist()
    projected = []
    for row in raw_records:
        projected.append({"bodyId": row["bodyId"],
                          "type": row["type"] or None, "instance": row["instance"] or None,
                          "class": row["class"] or None,
                          "somaSide": {"L": "left", "R": "right"}.get(row["somaSide"])})
    config_hash = hashlib.sha256(canonical(config)).hexdigest()
    annotation = normalize_annotations(projected, dataset=DATASET,
        source_note=f"public flat annotations sha256:{manifest['annotations']['sha256']}; selection sha256:{config_hash}; raw fields in pathway report",
        extraction_commit=code_commit)
    # Only selected-source rows enter Python. NO target or annotation mask here.
    outgoing_rows = []
    for batch in weight_batches(weights_path, manifest["weights"]["expected_rows"]):
        outgoing_rows.extend(batch.filter(pc.is_in(batch["body_pre"], value_set=selected_array)).to_pylist())
    graph = extract_connectivity(annotation, outgoing_rows, dataset=DATASET,
        source_sha256=manifest["weights"]["sha256"], confidence_filter=manifest["confidence_filter"],
        extraction_commit=code_commit, created_utc=config["created_utc"],
        query_or_extraction_config=canonical(config).decode(), seed_populations=[config["seed_type"]],
        readout_populations=[config["readout_type"]], selection_rules=config["selection"])
    key = store_graph(output_dir / "graphs", graph)
    report = {
        "schema_version": "pathway-report-v1", "dataset": DATASET, "code_commit": code_commit,
        "source_manifest": manifest, "source_manifest_sha256": hashlib.sha256(canonical(manifest)).hexdigest(),
        "selection_config": config, "selection_config_sha256": config_hash,
        "population_definition": "all rows of the pinned official flat annotation file; no neuPrint neuron-label restriction",
        "candidate_inventory": candidates, "selected_body_ids": sorted(selected),
        "intermediate_body_ids": sorted(intermediates), "source_annotation_records": raw_records,
        "source_field_counts": {name: counts(raw_records, name) for name in FIELDS[1:]},
        "annotation_adapter": {"L": "left", "R": "right",
            "other_sides": "null in annotation-v1; raw M, empty, null and unknown values preserved distinctly in source_annotation_records",
            "empty_optional_text": "empty type/instance/class maps to null; raw value retained"},
        "stage_counts": {"annotation_rows": table.num_rows,
            "weight_rows_per_scan": manifest["weights"]["expected_rows"], "full_weight_scans": 2,
            "seed_nodes": len(seeds), "readout_nodes": len(readouts),
            "first_hop_target_ids": len(first_targets), "second_hop_source_ids": len(second_sources),
            "two_hop_overlap_ids": len(overlap), "unannotated_overlap_ids": len(overlap - annotated),
            "excluded_endpoint_overlap_ids": len(overlap & (seeds | readouts)),
            "intermediate_nodes": len(intermediates), "selected_nodes": len(selected),
            "complete_selected_source_rows": len(outgoing_rows)},
        "graph": {"cache_key": key, "relative_path": f"graphs/{key}.json", "manifest": graph["manifest"]},
        "observations_scope": "structural directed connectivity only; all induced edges retained, including edges outside the selecting two-hop paths",
        "uncertainty": "No functional, causal, sensory, steering, or robot mapping claim; absent exact types are not replaced by aliases; anatomical metadata may be missing",
    }
    metadata = {"dataset": DATASET, "source_sha256": manifest["annotations"]["sha256"],
                "extraction_commit": code_commit,
                "source_note": "Pinned official flat annotations; complete raw fields for selected graph nodes",
                "records": raw_records}
    report["source_metadata"] = {"relative_path": "source-metadata.json",
                                 "sha256": hashlib.sha256(canonical(metadata) + b"\n").hexdigest()}
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata_path.write_bytes(canonical(metadata) + b"\n")
    report_path.write_bytes(canonical(report) + b"\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--code-commit", required=True, help="Full SHA of code used for this extraction")
    parser.add_argument("--manifest", type=Path, default=ROOT / "data/manifests/pathway-source-v1.json")
    parser.add_argument("--config", type=Path, default=ROOT / "config/pathway-lc10a-dna02-v1.json")
    parser.add_argument("--download", action="store_true", help="Download missing sources and verify pinned hashes")
    args = parser.parse_args()
    report = rebuild(args.annotations, args.weights, json.loads(args.manifest.read_text()),
                     json.loads(args.config.read_text()), args.code_commit, args.output_dir,
                     download=args.download)
    print(json.dumps({"graph_cache_key": report["graph"]["cache_key"], "stage_counts": report["stage_counts"]}, sort_keys=True))


if __name__ == "__main__":
    main()
