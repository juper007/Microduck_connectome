"""Strict Phase-5 neural-readout and behavior-intent contracts."""

from collections.abc import Mapping
import math

NEURAL_READOUT_FIELDS = frozenset((
    "timestamp_ns", "sequence", "steering_left", "steering_right", "escape", "runtime_healthy"
))
BEHAVIOR_INTENT_FIELDS = frozenset((
    "timestamp_ns", "sequence", "vx", "vy", "vyaw", "stop", "confidence", "source"
))
CONTROLLER_SOURCE = "male-cns-controller"


class ControlContractError(ValueError):
    """A Phase-5 readout or intent violates the frozen control contract."""


def _metadata(timestamp_ns, sequence):
    if type(timestamp_ns) is not int or timestamp_ns < 0:
        raise ControlContractError("timestamp_ns must be a non-negative integer")
    if type(sequence) is not int or sequence < 0:
        raise ControlContractError("sequence must be a non-negative integer")
    return timestamp_ns, sequence


def _finite(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ControlContractError(f"{label} must be numeric")
    value = float(value)
    if not math.isfinite(value):
        raise ControlContractError(f"{label} must be finite")
    return value


def validate_neural_readout(readout):
    if not isinstance(readout, Mapping) or set(readout) != NEURAL_READOUT_FIELDS:
        raise ControlContractError("neural readout fields do not match frozen contract")
    timestamp_ns, sequence = _metadata(readout["timestamp_ns"], readout["sequence"])
    values = {}
    for name in ("steering_left", "steering_right", "escape"):
        value = _finite(readout[name], name)
        if not 0.0 <= value <= 1.0:
            raise ControlContractError(f"{name} must be normalized in [0,1]")
        values[name] = value
    if type(readout["runtime_healthy"]) is not bool:
        raise ControlContractError("runtime_healthy must be bool")
    return {
        "timestamp_ns": timestamp_ns,
        "sequence": sequence,
        **values,
        "runtime_healthy": readout["runtime_healthy"],
    }


def validate_behavior_intent(intent):
    if not isinstance(intent, Mapping) or set(intent) != BEHAVIOR_INTENT_FIELDS:
        raise ControlContractError("behavior intent fields do not match frozen contract")
    timestamp_ns, sequence = _metadata(intent["timestamp_ns"], intent["sequence"])
    vx = _finite(intent["vx"], "vx")
    vy = _finite(intent["vy"], "vy")
    vyaw = _finite(intent["vyaw"], "vyaw")
    if type(intent["stop"]) is not bool:
        raise ControlContractError("stop must be bool")
    confidence = _finite(intent["confidence"], "confidence")
    if not 0.0 <= confidence <= 1.0:
        raise ControlContractError("confidence must be in [0,1]")
    if intent["source"] != CONTROLLER_SOURCE:
        raise ControlContractError(f"source must be {CONTROLLER_SOURCE!r}")
    return {
        "timestamp_ns": timestamp_ns,
        "sequence": sequence,
        "vx": vx,
        "vy": vy,
        "vyaw": vyaw,
        "stop": intent["stop"],
        "confidence": confidence,
        "source": CONTROLLER_SOURCE,
    }


def make_behavior_intent(
    *,
    timestamp_ns,
    sequence,
    vx=0.0,
    vy=0.0,
    vyaw=0.0,
    stop=False,
    confidence=1.0,
):
    return validate_behavior_intent({
        "timestamp_ns": timestamp_ns,
        "sequence": sequence,
        "vx": vx,
        "vy": vy,
        "vyaw": vyaw,
        "stop": stop,
        "confidence": confidence,
        "source": CONTROLLER_SOURCE,
    })
