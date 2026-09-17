"""Long-step numerical stability soak helpers for P3-07."""

import math
import time

from .performance import build_matched_scale_graph
from .sparse_runtime import SparseNeuralRuntime


def run_soak(config, *, mode, steps=30_000, clock=time.perf_counter):
    if mode not in ("zero", "bounded"):
        raise ValueError("mode must be zero or bounded")
    if type(steps) is not int or steps <= 0:
        raise ValueError("steps must be a positive integer")

    graph = build_matched_scale_graph()
    runtime = SparseNeuralRuntime(graph, config)
    max_abs_state = 0.0
    total_spikes = 0
    start = clock()

    for step in range(steps):
        if mode == "bounded" and step % 10 == 0:
            external = {1: 1.0, 200: 0.75}
        else:
            external = {}
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
        "steps": steps,
        "timestep_ms": config["timestep_ms"],
        "simulated_seconds": steps * config["timestep_ms"] / 1000.0,
        "wall_seconds": elapsed,
        "node_count": len(graph.body_ids),
        "edge_count": len(graph.edges()),
        "healthy": runtime.healthy,
        "nonfinite_detected": False,
        "max_abs_state": max_abs_state,
        "total_spikes": total_spikes,
        "final_step_count": runtime.step_count,
    }
