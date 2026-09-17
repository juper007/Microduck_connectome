"""Bounded steering decoder with explicit simulator-calibrated yaw sign."""

from collections.abc import Mapping
from dataclasses import dataclass
import json
import math
from pathlib import Path

from .control_contracts import ControlContractError, make_behavior_intent, validate_neural_readout


class SteeringDecoderError(ValueError):
    """Steering decoder config/readout violates P5-02."""


@dataclass(frozen=True)
class SteeringDecoderConfig:
    steering_yaw_sign: int | None
    gain_vyaw_radps: float
    max_abs_vyaw_radps: float = 0.5

    def __post_init__(self):
        if self.steering_yaw_sign is not None and (
            type(self.steering_yaw_sign) is not int or self.steering_yaw_sign not in (-1, 1)
        ):
            raise SteeringDecoderError("steering_yaw_sign must be null, +1, or -1")
        for value, label in (
            (self.gain_vyaw_radps, "gain_vyaw_radps"),
            (self.max_abs_vyaw_radps, "max_abs_vyaw_radps"),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise SteeringDecoderError(f"{label} must be numeric")
            value = float(value)
            if not math.isfinite(value) or value <= 0.0:
                raise SteeringDecoderError(f"{label} must be finite and > 0")
        if float(self.max_abs_vyaw_radps) > 0.5:
            raise SteeringDecoderError("max_abs_vyaw_radps cannot exceed frozen 0.50")


def load_steering_decoder_config(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SteeringDecoderError("cannot load steering decoder config") from error
    if not isinstance(value, Mapping):
        raise SteeringDecoderError("config must be a mapping")
    required = {
        "schema_version", "steering_yaw_sign", "gain_vyaw_radps",
        "max_abs_vyaw_radps", "source", "scope",
    }
    if set(value) != required or value["schema_version"] != "steering-decoder-v1":
        raise SteeringDecoderError("config fields/schema mismatch")
    if value["source"] != "male-cns-controller":
        raise SteeringDecoderError("source must remain male-cns-controller")
    return SteeringDecoderConfig(
        steering_yaw_sign=value["steering_yaw_sign"],
        gain_vyaw_radps=value["gain_vyaw_radps"],
        max_abs_vyaw_radps=value["max_abs_vyaw_radps"],
    )


class SteeringDecoder:
    def __init__(self, config):
        if not isinstance(config, SteeringDecoderConfig):
            raise SteeringDecoderError("config must be SteeringDecoderConfig")
        self.config = config

    def abstract_demand(self, readout):
        try:
            canonical = validate_neural_readout(readout)
        except ControlContractError as error:
            raise SteeringDecoderError("invalid neural readout") from error
        if not canonical["runtime_healthy"]:
            return 0.0
        return canonical["steering_right"] - canonical["steering_left"]

    def decode(self, readout):
        try:
            canonical = validate_neural_readout(readout)
        except ControlContractError as error:
            raise SteeringDecoderError("invalid neural readout") from error

        if not canonical["runtime_healthy"]:
            return make_behavior_intent(
                timestamp_ns=canonical["timestamp_ns"],
                sequence=canonical["sequence"],
                confidence=0.0,
            )

        demand = canonical["steering_right"] - canonical["steering_left"]
        if self.config.steering_yaw_sign is None:
            raise SteeringDecoderError("steering_yaw_sign is uncalibrated")

        raw = (
            float(self.config.steering_yaw_sign)
            * float(self.config.gain_vyaw_radps)
            * demand
        )
        limit = float(self.config.max_abs_vyaw_radps)
        vyaw = max(-limit, min(limit, raw))
        return make_behavior_intent(
            timestamp_ns=canonical["timestamp_ns"],
            sequence=canonical["sequence"],
            vx=0.0,
            vy=0.0,
            vyaw=vyaw,
            stop=False,
            confidence=min(1.0, abs(demand)),
        )
