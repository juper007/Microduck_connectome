"""Content-addressed cache for bounded connectivity-v1 artifacts on trusted disks."""

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from .annotations import annotations_to_json
from .connectivity import SCHEMA_VERSION, extract_connectivity


class GraphCacheError(ValueError):
    """Invalid graph, cache identity, or corrupt cache bytes."""


def _bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def _hash(value):
    return hashlib.sha256(_bytes(value)).hexdigest()


def _require(condition, message):
    if not condition:
        raise GraphCacheError(message)


def _keys(value, keys):
    _require(type(value) is dict and set(value) == set(keys), "unsupported object fields")


def _integer(value, minimum=0):
    _require(type(value) is int and value >= minimum, "invalid integer")


def _unique(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def _constant(value):
    raise GraphCacheError("nonfinite JSON number")


def _decode(data):
    return json.loads(data.decode("utf-8"), object_pairs_hook=_unique,
                      parse_constant=_constant)


def _validate(graph):
    _keys(graph, ("schema_version", "annotations", "edges", "full_outgoing_sums", "manifest"))
    _require(graph["schema_version"] == SCHEMA_VERSION, "unsupported graph schema")
    annotations = json.loads(annotations_to_json(graph["annotations"]))
    _require(_bytes(annotations) == _bytes(graph["annotations"]), "noncanonical annotations")
    manifest = graph["manifest"]
    _require(type(manifest) is dict, "manifest must be an object")
    # Reuse the extraction boundary for provenance validation and fixed statements.
    template = extract_connectivity(
        annotations, [], dataset=manifest["dataset"], source_sha256=manifest["source_sha256"],
        confidence_filter=manifest["confidence_filter"],
        extraction_commit=manifest["extraction_tool_version"], created_utc=manifest["created_utc"],
        query_or_extraction_config=manifest["query_or_extraction_config"],
        seed_populations=manifest["seed_populations"], readout_populations=manifest["readout_populations"],
        selection_rules=manifest["selection_rules"])["manifest"]
    _keys(manifest, template)
    for key in ("normalization_scope", "source_completeness", "seed_populations", "readout_populations"):
        _require(manifest[key] == template[key], f"invalid {key}")
    for key in ("node_count", "edge_count", "raw_weight_sum", "source_edge_count", "source_raw_weight_sum"):
        _integer(manifest[key])
    for key in ("source_edge_table_hash", "body_id_set_hash", "edge_table_hash",
                "annotation_artifact_hash", "full_outgoing_sums_hash"):
        _require(isinstance(manifest[key], str) and
                 re.fullmatch(r"[0-9a-f]{64}", manifest[key]) is not None, f"invalid {key}")
    nodes = {row["body_id"]: row for row in annotations["records"]}
    sums = graph["full_outgoing_sums"]
    _require(type(sums) is list and len(sums) == len(nodes), "invalid outgoing sums")
    outgoing = {}
    for body_id, row in zip(nodes, sums):
        _keys(row, ("body_id", "raw_weight_sum"))
        _integer(row["body_id"], 1)
        _require(row["body_id"] == body_id, "outgoing IDs must match ordered nodes")
        _integer(row["raw_weight_sum"])
        outgoing[body_id] = row["raw_weight_sum"]
    edges = graph["edges"]
    _require(type(edges) is list, "edges must be a list")
    previous = (0, 0)
    induced = dict.fromkeys(nodes, 0)
    for edge in edges:
        _keys(edge, ("source_body_id", "target_body_id", "raw_synapse_weight",
                     "normalized_weight", "source_type", "target_type", "provenance_dataset"))
        pre, post = edge["source_body_id"], edge["target_body_id"]
        _integer(pre, 1)
        _integer(post, 1)
        _require(pre in nodes and post in nodes, "edge endpoint missing")
        _require((pre, post) > previous, "edges must be sorted and unique")
        previous = pre, post
        weight = edge["raw_synapse_weight"]
        _integer(weight, 1)
        _require(outgoing[pre] >= weight, "outgoing denominator too small")
        normalized = edge["normalized_weight"]
        _require(type(normalized) is float and normalized > 0 and
                 normalized == weight / outgoing[pre], "invalid normalization")
        _require(edge["source_type"] == nodes[pre]["cell_type"] and
                 edge["target_type"] == nodes[post]["cell_type"] and
                 edge["provenance_dataset"] == manifest["dataset"], "edge annotation mismatch")
        induced[pre] += weight
    _require(all(induced[node] <= outgoing[node] for node in nodes), "induced sum exceeds outgoing sum")
    expected = {"node_count": len(nodes), "edge_count": len(edges),
                "raw_weight_sum": sum(induced.values()), "body_id_set_hash": _hash(list(nodes)),
                "edge_table_hash": _hash(edges), "annotation_artifact_hash": _hash(annotations),
                "full_outgoing_sums_hash": _hash(sums)}
    for key, value in expected.items():
        _require(manifest[key] == value, f"manifest {key} mismatch")
    total = sum(outgoing.values())
    count = manifest["source_edge_count"]
    weight = manifest["source_raw_weight_sum"]
    # Each positive missing selected-source remainder needs at least one source row.
    missing = sum(outgoing[node] > induced[node] for node in nodes)
    _require(count >= len(edges) + missing and weight >= total and
             weight - sum(induced.values()) >= count - len(edges),
             "inconsistent source counts")
    _require((count == 0) == (weight == 0), "inconsistent empty source")
    # If no source rows were omitted from the induced graph, recover its hash exactly.
    if count == len(edges):
        source = [{"body_pre": e["source_body_id"], "body_post": e["target_body_id"],
                   "weight": e["raw_synapse_weight"]} for e in edges]
        _require(weight == expected["raw_weight_sum"] and
                 manifest["source_edge_table_hash"] == _hash(source), "source table mismatch")


def _validated_bytes(graph):
    try:
        data = _bytes(graph)
        # Validate a JSON snapshot without mutating caller-owned containers.
        snapshot = _decode(data)
        _validate(snapshot)
        return data
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError) as error:
        raise GraphCacheError(f"invalid graph: {error}") from error


def graph_cache_key(graph):
    """Validate and hash the entire canonical graph, including all provenance."""
    return hashlib.sha256(_validated_bytes(graph)).hexdigest()


def _path(cache_dir, key):
    _require(isinstance(key, str) and re.fullmatch(r"[0-9a-f]{64}", key) is not None,
             "expected key must be 64 lowercase hex characters")
    return Path(cache_dir) / (key + ".json")


def load_graph(cache_dir, expected_key):
    """Read verified canonical bytes; missing entries raise FileNotFoundError."""
    data = _path(cache_dir, expected_key).read_bytes()
    _require(hashlib.sha256(data).hexdigest() == expected_key, "cache byte digest mismatch")
    try:
        graph = _decode(data)
        _require(_validated_bytes(graph) == data, "cache bytes are not canonical")
        return graph
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError) as error:
        raise GraphCacheError(f"invalid cached graph: {error}") from error


def store_graph(cache_dir, graph):
    """Validate and atomically publish one immutable entry; return its key.

    Existing entries are validated, never repaired silently. I/O errors propagate.
    """
    data = _validated_bytes(graph)
    key = hashlib.sha256(data).hexdigest()
    target = _path(cache_dir, key)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        load_graph(cache_dir, key)
        return key
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".graph-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        # Same-filesystem hard link publishes atomically without replacing any entry.
        try:
            os.link(temporary, target)
        except FileExistsError:
            load_graph(cache_dir, key)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return key
