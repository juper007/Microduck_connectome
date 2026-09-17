"""Long-step numerical stability soak helpers for P3-07."""

import math
import time

from .performance import build_matched_scale_graph
from .sparse_runtime import SparseNeuralRuntime
from .workload_identity import periodic_external, soak_workload_definition, workload_sha256


def run_soak(config, *, mode, steps=30_000, clock=time.perf_counter):
    definition = soak_workload_definition(
        timestep_ms=config["timestep_ms"],
        steps=steps,
    )
    if mode not in definition["modes"]:
        raise ValueError("mode must be zero or bounded")

    graph_spec = definition["graph"]
    graph = build_matched_scale_graph(
        node_count=graph_spec["node_count"],
        edge_count=graph_spec["edge_count"],
        normalized_weight=graph_spec["normalized_weight"],
    )
    runtime = SparseNeuralRuntime(graph, config)
    max_abs_state = 0.0
    total_spikes = 0
    start = clock()

    schedule = definition["modes"][mode]
    for step in range(definition["steps_per_mode"]):
        external = periodic_external(schedule, step)
        snapshot = runtime.step(external)
        if not snapshot["healthy"]:
            raise AssertionError("runtime became unhealthy during soak")
        for value in snapshot["state"]:
            if not math.isfinite(value):
                raise AssertionError("non-finite state during soak")
            max_abs_state = max(max_abs_state, abs(value))
        total_spikes += sum(snapshot["spikes"])

    elapsed = clock() - start
    return {
        "mode": mode,
        "steps": definition["steps_per_mode"],
        "timestep_ms": definition["timestep_ms"],
        "simulated_seconds": (
            definition["steps_per_mode"] * definition["timestep_ms"] / 1000.0
        ),
        "wall_seconds": elapsed,
        "node_count": len(graph.body_ids),
        "edge_count": len(graph.edges()),
        "healthy": runtime.healthy,
        "nonfinite_detected": False,
        "max_abs_state": max_abs_state,
        "total_spikes": total_spikes,
        "final_step_count": runtime.step_count,
        "workload_sha256": workload_sha256(definition),
    }
