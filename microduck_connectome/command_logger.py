"""Deterministic structured Phase-5 command trace logging."""

from collections.abc import Mapping, Sequence
import hashlib
import json
from pathlib import Path
import re

from .control_contracts import (
    CONTROLLER_SOURCE,
    ControlContractError,
    validate_behavior_intent,
    validate_neural_readout,
)

SCHEMA_VERSION = "command-trace-v1"
_REQUIRED_HASH_NAMES = (
    "dn_readout",
    "steering_decoder",
    "escape_decoder",
    "safety_envelope",
    "watchdog",
)
_CONFIG_FILES = {
    "dn_readout": "config/dn_readout_v1.json",
    "steering_decoder": "config/steering_decoder_v1.json",
    "escape_decoder": "config/escape_decoder_v1.json",
    "safety_envelope": "config/safety_envelope_v1.json",
    "watchdog": "config/watchdog_v1.json",
}


class CommandLoggerError(ValueError):
    """Command trace configuration or record violates P5-06."""


def sha256_file(path):
    try:
        data = Path(path).read_bytes()
    except OSError as error:
        raise CommandLoggerError("cannot read config for hashing") from error
    return hashlib.sha256(data).hexdigest()


def phase5_config_hashes(root):
    root = Path(root)
    return {
        name: sha256_file(root / relative)
        for name, relative in _CONFIG_FILES.items()
    }


