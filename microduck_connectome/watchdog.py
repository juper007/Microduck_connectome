"""Independent Phase-5 stale/unhealthy/unavailable-control watchdog."""

from collections.abc import Mapping
from dataclasses import dataclass
import json
from pathlib import Path

from .control_contracts import (
    ControlContractError,
    make_behavior_intent,
    validate_behavior_intent,
    validate_neural_readout,
)


class WatchdogError(ValueError):
    """Watchdog configuration or fallback metadata is invalid."""


@dataclass(frozen=True)
class WatchdogConfig:
    neural_readout_ttl_ms: int = 100
    behavior_intent_ttl_ms: int = 100

    def __post_init__(self):
        if type(self.neural_readout_ttl_ms) is not int or self.neural_readout_ttl_ms != 100:
            raise WatchdogError("neural_readout_ttl_ms must remain frozen at 100")
        if type(self.behavior_intent_ttl_ms) is not int or self.behavior_intent_ttl_ms != 100:
            raise WatchdogError("behavior_intent_ttl_ms must remain frozen at 100")


def load_watchdog_config(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise WatchdogError("cannot load watchdog config") from error
    required = {
        "schema_version",
        "neural_readout_ttl_ms",
        "behavior_intent_ttl_ms",
        "source",
        "safe_state",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise WatchdogError("watchdog config fields mismatch")
    if value["schema_version"] != "watchdog-v1" or value["source"] != "male-cns-controller":
        raise WatchdogError("watchdog config schema/source mismatch")
    return WatchdogConfig(
        value["neural_readout_ttl_ms"],
        value["behavior_intent_ttl_ms"],
    )


class ControlWatchdog:
    """Substitute internal stop-zero intent whenever control freshness/health is not valid."""

    def __init__(self, config=None):
        self.config = config or WatchdogConfig()
        if not isinstance(self.config, WatchdogConfig):
            raise WatchdogError("config must be WatchdogConfig")
        self.reset()

    def reset(self):
        self._last_neural = None
        self._last_intent = None
        self._last_output = None

    @staticmethod
    def _same_or_advancing(current, previous):
        if previous is None:
            return True
        cts, cseq = current["timestamp_ns"], current["sequence"]
        pts, pseq = previous["timestamp_ns"], previous["sequence"]
        return (cts == pts and cseq == pseq) or (cts > pts and cseq > pseq)

    def _validate_fallback(self, now_ns, fallback_sequence):
        if type(now_ns) is not int or now_ns < 0:
            raise WatchdogError("now_ns must be a non-negative integer")
        if type(fallback_sequence) is not int or fallback_sequence < 0:
            raise WatchdogError("fallback_sequence must be a non-negative integer")
        if self._last_output is not None:
            if now_ns < self._last_output["timestamp_ns"]:
                raise WatchdogError("now_ns cannot move backward")
            if fallback_sequence < self._last_output["sequence"]:
                raise WatchdogError("fallback_sequence cannot move backward")

    def _safe(self, now_ns, fallback_sequence, reasons):
        safe = make_behavior_intent(
            timestamp_ns=now_ns,
            sequence=fallback_sequence,
            vx=0.0,
            vy=0.0,
            vyaw=0.0,
            stop=True,
            confidence=0.0,
        )
        self._last_output = safe
        return {
            "intent": safe,
            "watchdog_triggered": True,
            "reasons": tuple(reasons),
        }

    def evaluate(
        self,
        neural_readout,
        behavior_intent,
        *,
        now_ns,
        fallback_sequence,
        decoder_available=True,
    ):
        self._validate_fallback(now_ns, fallback_sequence)
        if type(decoder_available) is not bool:
            raise WatchdogError("decoder_available must be bool")

        reasons = []
        neural = None
        intent = None

        if neural_readout is None:
            reasons.append("missing_neural")
        else:
            try:
                neural = validate_neural_readout(neural_readout)
            except ControlContractError:
                reasons.append("invalid_neural")

        if behavior_intent is None:
            reasons.append("missing_behavior")
        else:
            try:
                intent = validate_behavior_intent(behavior_intent)
            except ControlContractError:
                reasons.append("invalid_behavior")

        if not decoder_available:
            reasons.append("decoder_unavailable")

        if neural is not None:
            if neural["timestamp_ns"] > now_ns:
                reasons.append("future_neural")
            elif now_ns - neural["timestamp_ns"] > self.config.neural_readout_ttl_ms * 1_000_000:
                reasons.append("stale_neural")
            if not neural["runtime_healthy"]:
                reasons.append("runtime_unhealthy")
            if not self._same_or_advancing(neural, self._last_neural):
                reasons.append("nonmonotonic_neural")

        if intent is not None:
            if intent["timestamp_ns"] > now_ns:
                reasons.append("future_behavior")
            elif now_ns - intent["timestamp_ns"] > self.config.behavior_intent_ttl_ms * 1_000_000:
                reasons.append("stale_behavior")
            if not self._same_or_advancing(intent, self._last_intent):
                reasons.append("nonmonotonic_behavior")

        if neural is not None and intent is not None:
            if (
                neural["timestamp_ns"] != intent["timestamp_ns"]
                or neural["sequence"] != intent["sequence"]
            ):
                reasons.append("metadata_mismatch")

        if reasons:
            return self._safe(now_ns, fallback_sequence, reasons)

        self._last_neural = neural
        self._last_intent = intent
        self._last_output = intent
        return {
            "intent": dict(intent),
            "watchdog_triggered": False,
            "reasons": (),
        }
