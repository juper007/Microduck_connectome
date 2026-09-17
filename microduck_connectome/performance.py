"""Deterministic matched-scale performance helpers for P3-06."""

import math
import time

from .sparse_runtime import SparseNeuralRuntime


def percentile_nearest_rank(values_ns, percentile):
    values = sorted(values_ns)
    if not values:
        raise ValueError("values_ns must be non-empty")
    if isinstance(percentile, bool) or not isinstance(percentile, (int, float)):
        raise ValueError("percentile must be numeric")
    percentile = float(percentile)
    if not 0.0 < percentile <= 1.0:
        raise ValueError("percentile must be in (0, 1]")
    return values[max(0, math.ceil(percentile * len(values)) - 1)]


def build_matched_scale_graph(node_count=570, edge_count=21142, normalized_weight=0.01):
    """Return a deterministic synthetic graph matching the selected G1 graph scale."""
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

    class SyntheticGraph:
        pass

    graph = SyntheticGraph()
    graph.body_ids = tuple(range(1, node_count + 1))
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
    graph._edges = tuple(edges)
    graph.edges = lambda: graph._edges
    return graph


def profile_runtime(config, *, warmup_steps=100, measured_steps=500, clock_ns=time.perf_counter_ns):
    if type(warmup_steps) is not int or warmup_steps < 0:
        raise ValueError("warmup_steps must be a non-negative integer")
    if type(measured_steps) is not int or measured_steps <= 0:
        raise ValueError("measured_steps must be a positive integer")
    graph = build_matched_scale_graph()
    runtime = SparseNeuralRuntime(graph, config)
    for step in range(warmup_steps):
        runtime.step({1: 0.5} if step % 10 == 0 else {})

    latencies = []
    for step in range(measured_steps):
        external = {1: 0.5, 200: 0.25} if step % 10 == 0 else {}
        start = clock_ns()
        runtime.step(external)
        end = clock_ns()
        if end < start:
            raise ValueError("clock_ns must be monotonic")
        latencies.append(end - start)

    return {
        "node_count": 570,
        "edge_count": 21142,
        "warmup_steps": warmup_steps,
        "measured_steps": measured_steps,
        "p50_ms": percentile_nearest_rank(latencies, 0.50) / 1_000_000.0,
        "p95_ms": percentile_nearest_rank(latencies, 0.95) / 1_000_000.0,
        "p99_ms": percentile_nearest_rank(latencies, 0.99) / 1_000_000.0,
        "min_ms": min(latencies) / 1_000_000.0,
        "max_ms": max(latencies) / 1_000_000.0,
        "preferred_p95_target_ms": 18.0,
        "preferred_p95_target_met": percentile_nearest_rank(latencies, 0.95) <= 18_000_000,
    }
