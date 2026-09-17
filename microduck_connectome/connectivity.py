"""Bounded, offline induced edges with full-source outgoing normalization."""

from collections.abc import Mapping
from datetime import datetime
import hashlib
import json
import re

from .annotations import AnnotationError, MAX_BODY_ID, annotations_to_json
from .neuprint_client import DATASET

SCHEMA_VERSION = "connectivity-v1"
SOURCE_FIELDS = frozenset(("body_pre", "body_post", "weight"))


class ConnectivityError(ValueError):
    """An input violates the connectivity extraction contract."""


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def _hash(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ConnectivityError(f"{label} must be a nonblank Unicode string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ConnectivityError(f"{label} must be valid Unicode") from None
    return value


def _hex(value, length, label):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{" + str(length) + "}", value):
        raise ConnectivityError(f"{label} must be {length} lowercase hexadecimal characters")


def _names(value, label):
    if not isinstance(value, (list, tuple)):
        raise ConnectivityError(f"{label} must be a list or tuple")
    names = [_text(name, label) for name in value]
    if len(set(names)) != len(names):
        raise ConnectivityError(f"{label} contains duplicate names")
    return sorted(names)


def extract_connectivity(annotation_artifact, rows, *, dataset, source_sha256,
                         confidence_filter, extraction_commit, created_utc,
                         query_or_extraction_config, seed_populations,
                         readout_populations, selection_rules):
    """Return fresh deterministic graph data from explicit source rows.

    The annotation artifact defines selected nodes. The caller MUST supply all
    retained-confidence outgoing rows for these sources, including external
    targets without annotations. Completeness and provenance cannot be verified
    here. No confidence/weight filtering is applied by this function.
    """
    if dataset != DATASET:
        raise ConnectivityError(f"dataset must be {DATASET}")
    _hex(source_sha256, 64, "source_sha256")
    _hex(extraction_commit, 40, "extraction_commit")
    for label, value in (("confidence_filter", confidence_filter),
                         ("query_or_extraction_config", query_or_extraction_config),
                         ("selection_rules", selection_rules)):
        _text(value, label)
    if not isinstance(created_utc, str) or not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", created_utc):
        raise ConnectivityError("created_utc must be YYYY-MM-DDTHH:MM:SSZ")
    try:
        datetime.strptime(created_utc, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        raise ConnectivityError("created_utc must be a valid UTC date/time") from None
    seeds = _names(seed_populations, "seed_populations")
    readouts = _names(readout_populations, "readout_populations")
    try:
        annotations = json.loads(annotations_to_json(annotation_artifact))
    except AnnotationError as error:
        raise ConnectivityError(f"invalid annotation artifact: {error}") from error
    if not isinstance(rows, (list, tuple)):
        raise ConnectivityError("rows must be a list or tuple")
    nodes = {record["body_id"]: record for record in annotations["records"]}
    outgoing = dict.fromkeys(nodes, 0)
    source_rows = []
    seen = set()
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or set(row) != SOURCE_FIELDS:
            raise ConnectivityError(f"row {index} must have exactly body_pre, body_post, weight")
        for key in ("body_pre", "body_post"):
            if type(row[key]) is not int or not 1 <= row[key] <= MAX_BODY_ID:
                raise ConnectivityError(f"row {index}.{key} must be an integer in 1..2**63-1")
        weight = row["weight"]
        if type(weight) is not int or weight <= 0:
            raise ConnectivityError(f"row {index}.weight must be a positive integer")
        identity = row["body_pre"], row["body_post"]
        if identity in seen:
            raise ConnectivityError(f"row {index} duplicates an edge identity")
        seen.add(identity)
        source_rows.append(dict(row))
        if row["body_pre"] in outgoing:
            outgoing[row["body_pre"]] += weight
    source_rows.sort(key=lambda row: (row["body_pre"], row["body_post"]))
    edges = []
    for row in source_rows:
        pre, post, weight = row["body_pre"], row["body_post"], row["weight"]
        if pre in nodes and post in nodes:
            normalized = weight / outgoing[pre]
            if normalized == 0:
                raise ConnectivityError("normalized weight underflows float representation")
            edges.append({"source_body_id": pre, "target_body_id": post,
                          "raw_synapse_weight": weight, "normalized_weight": normalized,
                          "source_type": nodes[pre]["cell_type"],
                          "target_type": nodes[post]["cell_type"],
                          "provenance_dataset": DATASET})
    sums = [{"body_id": body_id, "raw_weight_sum": total}
            for body_id, total in outgoing.items()]
    manifest = {
        "dataset": DATASET, "extraction_tool_version": extraction_commit,
        "query_or_extraction_config": query_or_extraction_config,
        "created_utc": created_utc, "source_sha256": source_sha256,
        "confidence_filter": confidence_filter,
        "normalization_scope": "all retained-confidence source outgoing edges before target selection",
        "source_completeness": "caller assertion; not independently verified",
        "seed_populations": seeds, "readout_populations": readouts,
        "selection_rules": selection_rules,
        "node_count": len(nodes), "edge_count": len(edges),
        "raw_weight_sum": sum(edge["raw_synapse_weight"] for edge in edges),
        "body_id_set_hash": _hash(list(nodes)), "edge_table_hash": _hash(edges),
        "annotation_artifact_hash": _hash(annotations),
        "source_edge_count": len(source_rows),
        "source_raw_weight_sum": sum(row["weight"] for row in source_rows),
        "source_edge_table_hash": _hash(source_rows),
        "full_outgoing_sums_hash": _hash(sums),
    }
    return {"schema_version": SCHEMA_VERSION, "annotations": annotations,
            "edges": edges, "full_outgoing_sums": sums, "manifest": manifest}
