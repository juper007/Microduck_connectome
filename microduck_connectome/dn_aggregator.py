"""Evidence-pinned descending-neuron activity aggregation for P5-01."""

from collections.abc import Mapping
import hashlib
import json
from pathlib import Path

from .annotations import MAX_BODY_ID
from .neuprint_client import DATASET
from .readout import PopulationReadout, PopulationReadoutError

SCHEMA_VERSION = "dn-readout-v1"
_REQUIRED_POPULATIONS = ("steering_left", "steering_right", "escape")
_EXPECTED_META = {
    "steering_left": ("L", "DNa02"),
    "steering_right": ("R", "DNa02"),
    "escape": ("B", "DNp01"),
}


class DNAggregatorError(ValueError):
    """DN aggregator configuration or input violates the P5-01 contract."""


def _canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def validate_dn_readout_config(config):
    if not isinstance(config, Mapping):
        raise DNAggregatorError("config must be a mapping")
    required = {
        "schema_version", "dataset", "timestep_ms", "window_ms",
        "populations", "source_evidence", "scope",
    }
    if set(config) != required:
        raise DNAggregatorError("config fields do not match dn-readout-v1")
    if config["schema_version"] != SCHEMA_VERSION:
        raise DNAggregatorError(f"schema_version must be {SCHEMA_VERSION}")
    if config["dataset"] != DATASET:
        raise DNAggregatorError(f"dataset must be {DATASET}")
    if config["timestep_ms"] != 20 or type(config["timestep_ms"]) is not int:
        raise DNAggregatorError("timestep_ms must remain frozen at 20")
    if config["window_ms"] != 100 or type(config["window_ms"]) is not int:
        raise DNAggregatorError("window_ms must remain frozen at 100")

    populations = config["populations"]
    if not isinstance(populations, Mapping) or set(populations) != set(_REQUIRED_POPULATIONS):
        raise DNAggregatorError("exact steering_left/right and escape populations are required")

    normalized = dict(config)
    normalized_populations = {}
    seen = set()
    for name in _REQUIRED_POPULATIONS:
        spec = populations[name]
        if not isinstance(spec, Mapping) or set(spec) != {"body_ids", "side", "source_type"}:
            raise DNAggregatorError(f"{name} has invalid population fields")
        expected_side, expected_type = _EXPECTED_META[name]
        if spec["side"] != expected_side or spec["source_type"] != expected_type:
            raise DNAggregatorError(f"{name} side/type metadata mismatch")
        ids = spec["body_ids"]
        if not isinstance(ids, list) or not ids:
            raise DNAggregatorError(f"{name}.body_ids must be a non-empty list")
        if ids != sorted(ids) or len(ids) != len(set(ids)):
            raise DNAggregatorError(f"{name}.body_ids must be unique and ascending")
        for body_id in ids:
            if type(body_id) is not int or not 1 <= body_id <= MAX_BODY_ID:
                raise DNAggregatorError(f"{name} contains invalid body_id")
            if body_id in seen:
                raise DNAggregatorError("readout populations must not overlap")
            seen.add(body_id)
        normalized_populations[name] = {
            "body_ids": list(ids),
            "side": expected_side,
            "source_type": expected_type,
        }
    normalized["populations"] = normalized_populations
    return normalized


def load_dn_readout_config(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DNAggregatorError("cannot load DN readout config") from error
    return validate_dn_readout_config(value)


def dn_readout_config_sha256(config):
    canonical = _canonical_json(validate_dn_readout_config(config))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class DNActivityAggregator:
    """Produce normalized neural-readout messages from aligned runtime spikes."""

    def __init__(self, runtime_body_ids, config):
        self.config = validate_dn_readout_config(config)
        populations = {
            name: spec["body_ids"]
            for name, spec in self.config["populations"].items()
        }
        try:
            self.readout = PopulationReadout(
                tuple(runtime_body_ids),
                populations,
                timestep_ms=self.config["timestep_ms"],
                window_ms=self.config["window_ms"],
            )
        except PopulationReadoutError as error:
            raise DNAggregatorError("invalid runtime body IDs/readout population") from error
        self._last_timestamp_ns = None
        self._last_sequence = None

    def reset(self):
        self.readout.reset()
        self._last_timestamp_ns = None
        self._last_sequence = None

    def _metadata(self, timestamp_ns, sequence, runtime_healthy):
        if type(timestamp_ns) is not int or timestamp_ns < 0:
            raise DNAggregatorError("timestamp_ns must be a non-negative integer")
        if type(sequence) is not int or sequence < 0:
            raise DNAggregatorError("sequence must be a non-negative integer")
        if type(runtime_healthy) is not bool:
            raise DNAggregatorError("runtime_healthy must be bool")
        if self._last_timestamp_ns is not None and timestamp_ns <= self._last_timestamp_ns:
            raise DNAggregatorError("timestamp_ns must increase strictly")
        if self._last_sequence is not None and sequence <= self._last_sequence:
            raise DNAggregatorError("sequence must increase strictly")

    def update(self, spikes, *, timestamp_ns, sequence, runtime_healthy=True):
        self._metadata(timestamp_ns, sequence, runtime_healthy)
        if not runtime_healthy:
            self.readout.reset()
            values = {name: 0.0 for name in _REQUIRED_POPULATIONS}
        else:
            try:
                raw = self.readout.update(spikes)
            except PopulationReadoutError as error:
                raise DNAggregatorError("spikes violate P3 PopulationReadout contract") from error
            denominator = float(self.readout.window_steps)
            values = {name: raw[name] / denominator for name in _REQUIRED_POPULATIONS}

        self._last_timestamp_ns = timestamp_ns
        self._last_sequence = sequence
        return {
            "timestamp_ns": timestamp_ns,
            "sequence": sequence,
            "steering_left": values["steering_left"],
            "steering_right": values["steering_right"],
            "escape": values["escape"],
            "runtime_healthy": runtime_healthy,
        }