def load_command_logger_config(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CommandLoggerError("cannot load command logger config") from error
    required = {
        "schema_version",
        "controller_source",
        "required_config_hashes",
        "format",
        "scope",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise CommandLoggerError("command logger config fields mismatch")
    if value["schema_version"] != "command-logger-v1":
        raise CommandLoggerError("command logger schema mismatch")
    if value["controller_source"] != CONTROLLER_SOURCE:
        raise CommandLoggerError("controller source mismatch")
    if value["format"] != "canonical-jsonl":
        raise CommandLoggerError("format must be canonical-jsonl")
    if value["required_config_hashes"] != list(_REQUIRED_HASH_NAMES):
        raise CommandLoggerError("required config hash names/order mismatch")
    return dict(value)


def _hashes(value):
    if not isinstance(value, Mapping) or set(value) != set(_REQUIRED_HASH_NAMES):
        raise CommandLoggerError("config_hashes must contain the five Phase-5 config identities")
    normalized = {}
    for name in _REQUIRED_HASH_NAMES:
        digest = value[name]
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise CommandLoggerError(f"{name} config hash must be lowercase SHA256")
        normalized[name] = digest
    return normalized


def _intent(value, label, *, optional=False):
    if optional and value is None:
        return None
    try:
        return validate_behavior_intent(value)
    except ControlContractError as error:
        raise CommandLoggerError(f"{label} violates behavior-intent contract") from error


def _neural(value):
    if value is None:
        return None
    try:
        return validate_neural_readout(value)
    except ControlContractError as error:
        raise CommandLoggerError("neural_readout violates frozen contract") from error


def _reasons(value, label):
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise CommandLoggerError(f"{label} must be a string sequence")
    result = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise CommandLoggerError(f"{label} entries must be nonblank strings")
        result.append(item)
    return result


def _safety_result(value):
    if value is None:
        return None, None, []
    if not isinstance(value, Mapping) or set(value) != {"intent", "clamp_applied", "reasons"}:
        raise CommandLoggerError("safety_result fields mismatch")
    if type(value["clamp_applied"]) is not bool:
        raise CommandLoggerError("clamp_applied must be bool")
    return (
        _intent(value["intent"], "post_safety_intent"),
        value["clamp_applied"],
        _reasons(value["reasons"], "clamp reasons"),
    )


def _watchdog_result(value):
    required = {"intent", "watchdog_state", "stale_reason", "decoder_alive"}
    if not isinstance(value, Mapping) or set(value) != required:
        raise CommandLoggerError("watchdog_result fields mismatch")
    final_intent = _intent(value["intent"], "final_intent")
    state = value["watchdog_state"]
    if state not in ("healthy", "safe_stop"):
        raise CommandLoggerError("watchdog_state must be healthy or safe_stop")
    stale_reason = value["stale_reason"]
    if stale_reason is not None and (
        not isinstance(stale_reason, str) or not stale_reason.strip()
    ):
        raise CommandLoggerError("stale_reason must be null or nonblank text")
    if type(value["decoder_alive"]) is not bool:
        raise CommandLoggerError("decoder_alive must be bool")
    if state == "safe_stop":
        if not final_intent["stop"] or any(
            final_intent[name] != 0.0 for name in ("vx", "vy", "vyaw")
        ):
            raise CommandLoggerError("safe_stop watchdog output must be stop-zero")
        if stale_reason is None:
            raise CommandLoggerError("safe_stop requires a reason")
    return final_intent, state, stale_reason, value["decoder_alive"]


class CommandTraceLogger:
    """Retain detached, deterministic Phase-5 control records."""

    def __init__(self, config, config_hashes):
        if isinstance(config, (str, Path)):
            config = load_command_logger_config(config)
        else:
            # Round-trip through the same validation without leaking caller mutation.
            if not isinstance(config, Mapping):
                raise CommandLoggerError("config must be mapping or path")
            expected = {
                "schema_version": "command-logger-v1",
                "controller_source": CONTROLLER_SOURCE,
                "required_config_hashes": list(_REQUIRED_HASH_NAMES),
                "format": "canonical-jsonl",
                "scope": config.get("scope"),
            }
            if dict(config) != expected or not isinstance(expected["scope"], str):
                raise CommandLoggerError("invalid in-memory command logger config")
            config = expected
        self.config = dict(config)
        self.config_hashes = _hashes(config_hashes)
        self._records = []

    def append(
        self,
        *,
        neural_readout,
        pre_safety_intent,
        safety_result,
        watchdog_result,
    ):
        neural = _neural(neural_readout)
        pre = _intent(pre_safety_intent, "pre_safety_intent", optional=True)
        post, clamp_applied, clamp_reasons = _safety_result(safety_result)
        final_intent, watchdog_state, stale_reason, decoder_alive = _watchdog_result(
            watchdog_result
        )

        timestamp_ns = final_intent["timestamp_ns"]
        sequence = final_intent["sequence"]
        if self._records:
            previous = self._records[-1]
            if timestamp_ns <= previous["timestamp_ns"]:
                raise CommandLoggerError("record timestamp must increase strictly")
            if sequence <= previous["sequence"]:
                raise CommandLoggerError("record sequence must increase strictly")

        record = {
            "schema_version": SCHEMA_VERSION,
            "timestamp_ns": timestamp_ns,
            "sequence": sequence,
            "neural_readout": neural,
            "pre_safety_intent": pre,
            "post_safety_intent": post,
            "final_intent": final_intent,
            "stop": final_intent["stop"],
            "runtime_healthy": None if neural is None else neural["runtime_healthy"],
            "watchdog_state": watchdog_state,
            "decoder_alive": decoder_alive,
            "clamp_applied": clamp_applied,
            "clamp_reasons": clamp_reasons,
            "stale_reason": stale_reason,
            "controller_source": CONTROLLER_SOURCE,
            "config_hashes": dict(self.config_hashes),
        }
        # Canonical JSON is also the strict no-NaN/Inf check and deep detach.
        canonical = json.dumps(
            record,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        detached = json.loads(canonical)
        self._records.append(detached)
        return json.loads(canonical)

    def records(self):
        return json.loads(
            json.dumps(
                self._records,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            )
        )

    def to_jsonl(self):
        return "".join(
            json.dumps(
                record,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            )
            + "\n"
            for record in self._records
        )
