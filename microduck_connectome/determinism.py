"""Deterministic replay evidence helpers for P3-05."""

import hashlib
import json
from collections.abc import Sequence

from .sparse_runtime import SparseNeuralRuntime


class DeterminismError(AssertionError):
    """Fixed replay produced different exact snapshots."""


def _canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def replay_trace(graph, config, trace):
    if not isinstance(trace, Sequence) or isinstance(trace, (str, bytes)):
        raise TypeError("trace must be a sequence of external-input mappings")
    runtime = SparseNeuralRuntime(graph, config)
    return [runtime.step(external) for external in trace]


def trace_sha256(snapshots):
    return hashlib.sha256(_canonical_json(snapshots).encode("utf-8")).hexdigest()


def verify_fixed_replay(graph, config, trace):
    first = replay_trace(graph, config, trace)
    second = replay_trace(graph, config, trace)
    first_hash = trace_sha256(first)
    second_hash = trace_sha256(second)
    if first != second or first_hash != second_hash:
        raise DeterminismError("fixed replay differs")
    return {
        "steps": len(first),
        "body_ids": list(first[-1]["body_ids"]) if first else list(graph.body_ids),
        "trace_sha256": first_hash,
        "exact_replay_equal": True,
    }
