"""Phase-4 perception-to-neural stimulus mapping using pinned Phase-2 populations."""

from collections.abc import Mapping
import hashlib
import json
import math
from pathlib import Path

from .annotations import MAX_BODY_ID
from .neuprint_client import DATASET
from .perception_frame import make_perception_frame
from .stimulus import StimulusInjector

SCHEMA_VERSION = "sensory-mapping-v1"
_POPULATION_KEYS = ("lc10a_left", "lc10a_right", "lplc2_left", "lplc2_right")
_EXPECTED_META = {
    "lc10a_left": ("L", "LC10a"),
    "lc10a_right": ("R", "LC10a"),
    "lplc2_left": ("L", "LPLC2"),
    "lplc2_right": ("R", "LPLC2"),
}


class SensoryMappingError(ValueError):
    """Sensory mapping configuration or frame violates P4-04."""


def _canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def validate_sensory_mapping_config(config):
    if not isinstance(config, Mapping):
        raise SensoryMappingError("config must be a mapping")
    required = {
        "schema_version", "dataset", "perception_ttl_ms", "engineering_mapping",
        "populations", "source_evidence", "scope",
    }
    if set(config) != required:
        raise SensoryMappingError("config fields do not match sensory-mapping-v1")
    if config["schema_version"] != SCHEMA_VERSION:
        raise SensoryMappingError(f"schema_version must be {SCHEMA_VERSION}")
    if config["dataset"] != DATASET:
        raise SensoryMappingError(f"dataset must be {DATASET}")
    if config["perception_ttl_ms"] != 100 or type(config["perception_ttl_ms"]) is not int:
        raise SensoryMappingError("perception_ttl_ms must remain frozen at 100")
    populations = config["populations"]
    if not isinstance(populations, Mapping) or set(populations) != set(_POPULATION_KEYS):
        raise SensoryMappingError("exact LC10a/LPLC2 L/R population keys are required")

    normalized = dict(config)
    normalized_populations = {}
    seen = set()
    for name in _POPULATION_KEYS:
        spec = populations[name]
        if not isinstance(spec, Mapping) or set(spec) != {"body_ids", "side", "max_amplitude", "source_type"}:
            raise SensoryMappingError(f"{name} has invalid population fields")
        expected_side, expected_type = _EXPECTED_META[name]
        if spec["side"] != expected_side or spec["source_type"] != expected_type:
            raise SensoryMappingError(f"{name} side/type metadata mismatch")
        ids = spec["body_ids"]
        if not isinstance(ids, list) or not ids:
            raise SensoryMappingError(f"{name}.body_ids must be a non-empty list")
        if ids != sorted(ids) or len(ids) != len(set(ids)):
            raise SensoryMappingError(f"{name}.body_ids must be unique and ascending")
        for body_id in ids:
            if type(body_id) is not int or not 1 <= body_id <= MAX_BODY_ID:
                raise SensoryMappingError(f"{name} contains invalid body_id")
            if body_id in seen:
                raise SensoryMappingError("sensory populations must not overlap")
            seen.add(body_id)
        limit = spec["max_amplitude"]
        if isinstance(limit, bool) or not isinstance(limit, (int, float)):
            raise SensoryMappingError(f"{name}.max_amplitude must be numeric")
        limit = float(limit)
        if not math.isfinite(limit) or not 0.0 <= limit <= 1.0:
            raise SensoryMappingError(f"{name}.max_amplitude must be in [0,1]")
        normalized_populations[name] = {
            "body_ids": list(ids),
            "side": expected_side,
            "max_amplitude": limit,
            "source_type": expected_type,
        }
    normalized["populations"] = normalized_populations
    return normalized


def load_sensory_mapping_config(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SensoryMappingError("cannot load sensory mapping config") from error
    return validate_sensory_mapping_config(value)


def sensory_mapping_config_sha256(config):
    return hashlib.sha256(_canonical_json(validate_sensory_mapping_config(config)).encode("utf-8")).hexdigest()


class SensoryMapper:
    """Map fresh perception frames to named channels and P3 external inputs."""

    def __init__(self, runtime_body_ids, config):
        self.config = validate_sensory_mapping_config(config)
        injector_specs = {
            name: {
                "body_ids": spec["body_ids"],
                "side": spec["side"],
                "max_amplitude": spec["max_amplitude"],
            }
            for name, spec in self.config["populations"].items()
        }
        self.injector = StimulusInjector(tuple(runtime_body_ids), injector_specs)
        self.ttl_ns = self.config["perception_ttl_ms"] * 1_000_000

    def _frame(self, frame):
        if not isinstance(frame, Mapping):
            raise SensoryMappingError("frame must be a mapping")
        try:
            return make_perception_frame(**dict(frame))
        except (TypeError, ValueError) as error:
            raise SensoryMappingError("frame violates frozen perception contract") from error

    def _status(self, frame, now_ns):
        if type(now_ns) is not int or now_ns < 0:
            raise SensoryMappingError("now_ns must be a non-negative integer")
        frame = self._frame(frame)
        if now_ns < frame["timestamp_ns"]:
            raise SensoryMappingError("now_ns cannot precede frame timestamp")
        stale = now_ns - frame["timestamp_ns"] > self.ttl_ns
        return frame, stale

    def map_channels(self, frame, *, now_ns):
        frame, stale = self._status(frame, now_ns)
        channels = {name: 0.0 for name in _POPULATION_KEYS}
        if stale or not frame["valid"]:
            return channels

        target_strength = frame["target_area"] * frame["confidence"]
        x = frame["target_x"]
        channels["lc10a_left"] = target_strength * (1.0 - x) / 2.0
        channels["lc10a_right"] = target_strength * (1.0 + x) / 2.0
        channels["lplc2_left"] = frame["looming"]
        channels["lplc2_right"] = frame["looming"]
        return channels

    def build_external(self, frame, *, now_ns):
        canonical, stale = self._status(frame, now_ns)
        channels = self.map_channels(canonical, now_ns=now_ns)
        return self.injector.build_external(
            channels,
            valid=canonical["valid"],
            stale=stale,
        )
