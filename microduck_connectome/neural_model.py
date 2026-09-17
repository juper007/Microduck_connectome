"""Validation and identity for the frozen MVP neural-model contract."""

from collections.abc import Mapping
import hashlib
import json
import math
from pathlib import Path

SCHEMA_VERSION = "neural-model-config-v1"
MODEL_SPEC_VERSION = "P-1.1"
MODEL_FAMILY = "discrete-time-lif-like"

_REQUIRED_FIELDS = frozenset(
    (
        "schema_version",
        "model_spec_version",
        "model_family",
        "timestep_ms",
        "alpha",
        "threshold",
        "reset_value",
        "recurrent_gain",
        "state_dtype",
        "spike_dtype",
        "deterministic",
        "plasticity",
        "recurrent_weight_mode",
        "normalization_scope",
        "update_semantics",
        "recurrent_spike_source",
        "initial_state",
    )
)

_FROZEN_INVARIANTS = {
    "schema_version": SCHEMA_VERSION,
    "model_spec_version": MODEL_SPEC_VERSION,
    "model_family": MODEL_FAMILY,
    "state_dtype": "float32",
    "spike_dtype": "bool",
    "deterministic": True,
    "plasticity": False,
    "recurrent_weight_mode": "unsigned",
    "normalization_scope": "full_source_before_subgraph_filtering",
    "update_semantics": "synchronous",
    "recurrent_spike_source": "previous_step",
    "initial_state": "zero",
}


class NeuralModelConfigError(ValueError):
    """A neural-model configuration violates the frozen MVP contract."""


def _canonical_json(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _finite_number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise NeuralModelConfigError(f"{label} must be a finite number")
    value = float(value)
    if not math.isfinite(value):
        raise NeuralModelConfigError(f"{label} must be a finite number")
    return value


def validate_model_config(config):
    """Validate and return a canonicalizable copy of an MVP model config."""
    if not isinstance(config, Mapping):
        raise NeuralModelConfigError("config must be a mapping")
    fields = set(config)
    if fields != _REQUIRED_FIELDS:
        missing = sorted(_REQUIRED_FIELDS - fields)
        extra = sorted(fields - _REQUIRED_FIELDS)
        raise NeuralModelConfigError(f"config fields mismatch; missing={missing}, extra={extra}")

    for key, expected in _FROZEN_INVARIANTS.items():
        if config[key] != expected or type(config[key]) is not type(expected):
            raise NeuralModelConfigError(f"{key} must be {expected!r} for MVP")

    timestep_ms = config["timestep_ms"]
    if type(timestep_ms) is not int or timestep_ms <= 0:
        raise NeuralModelConfigError("timestep_ms must be a positive integer")

    alpha = _finite_number(config["alpha"], "alpha")
    if not 0.0 <= alpha <= 1.0:
        raise NeuralModelConfigError("alpha must be in [0, 1]")

    threshold = _finite_number(config["threshold"], "threshold")
    reset_value = _finite_number(config["reset_value"], "reset_value")
    recurrent_gain = _finite_number(config["recurrent_gain"], "recurrent_gain")
    if recurrent_gain < 0.0:
        raise NeuralModelConfigError("recurrent_gain must be non-negative for unsigned MVP weights")

    validated = dict(config)
    validated["alpha"] = alpha
    validated["threshold"] = threshold
    validated["reset_value"] = reset_value
    validated["recurrent_gain"] = recurrent_gain
    return validated


def model_config_sha256(config):
    """Return SHA-256 of validated canonical JSON configuration bytes."""
    validated = validate_model_config(config)
    return hashlib.sha256(_canonical_json(validated).encode("utf-8")).hexdigest()


def load_model_config(path):
    """Load a UTF-8 JSON file and validate the frozen MVP model contract."""
    path = Path(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise NeuralModelConfigError(f"cannot load model config: {error}") from error
    return validate_model_config(value)
