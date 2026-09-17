"""Bounded graph queries; source annotations do not establish biological function.

All queries operate on the current graph/view. Source metadata is a separate,
caller-supplied envelope, not an extension of the persisted graph schema.
"""

from collections import deque
import re

from .annotations import MAX_BODY_ID


def _label(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonblank source string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError(f"{name} must be valid Unicode") from None
    return value


def _labels(values, name, *, allow_unknown=False):
    if isinstance(values, (str, bytes)):
        raise ValueError(f"{name} must be an iterable of labels, not a string")
    try:
        iterator = iter(values)
    except TypeError:
        raise ValueError(f"{name} must be an iterable of labels") from None
    result = set()
    for value in iterator:
        if value is None and allow_unknown:
            result.add(None)
        else:
            result.add(_label(value, name))
    return result


def shortest_path(graph, source_body_id, target_body_id, *, max_hops,
                  allowed_body_ids=None, allowed_types=None, min_raw_weight=1):
    """Return the lexicographically first shortest directed path, or None.

    Length means hop count, not weight cost. ``max_hops`` is required and must
    be a nonnegative integer. ``min_raw_weight`` is a positive integer inclusive
    edge threshold (no normalized-weight changes). Node and exact-type filters
    apply to ALL path nodes, including endpoints; ``None`` in allowed_types
    explicitly permits unknown types. Empty filters permit no path. Unknown or
    excluded-from-view IDs raise KeyError, malformed inputs raise ValueError.
    A permitted source == target returns a zero-hop path. BFS visits each node
    at most once; sorted neighbors break equal-length ties deterministically.
    """
    graph.node(source_body_id)
    graph.node(target_body_id)
    if type(max_hops) is not int or max_hops < 0:
        raise ValueError("max_hops must be a nonnegative integer")
    if type(min_raw_weight) is not int or min_raw_weight < 1:
        raise ValueError("min_raw_weight must be a positive integer")
    permitted = set(graph.body_ids)
    if allowed_body_ids is not None:
        if isinstance(allowed_body_ids, (str, bytes)):
            raise ValueError("allowed_body_ids must be an iterable of body IDs")
        try:
            iterator = iter(allowed_body_ids)
        except TypeError:
            raise ValueError("allowed_body_ids must be an iterable of body IDs") from None
        selected = set()
        for body_id in iterator:
            graph.node(body_id)  # Validate before deduplication (True != body ID 1).
            selected.add(body_id)
        permitted &= selected
    if allowed_types is not None:
        types = _labels(allowed_types, "allowed_types", allow_unknown=True)
        permitted &= {node["body_id"] for node in graph.nodes()
                      if node["cell_type"] in types}
    if source_body_id not in permitted or target_body_id not in permitted:
        return None
    parents = {source_body_id: None}
    pending = deque([(source_body_id, 0)])
    while pending:
        current, depth = pending.popleft()
        if current == target_body_id:
            path = []
            while current is not None:
                path.append(current)
                current = parents[current]
            return tuple(reversed(path))
        if depth == max_hops:
            continue
        for edge in sorted(graph.outgoing(current), key=lambda row: row["target_body_id"]):
            target = edge["target_body_id"]
            if (target in permitted and target not in parents
                    and edge["raw_synapse_weight"] >= min_raw_weight):
                parents[target] = current
                pending.append((target, depth + 1))
    return None


def _source_metadata(graph, envelope):
    if not isinstance(envelope, dict):
        raise ValueError("source metadata must be an envelope object")
    if set(envelope) != {"dataset", "source_sha256", "source_note", "records"}:
        raise ValueError("source metadata requires dataset/source_sha256/source_note/records")
    dataset = _label(envelope["dataset"], "dataset")
    if dataset != graph.root_manifest["dataset"]:
        raise ValueError("source metadata dataset does not match graph")
    digest = envelope["source_sha256"]
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ValueError("source_sha256 must be a lowercase SHA-256 hex digest")
    _label(envelope["source_note"], "source_note")
    if not isinstance(envelope["records"], (list, tuple)):
        raise ValueError("source metadata records must be a list or tuple")
    records = {}
    for row in envelope["records"]:
        if not isinstance(row, dict):
            raise ValueError("source metadata record must be an object")
        body_id = row.get("bodyId")
        if type(body_id) is not int or not 1 <= body_id <= MAX_BODY_ID:
            raise ValueError("source bodyId must be an integer in 1..2**63-1")
        if body_id in records:
            raise ValueError("duplicate source bodyId")
        record = {}
        for field in ("superclass", "somaNeuromere"):
            value = row.get(field)
            record[field] = None if value is None else _label(value, field)
        records[body_id] = record
    provenance = {key: envelope[key] for key in ("dataset", "source_sha256", "source_note")}
    return records, provenance


def descending_neurons(graph, source_metadata, *, superclass_labels):
    """Select exact caller-specified descending superclass labels from source.

    No default vocabulary or type-name heuristic is supplied. Missing rows or
    superclass values are returned as unknown, not as negative evidence. The
    caller must justify the meaning of the chosen source labels.
    """
    labels = _labels(superclass_labels, "superclass_labels")
    if not labels:
        raise ValueError("superclass_labels must not be empty")
    records, provenance = _source_metadata(graph, source_metadata)
    selected, unknown = [], []
    for body_id in graph.body_ids:
        value = records.get(body_id, {}).get("superclass")
        if value is None:
            unknown.append(body_id)
        elif value in labels:
            selected.append(body_id)
    return {"body_ids": tuple(selected), "unknown_body_ids": tuple(unknown),
            "superclass_labels": tuple(sorted(labels)), "source_provenance": provenance,
            "root_key": graph.root_key}


def cross_region_edges(graph, source_metadata, *, source_regions, target_regions,
                       region_field="somaNeuromere"):
    """Select directed edges between exact source anatomical label sets.

    ``region_field`` is somaNeuromere (soma regions) or superclass (source-defined
    populations). Neither establishes axonal projections or neuropil overlap.
    Brain/VNC terminology is justified only by caller-provided source evidence.
    Sets must be nonempty and disjoint; reverse direction needs another call.
    Missing selected-field metadata remains explicit. Weights and normalization are
    copied unchanged, and source metadata cannot expand a graph/view.
    """
    if region_field not in ("somaNeuromere", "superclass"):
        raise ValueError("region_field must be somaNeuromere or superclass")
    sources = _labels(source_regions, "source_regions")
    targets = _labels(target_regions, "target_regions")
    if not sources or not targets or sources & targets:
        raise ValueError("source_regions and target_regions must be nonempty and disjoint")
    records, provenance = _source_metadata(graph, source_metadata)
    source_ids, target_ids, unknown = [], [], []
    for body_id in graph.body_ids:
        value = records.get(body_id, {}).get(region_field)
        if value is None:
            unknown.append(body_id)
        elif value in sources:
            source_ids.append(body_id)
        elif value in targets:
            target_ids.append(body_id)
    source_set, target_set = set(source_ids), set(target_ids)
    edges = tuple(edge for edge in graph.edges()
                  if edge["source_body_id"] in source_set
                  and edge["target_body_id"] in target_set)
    return {"edges": edges, "source_body_ids": tuple(source_ids),
            "target_body_ids": tuple(target_ids), "unknown_body_ids": tuple(unknown),
            "source_regions": tuple(sorted(sources)), "target_regions": tuple(sorted(targets)),
            "region_field": region_field, "source_provenance": provenance,
            "root_key": graph.root_key}
