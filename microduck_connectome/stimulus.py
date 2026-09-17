"""Bounded population-to-neuron stimulus adapter for P3-03."""

import math
from collections.abc import Mapping, Sequence

_VALID_SIDES = frozenset(("L", "R", "M"))


class StimulusConfigError(ValueError):
    """Population configuration violates the P3-03 contract."""


class StimulusInputError(ValueError):
    """A stimulus request violates the bounded injection contract."""


class StimulusInjector:
    """Map named bounded population amplitudes to body-ID external inputs."""

    def __init__(self, body_ids, populations):
        body_ids = tuple(body_ids)
        if not body_ids or tuple(sorted(body_ids)) != body_ids or len(set(body_ids)) != len(body_ids):
            raise StimulusConfigError("body_ids must be non-empty, unique and ascending")
        for body_id in body_ids:
            if type(body_id) is not int or body_id <= 0:
                raise StimulusConfigError("body_ids must be positive integers")
        if not isinstance(populations, Mapping) or not populations:
            raise StimulusConfigError("populations must be a non-empty mapping")

        names = list(populations)
        for name in names:
            if not isinstance(name, str) or not name.strip():
                raise StimulusConfigError("population names must be nonblank strings")

        known = set(body_ids)
        seen_ids = set()
        normalized = {}
        for name in sorted(names):
            spec = populations[name]
            if not isinstance(spec, Mapping) or set(spec) != {"body_ids", "side", "max_amplitude"}:
                raise StimulusConfigError(
                    f"population {name!r} must contain exactly body_ids, side, max_amplitude"
                )
            side = spec["side"]
            if side not in _VALID_SIDES:
                raise StimulusConfigError("population side must be one of L, R, M")
            members = spec["body_ids"]
            if not isinstance(members, Sequence) or isinstance(members, (str, bytes)):
                raise StimulusConfigError("population body_ids must be a sequence")
            members = tuple(members)
            if not members:
                raise StimulusConfigError("population body_ids must be non-empty")
            if tuple(sorted(members)) != members or len(set(members)) != len(members):
                raise StimulusConfigError("population body_ids must be unique and ascending")
            for body_id in members:
                if type(body_id) is not int or body_id not in known:
                    raise StimulusConfigError("population references unknown body_id")
                if body_id in seen_ids:
                    raise StimulusConfigError("body_id may belong to only one stimulus population")
                seen_ids.add(body_id)
            limit = spec["max_amplitude"]
            if isinstance(limit, bool) or not isinstance(limit, (int, float)):
                raise StimulusConfigError("max_amplitude must be numeric")
            limit = float(limit)
            if not math.isfinite(limit) or not 0.0 <= limit <= 1.0:
                raise StimulusConfigError("max_amplitude must be finite in [0, 1]")
            normalized[name] = (members, side, limit)

        self.body_ids = body_ids
        self._populations = normalized

    def population_specs(self):
        """Return detached population metadata for inspection/logging."""
        return {
            name: {"body_ids": list(members), "side": side, "max_amplitude": limit}
            for name, (members, side, limit) in self._populations.items()
        }

    def build_external(self, stimuli, *, valid=True, stale=False):
        """Return detached body-ID->amplitude mapping; stale/invalid observations inject zero."""
        if type(valid) is not bool or type(stale) is not bool:
            raise StimulusInputError("valid and stale must be bool")
        if not valid or stale:
            return {}
        if not isinstance(stimuli, Mapping):
            raise StimulusInputError("stimuli must be a mapping")
        external = {}
        for name, amplitude in stimuli.items():
            if name not in self._populations:
                raise StimulusInputError(f"unknown stimulus population {name!r}")
            if isinstance(amplitude, bool) or not isinstance(amplitude, (int, float)):
                raise StimulusInputError("stimulus amplitude must be numeric")
            amplitude = float(amplitude)
            if not math.isfinite(amplitude) or not 0.0 <= amplitude <= 1.0:
                raise StimulusInputError("stimulus amplitude must be finite in [0, 1]")
            members, _side, limit = self._populations[name]
            effective = min(amplitude, limit)
            if effective == 0.0:
                continue
            for body_id in members:
                external[body_id] = effective
        return external
