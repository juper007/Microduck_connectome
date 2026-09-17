"""Deterministic sparse CPU runtime for the frozen MVP neural model."""

import math

from .neural_model import validate_model_config


class NeuralRuntimeError(ValueError):
    """Runtime input or graph violates the P3-02 execution contract."""


class SparseNeuralRuntime:
    """Synchronous sparse LIF-like runtime keyed by MaleCNS body IDs."""

    def __init__(self, graph, config, *, max_abs_state=1_000_000.0):
        self.config = validate_model_config(config)
        if isinstance(max_abs_state, bool) or not isinstance(max_abs_state, (int, float)):
            raise NeuralRuntimeError("max_abs_state must be a finite positive number")
        self.max_abs_state = float(max_abs_state)
        if not math.isfinite(self.max_abs_state) or self.max_abs_state <= 0:
            raise NeuralRuntimeError("max_abs_state must be a finite positive number")

        try:
            body_ids = tuple(graph.body_ids)
        except Exception as error:
            raise NeuralRuntimeError("graph must expose body_ids") from error
        if not body_ids:
            raise NeuralRuntimeError("graph must contain at least one neuron")
        if tuple(sorted(body_ids)) != body_ids or len(set(body_ids)) != len(body_ids):
            raise NeuralRuntimeError("graph body_ids must be unique and ascending integers")
        for body_id in body_ids:
            if type(body_id) is not int or body_id <= 0:
                raise NeuralRuntimeError("graph body_ids must be positive integers")

        self.body_ids = body_ids
        self._index = {body_id: index for index, body_id in enumerate(body_ids)}
        self._incoming = [[] for _ in body_ids]
        try:
            edges = tuple(graph.edges())
        except Exception as error:
            raise NeuralRuntimeError("graph must expose edges()") from error
        seen = set()
        for edge in edges:
            try:
                source = edge["source_body_id"]
                target = edge["target_body_id"]
                weight = edge["normalized_weight"]
            except (KeyError, TypeError) as error:
                raise NeuralRuntimeError("edge missing source/target/normalized_weight") from error
            if source not in self._index or target not in self._index:
                raise NeuralRuntimeError("edge endpoint is absent from graph body_ids")
            identity = (source, target)
            if identity in seen:
                raise NeuralRuntimeError("duplicate directed edge")
            seen.add(identity)
            if isinstance(weight, bool) or not isinstance(weight, (int, float)):
                raise NeuralRuntimeError("normalized_weight must be a finite non-negative number")
            weight = float(weight)
            if not math.isfinite(weight) or weight < 0:
                raise NeuralRuntimeError("normalized_weight must be a finite non-negative number")
            self._incoming[self._index[target]].append((self._index[source], weight))
        for incoming in self._incoming:
            incoming.sort()
        self.reset()

    @property
    def healthy(self):
        return self._healthy

    @property
    def step_count(self):
        return self._step_count

    def reset(self):
        self._state = [0.0] * len(self.body_ids)
        self._spikes = [False] * len(self.body_ids)
        self._healthy = True
        self._step_count = 0

    def state(self):
        return tuple(self._state)

    def spikes(self):
        return tuple(self._spikes)

    def snapshot(self):
        return {
            "body_ids": self.body_ids,
            "state": self.state(),
            "spikes": self.spikes(),
            "healthy": self.healthy,
            "step_count": self.step_count,
        }

    def _fail(self, message):
        self._healthy = False
        raise NeuralRuntimeError(message)

    def step(self, external=None):
        if not self._healthy:
            raise NeuralRuntimeError("runtime is unhealthy; reset required")
        if external is None:
            external = {}
        if not hasattr(external, "items"):
            self._fail("external input must be a mapping")
        injected = [0.0] * len(self.body_ids)
        try:
            items = external.items()
        except Exception:
            self._fail("external input must be a mapping")
        for body_id, value in items:
            if body_id not in self._index:
                self._fail("external input references unknown body_id")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                self._fail("external input must be finite numeric values")
            value = float(value)
            if not math.isfinite(value):
                self._fail("external input must be finite numeric values")
            injected[self._index[body_id]] = value

        alpha = self.config["alpha"]
        threshold = self.config["threshold"]
        reset_value = self.config["reset_value"]
        recurrent_gain = self.config["recurrent_gain"]
        previous_state = self._state
        previous_spikes = self._spikes

        candidate = [0.0] * len(self.body_ids)
        next_spikes = [False] * len(self.body_ids)
        next_state = [0.0] * len(self.body_ids)
        try:
            for target_index, incoming in enumerate(self._incoming):
                recurrent = 0.0
                for source_index, weight in incoming:
                    if previous_spikes[source_index]:
                        recurrent += weight
                value = (
                    alpha * previous_state[target_index]
                    + injected[target_index]
                    + recurrent_gain * recurrent
                )
                if not math.isfinite(value) or abs(value) > self.max_abs_state:
                    self._fail("non-finite or excessive neural state")
                candidate[target_index] = value
            for index, value in enumerate(candidate):
                spiked = value >= threshold
                next_spikes[index] = spiked
                next_state[index] = reset_value if spiked else value
        except OverflowError:
            self._fail("neural state overflow")

        self._state = next_state
        self._spikes = next_spikes
        self._step_count += 1
        return self.snapshot()
