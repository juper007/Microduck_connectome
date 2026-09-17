"""Verify a rebuilt pathway report and produce deterministic bounded query evidence."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import re

from .graph import ConnectomeGraph
from .pathway_queries import cross_region_edges, descending_neurons, shortest_path


def _relative_file(base, value):
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("artifact paths must be nonempty portable relative paths")
    relative = PurePosixPath(value)
    if (relative.is_absolute() or PureWindowsPath(value).drive
            or any(part in (".", "..", "") for part in value.split("/"))):
        raise ValueError("artifact paths must stay below the report directory")
    path = (base / value).resolve()
    if not path.is_relative_to(base):
        raise ValueError("artifact path escapes report directory")
    return path


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def _load(data):
    def object_pairs(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError(f"duplicate JSON key: {key}")
            obj[key] = value
        return obj

    def invalid_constant(value):
        raise ValueError(f"invalid JSON constant: {value}")

    return json.loads(data, object_pairs_hook=object_pairs, parse_constant=invalid_constant)


def query_report(report_path, *, code_commit):
    """Read verified adjacent artifacts; return a deterministic JSON-ready report.

    Hashes establish consistency with the supplied extraction report, not an
    independent signature. The source extraction/rebuild verifies raw sources.
    """
    if not isinstance(code_commit, str) or re.fullmatch(r"[0-9a-f]{40}", code_commit) is None:
        raise ValueError("code_commit must be a full lowercase 40-character Git SHA")
    report_path = Path(report_path).resolve()
    report_bytes = report_path.read_bytes()
    report = _load(report_bytes)
    if report["schema_version"] != "pathway-report-v1":
        raise ValueError("unsupported pathway report schema")
    graph_info = report["graph"]
    graph_path = _relative_file(report_path.parent, graph_info["relative_path"])
    if graph_path.name != graph_info["cache_key"] + ".json":
        raise ValueError("graph path must name the expected graph cache key")
    graph = ConnectomeGraph.from_cache(graph_path.parent, graph_info["cache_key"])
    if (graph.root_manifest != graph_info["manifest"]
            or list(graph.body_ids) != report["selected_body_ids"]
            or graph.root_manifest["dataset"] != report["dataset"]):
        raise ValueError("report graph manifest, selected IDs or dataset mismatch")
    metadata_info = report["source_metadata"]
    metadata_path = _relative_file(report_path.parent, metadata_info["relative_path"])
    metadata_bytes = metadata_path.read_bytes()
    if _digest(metadata_bytes) != metadata_info["sha256"]:
        raise ValueError("source metadata file SHA-256 mismatch")
    metadata = _load(metadata_bytes)
    manifest = report["source_manifest"]
    config = report["selection_config"]
    if (_digest(_canonical(manifest)) != report["source_manifest_sha256"]
            or _digest(_canonical(config)) != report["selection_config_sha256"]):
        raise ValueError("source manifest or selection configuration SHA-256 mismatch")
    if (graph.root_manifest["source_sha256"] != manifest["weights"]["sha256"]
            or graph.root_manifest["extraction_tool_version"] != report["code_commit"]
            or graph.root_manifest["query_or_extraction_config"] != _canonical(config).decode()):
        raise ValueError("graph source, extraction code or selection configuration mismatch")
    if (metadata["source_sha256"] != manifest["annotations"]["sha256"]
            or metadata["extraction_commit"] != report["code_commit"]
            or metadata["records"] != report["source_annotation_records"]
            or metadata["dataset"] != report["dataset"]):
        raise ValueError("metadata provenance or records mismatch with extraction report")
    # This also validates all source body IDs/labels, including duplicate records.
    descending = descending_neurons(graph, metadata, superclass_labels=["descending_neuron"])
    if sorted(row["bodyId"] for row in metadata["records"]) != list(graph.body_ids):
        raise ValueError("rebuilt metadata must cover exactly the selected graph nodes")
    seeds = graph.select_type(config["seed_type"])
    readouts = graph.select_type(config["readout_type"])
    if not seeds or not readouts:
        raise ValueError("selected graph lacks the configured seed or readout population")
    pairs = []
    two_hop_paths = []
    for seed in seeds:
        for readout in readouts:
            path = shortest_path(graph, seed, readout, max_hops=2)
            pairs.append({"source_body_id": seed, "target_body_id": readout,
                          "shortest_path": None if path is None else list(path)})
            # Count simple two-edge paths, even when a direct path also exists.
            for first in graph.outgoing(seed):
                middle = first["target_body_id"]
                if len({seed, middle, readout}) == 3 and graph.edge(middle, readout) is not None:
                    two_hop_paths.append([seed, middle, readout])
    cross = {}
    for source, target in (("cb_intrinsic", "vnc_intrinsic"), ("vnc_intrinsic", "cb_intrinsic")):
        result = cross_region_edges(graph, metadata, region_field="superclass",
                                    source_regions=[source], target_regions=[target])
        result["edge_count"] = len(result["edges"])
        cross[f"{source}_to_{target}"] = result
    soma_counts = Counter(row.get("somaNeuromere") for row in metadata["records"])
    soma_unknown = sorted(row["bodyId"] for row in metadata["records"]
                          if row.get("somaNeuromere") is None)
    return {
        "schema_version": "pathway-query-report-v1", "dataset": report["dataset"],
        "query_code_commit": code_commit, "extraction_code_commit": report["code_commit"],
        "input_report_sha256": _digest(report_bytes), "root_key": graph.root_key,
        "metadata_file_sha256": metadata_info["sha256"],
        "source_provenance": descending["source_provenance"],
        "path_query": {"max_hops": 2, "min_raw_weight": 1, "seed_type": config["seed_type"],
                       "readout_type": config["readout_type"], "seed_body_ids": list(seeds),
                       "readout_body_ids": list(readouts), "pairs": pairs,
                       "reachable_pair_count": sum(row["shortest_path"] is not None for row in pairs),
                       "two_hop_scope": "All simple two-edge paths in selected induced graph; intermediate may be another seed/readout.",
                       "simple_two_hop_path_count": len(two_hop_paths),
                       "simple_two_hop_paths": sorted(two_hop_paths)},
        "descending": descending, "cross_superclass": cross,
        "soma_neuromere_coverage": {
            "known_count": len(graph.body_ids) - len(soma_unknown),
            "unknown_count": len(soma_unknown), "unknown_body_ids": soma_unknown,
            "known_source_label_counts": {label: soma_counts[label]
                                          for label in sorted(key for key in soma_counts if key is not None)}},
        "scope": "Only the selected induced graph; zero matches do not establish absence in the full source graph.",
        "limitations": [
            "Superclass queries cover exact cb_intrinsic/vnc_intrinsic source populations, not all brain/VNC neurons.",
            "Soma labels indicate soma location; missing labels do not imply brain location or axonal projection.",
            "Structural paths do not establish functional, causal or robot mappings.",
            "Report and metadata hashes check consistency; independent source rebuild is required for source verification.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--code-commit", required=True, help="Full Git SHA of the query code")
    args = parser.parse_args()
    result = query_report(args.report, code_commit=args.code_commit)
    # Do not replace source artifacts with derived query evidence.
    report = _load(args.report.read_bytes())
    base = args.report.resolve().parent
    inputs = {args.report.resolve(), _relative_file(base, report["graph"]["relative_path"]),
              _relative_file(base, report["source_metadata"]["relative_path"])}
    if args.output.resolve() in inputs:
        raise ValueError("output must not overwrite a report input artifact")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(_canonical(result) + b"\n")
    print(json.dumps({"root_key": result["root_key"],
                      "reachable_pair_count": result["path_query"]["reachable_pair_count"],
                      "simple_two_hop_path_count": result["path_query"]["simple_two_hop_path_count"]},
                     sort_keys=True))


if __name__ == "__main__":
    main()
