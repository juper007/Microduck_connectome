"""Deterministic rolling population spike readout for P3-04."""

from collections import deque
from collections.abc import Mapping, Sequence


class PopulationReadoutError(ValueError):
    """Readout configuration or update violates the P3-04 contract."""


class PopulationReadout:
    """Rolling spike-count-per-neuron then population-mean aggregation."""

    def __init__(self, body_ids, populations, *, timestep_ms=20, window_ms=100):
        body_ids = tuple(body_ids)
        if not body_ids or tuple(sorted(body_ids)) != body_ids or len(set(body_ids)) != len(body_ids):
            raise PopulationReadoutError("body_ids must be non-empty, unique and ascending")
        if type(timestep_ms) is not int or timestep_ms <= 0:
            raise PopulationReadoutError("timestep_ms must be a positive integer")
        if type(window_ms) is not int or window_ms <= 0 or window_ms % timestep_ms:
            raise PopulationReadoutError("window_ms must be a positive exact multiple of timestep_ms")
        if not isinstance(populations, Mapping) or not populations:
            raise PopulationReadoutError("populations must be a non-empty mapping")
        index = {body_id: i for i, body_id in enumerate(body_ids)}
        normalized = {}
        names = list(populations)
        for name in names:
            if not isinstance(name, str) or not name.strip():
                raise PopulationReadoutError("population names must be nonblank strings")
        for name in sorted(names):
            members = populations[name]
            if not isinstance(members, Sequence) or isinstance(members, (str, bytes)):
                raise PopulationReadoutError("population members must be a sequence")
            members = tuple(members)
            if not members or tuple(sorted(members)) != members or len(set(members)) != len(members):
                raise PopulationReadoutError("population members must be non-empty unique ascending IDs")
            try:
                normalized[name] = tuple(index[body_id] for body_id in members)
            except (KeyError, TypeError):
                raise PopulationReadoutError("population references unknown body_id") from None
        self.body_ids = body_ids
        self.timestep_ms = timestep_ms
        self.window_ms = window_ms
        self.window_steps = window_ms // timestep_ms
        self._populations = normalized
        self._history = deque(maxlen=self.window_steps)

    @classmethod
    def from_graph_types(cls, graph, cell_types, *, timestep_ms=20, window_ms=100):
        if not isinstance(cell_types, Sequence) or isinstance(cell_types, (str, bytes)) or not cell_types:
            raise PopulationReadoutError("cell_types must be a non-empty sequence")
        populations = {}
        for cell_type in cell_types:
            if not isinstance(cell_type, str) or not cell_type.strip():
                raise PopulationReadoutError("cell_types must contain nonblank strings")
            members = tuple(graph.select_type(cell_type))
            if not members:
                raise PopulationReadoutError(f"cell type {cell_type!r} selects no neurons")
            populations[cell_type] = members
        return cls(graph.body_ids, populations, timestep_ms=timestep_ms, window_ms=window_ms)

    def reset(self):
        self._history.clear()

    @property
    def samples(self):
        return len(self._history)

    def update(self, spikes):
        if not isinstance(spikes, Sequence) or isinstance(spikes, (str, bytes)):
            raise PopulationReadoutError("spikes must be a sequence")
        spikes = tuple(spikes)
        if len(spikes) != len(self.body_ids) or any(type(value) is not bool for value in spikes):
            raise PopulationReadoutError("spikes must be bools aligned exactly to body_ids")
        self._history.append(spikes)
        return self.values()

    def values(self):
        result = {}
        for name, indices in self._populations.items():
            if not self._history:
                result[name] = 0.0
                continue
            per_neuron_counts = [
                sum(1 for sample in self._history if sample[index])
                for index in indices
            ]
            result[name] = sum(per_neuron_counts) / len(indices)
        return result

    def population_specs(self):
        return {
            name: [self.body_ids[index] for index in indices]
            for name, indices in self._populations.items()
        }
