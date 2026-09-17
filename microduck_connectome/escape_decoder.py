"""Config-driven internal escape/stop decoder for P5-03."""

from collections.abc import Mapping
from dataclasses import dataclass
import json
import math
from pathlib import Path

from .control_contracts import (
    ControlContractError,
    make_behavior_intent,
    validate_behavior_intent,
    validate_neural_readout,
)


class EscapeDecoderError(ValueError):
    """Escape decoder input/configuration violates P5-03."""


@dataclass(frozen=True)
class EscapeDecoderConfig:
    gain: float = 1.0
    threshold: float = 0.5

    def __post_init__(self):
        for value, label in ((self.gain, "gain"), (self.threshold, "threshold")):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise EscapeDecoderError(f"{label} must be numeric")
            if not math.isfinite(float(value)):
                raise EscapeDecoderError(f"{label} must be finite")
        if float(self.gain) <= 0:
            raise EscapeDecoderError("gain must be > 0")
        if not 0.0 < float(self.threshold) <= 1.0:
            raise EscapeDecoderError("threshold must be in (0,1]")


def load_escape_decoder_config(path):
    try:
        value=json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EscapeDecoderError("cannot load escape decoder config") from error
    if not isinstance(value, Mapping) or set(value)!={"schema_version","gain","threshold","source","scope"}:
        raise EscapeDecoderError("config fields mismatch")
    if value["schema_version"]!="escape-decoder-v1" or value["source"]!="male-cns-controller":
        raise EscapeDecoderError("config schema/source mismatch")
    return EscapeDecoderConfig(value["gain"], value["threshold"])


class EscapeDecoder:
    def __init__(self, config):
        if not isinstance(config, EscapeDecoderConfig):
            raise EscapeDecoderError("config must be EscapeDecoderConfig")
        self.config=config

    def apply(self, readout, base_intent=None):
        try:
            neural=validate_neural_readout(readout)
            base=validate_behavior_intent(base_intent) if base_intent is not None else None
        except ControlContractError as error:
            raise EscapeDecoderError("invalid readout/base intent") from error
        if base is not None and (
            base["timestamp_ns"]!=neural["timestamp_ns"] or base["sequence"]!=neural["sequence"]
        ):
            raise EscapeDecoderError("base intent metadata must match neural readout")

        unhealthy=not neural["runtime_healthy"]
        effective=min(1.0, neural["escape"]*float(self.config.gain))
        asserted=unhealthy or effective>=float(self.config.threshold) or (base is not None and base["stop"])
        if asserted:
            return make_behavior_intent(
                timestamp_ns=neural["timestamp_ns"], sequence=neural["sequence"],
                vx=0.0, vy=0.0, vyaw=0.0, stop=True,
                confidence=0.0 if unhealthy else effective,
            )
        if base is not None:
            return base
        return make_behavior_intent(
            timestamp_ns=neural["timestamp_ns"], sequence=neural["sequence"],
            confidence=max(0.0, 1.0-effective),
        )
