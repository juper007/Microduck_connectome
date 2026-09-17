"""Deterministic matched-scale performance and memory helpers for P3-06."""

import math
from pathlib import Path
import time

from .sparse_runtime import SparseNeuralRuntime
from .workload_identity import (
    graph_workload_definition,
    matched_scale_graph_fixture,
    performance_workload_definition,
    periodic_external,
    workload_sha256,
)


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


def read_linux_process_memory(status_path="/proc/self/status"):
    """Return current/peak process RSS from Linux procfs in bytes."""
    values = {}
    try:
        lines = Path(status_path).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise RuntimeError("cannot read Linux process memory status") from error
    for line in lines:
        if ":" not in line:
            continue
        name, raw = line.split(":", 1)
        if name not in ("VmRSS", "VmHWM"):
            continue
        parts = raw.split()
        if len(parts) != 2 or parts[1] != "kB":
            raise RuntimeError(f"{name} must be reported in kB")
        try:
            values[name] = int(parts[0]) * 1024
        except ValueError as error:
            raise RuntimeError(f"{name} is not an integer") from error
    if set(values) != {"VmRSS", "VmHWM"}:
        raise RuntimeError("Linux process memory status lacks VmRSS/VmHWM")
    return {
        "measurement_method": "linux-proc-status-vmrss-vmhwm",
        "rss_bytes": values["VmRSS"],
        "peak_rss_bytes": values["VmHWM"],
    }


def build_matched_scale_graph(node_count=570, edge_count=21142, normalized_weight=0.01):
    """Return a deterministic synthetic graph matching the selected G1 graph scale."""
    definition = graph_workload_definition(
        node_count=node_count,
        edge_count=edge_count,
        normalized_weight=normalized_weight,
    )

    fixture = matched_scale_graph_fixture(
        node_count=definition["node_count"],
        edge_count=definition["edge_count"],
        normalized_weight=definition["normalized_weight"],
    )

    class SyntheticGraph:
        pass

    graph = SyntheticGraph()
    graph.body_ids = tuple(fixture["body_ids"])
    graph._edges = tuple(fixture["edges"])
    graph.edges = lambda: graph._edges
    return graph


def _validate_memory_sample(sample):
    if not isinstance(sample, dict):
        raise ValueError("memory reader must return a dict")
    required = {"measurement_method", "rss_bytes", "peak_rss_bytes"}
    if set(sample) != required:
        raise ValueError("memory reader returned unexpected fields")
    if not isinstance(sample["measurement_method"], str) or not sample["measurement_method"]:
        raise ValueError("memory measurement_method must be a nonblank string")
    for key in ("rss_bytes", "peak_rss_bytes"):
        if type(sample[key]) is not int or sample[key] < 0:
            raise ValueError(f"{key} must be a non-negative integer")
    if sample["peak_rss_bytes"] < sample["rss_bytes"]:
        raise ValueError("peak_rss_bytes must be >= rss_bytes")
    return sample


def profile_runtime(
    config,
    *,
    warmup_steps=100,
    measured_steps=500,
    clock_ns=time.perf_counter_ns,
    memory_reader=None,
):
    definition = performance_workload_definition(
        warmup_steps=warmup_steps,
        measured_steps=measured_steps,
    )
    if memory_reader is None:
        memory_reader = read_linux_process_memory

    baseline_memory = _validate_memory_sample(memory_reader())
    graph_spec = definition["graph"]
    graph = build_matched_scale_graph(
        node_count=graph_spec["node_count"],
        edge_count=graph_spec["edge_count"],
        normalized_weight=graph_spec["normalized_weight"],
    )
    runtime = SparseNeuralRuntime(graph, config)
    constructed_memory = _validate_memory_sample(memory_reader())
    if constructed_memory["measurement_method"] != baseline_memory["measurement_method"]:
        raise ValueError("memory measurement method changed during profile")

    warmup_schedule = definition["warmup_stimulus"]
    for step in range(definition["warmup_steps"]):
        runtime.step(periodic_external(warmup_schedule, step))

    latencies = []
    measured_schedule = definition["measured_stimulus"]
    for step in range(definition["measured_steps"]):
        external = periodic_external(measured_schedule, step)
        start = clock_ns()
        runtime.step(external)
        end = clock_ns()
        if end < start:
            raise ValueError("clock_ns must be monotonic")
        latencies.append(end - start)

    final_memory = _validate_memory_sample(memory_reader())
    if final_memory["measurement_method"] != baseline_memory["measurement_method"]:
        raise ValueError("memory measurement method changed during profile")

    p95_ns = percentile_nearest_rank(latencies, 0.95)
    return {
        "node_count": graph_spec["node_count"],
        "edge_count": graph_spec["edge_count"],
        "warmup_steps": definition["warmup_steps"],
        "measured_steps": definition["measured_steps"],
        "p50_ms": percentile_nearest_rank(latencies, 0.50) / 1_000_000.0,
        "p95_ms": p95_ns / 1_000_000.0,
        "p99_ms": percentile_nearest_rank(latencies, 0.99) / 1_000_000.0,
        "min_ms": min(latencies) / 1_000_000.0,
        "max_ms": max(latencies) / 1_000_000.0,
        "preferred_p95_target_ms": 18.0,
        "preferred_p95_target_met": p95_ns <= 18_000_000,
        "memory_measurement_method": baseline_memory["measurement_method"],
        "baseline_rss_bytes": baseline_memory["rss_bytes"],
        "runtime_constructed_rss_bytes": constructed_memory["rss_bytes"],
        "post_profile_rss_bytes": final_memory["rss_bytes"],
        "peak_rss_bytes": max(
            baseline_memory["peak_rss_bytes"],
            constructed_memory["peak_rss_bytes"],
            final_memory["peak_rss_bytes"],
        ),
        "runtime_rss_delta_bytes": (
            constructed_memory["rss_bytes"] - baseline_memory["rss_bytes"]
        ),
        "workload_definition": definition,
        "workload_sha256": workload_sha256(definition),
    }
