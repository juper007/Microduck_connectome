"""Canonical executable workload identities for Phase 3 performance/soak evidence."""

import hashlib
import json
import math

DEFAULT_NODE_COUNT = 570
DEFAULT_EDGE_COUNT = 21_142
DEFAULT_NORMALIZED_WEIGHT = 0.01
GRAPH_GENERATION_RULE = "round_robin_offset_unique_directed_nonself-v1"


def _canonical_json(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def workload_sha256(definition):
    return hashlib.sha256(_canonical_json(definition).encode("utf-8")).hexdigest()


def _validated_graph_params(node_count, edge_count, normalized_weight):
    if type(node_count) is not int or node_count < 2:
        raise ValueError("node_count must be an integer >= 2")
    max_edges = node_count * (node_count - 1)
    if type(edge_count) is not int or not 0 <= edge_count <= max_edges:
        raise ValueError("edge_count exceeds unique directed non-self edges")
    if isinstance(normalized_weight, bool) or not isinstance(normalized_weight, (int, float)):
        raise ValueError("normalized_weight must be numeric")
    normalized_weight = float(normalized_weight)
    if not math.isfinite(normalized_weight) or normalized_weight < 0:
        raise ValueError("normalized_weight must be finite and non-negative")
    return node_count, edge_count, normalized_weight


def matched_scale_graph_fixture(
    *,
    node_count=DEFAULT_NODE_COUNT,
    edge_count=DEFAULT_EDGE_COUNT,
    normalized_weight=DEFAULT_NORMALIZED_WEIGHT,
):
    """Return the exact deterministic synthetic graph content used by P3 workloads."""
    node_count, edge_count, normalized_weight = _validated_graph_params(
        node_count, edge_count, normalized_weight
    )
    body_ids = list(range(1, node_count + 1))
    edges = []
    source = 1
    offset = 1
    while len(edges) < edge_count:
        target = ((source - 1 + offset) % node_count) + 1
        if target != source:
            edges.append({
                "source_body_id": source,
                "target_body_id": target,
                "normalized_weight": normalized_weight,
            })
        source += 1
        if source > node_count:
            source = 1
            offset += 1
    return {"body_ids": body_ids, "edges": edges}


def graph_workload_definition(
    *,
    node_count=DEFAULT_NODE_COUNT,
    edge_count=DEFAULT_EDGE_COUNT,
    normalized_weight=DEFAULT_NORMALIZED_WEIGHT,
):
    node_count, edge_count, normalized_weight = _validated_graph_params(
        node_count, edge_count, normalized_weight
    )
    fixture = matched_scale_graph_fixture(
        node_count=node_count,
        edge_count=edge_count,
        normalized_weight=normalized_weight,
    )
    return {
        "node_count": node_count,
        "edge_count": edge_count,
        "normalized_weight": normalized_weight,
        "generation_rule": GRAPH_GENERATION_RULE,
        "fixture_sha256": workload_sha256(fixture),
    }


def performance_workload_definition(*, warmup_steps=100, measured_steps=500):
    if type(warmup_steps) is not int or warmup_steps < 0:
        raise ValueError("warmup_steps must be a non-negative integer")
    if type(measured_steps) is not int or measured_steps <= 0:
        raise ValueError("measured_steps must be a positive integer")
    return {
        "schema_version": "p3-06-workload-v2",
        "fixture_kind": "synthetic_matched_scale",
        "graph": graph_workload_definition(),
        "warmup_steps": warmup_steps,
        "measured_steps": measured_steps,
        "warmup_stimulus": {
            "period_steps": 10,
            "external": {"1": 0.5},
        },
        "measured_stimulus": {
            "period_steps": 10,
            "external": {"1": 0.5, "200": 0.25},
        },
    }


def soak_workload_definition(*, timestep_ms=20, steps=30_000):
    if type(timestep_ms) is not int or timestep_ms <= 0:
        raise ValueError("timestep_ms must be a positive integer")
    if type(steps) is not int or steps <= 0:
        raise ValueError("steps must be a positive integer")
    return {
        "schema_version": "p3-07-workload-v2",
        "fixture_kind": "synthetic_matched_scale",
        "graph": graph_workload_definition(),
        "timestep_ms": timestep_ms,
        "steps_per_mode": steps,
        "modes": {
            "zero": {"external": {}},
            "bounded": {
                "period_steps": 10,
                "external": {"1": 1.0, "200": 0.75},
            },
        },
    }


def periodic_external(schedule, step):
    """Return int-keyed external input for one periodic schedule step."""
    period = schedule.get("period_steps")
    external = schedule.get("external")
    if period is None:
        return {}
    if type(period) is not int or period <= 0:
        raise ValueError("period_steps must be a positive integer")
    if step % period:
        return {}
    return {int(body_id): amplitude for body_id, amplitude in external.items()}
