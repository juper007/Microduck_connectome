"""P7-only temporal shaping of DN-selected steering intent."""

from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path

from .control_contracts import make_behavior_intent
from .steering_decoder import SteeringDecoder


def load_temporal_steering_config(path: str | Path) -> dict:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if set(value) != {"schema_version", "hold_ms", "target_ttl_ms", "source", "scope"}:
        raise ValueError("temporal steering config fields mismatch")
    if (value["schema_version"] != "p7-temporal-steering-v1"
            or value["source"] != "phase-7-engineering-calibration"):
        raise ValueError("temporal steering config identity mismatch")
    if type(value["hold_ms"]) is not int or not 0 < value["hold_ms"] <= 500:
        raise ValueError("hold_ms must be a bounded positive integer")
    if type(value["target_ttl_ms"]) is not int or value["target_ttl_ms"] != 100:
        raise ValueError("target_ttl_ms must preserve the P6 perception TTL")
    if not isinstance(value["scope"], str) or not value["scope"]:
        raise ValueError("temporal steering scope is required")
    return value


class P7TemporalSteeringDecoder:
    """Hold the last DN direction through sparse spikes, never through target loss.

    Visual presence is a suppressive gate only. The side and amplitude always
    originate from the DNa02 readout through the ordinary SteeringDecoder.
    """

    def __init__(self, base: SteeringDecoder, config: Mapping):
        if not isinstance(base, SteeringDecoder):
            raise TypeError("base must be a SteeringDecoder")
        self.base = base
        self.hold_ns = config["hold_ms"] * 1_000_000
        self.target_ttl_ns = config["target_ttl_ms"] * 1_000_000
        self.reset()

    def reset(self) -> None:
        self._target_visible = False
        self._held_vyaw = 0.0
        self._last_evidence_ns = None

    def observe_frame(self, frame, *, now_ns: int) -> None:
        visible = (
            isinstance(frame, Mapping)
            and frame.get("valid") is True
            and isinstance(frame.get("target_area"), (int, float))
            and frame["target_area"] > 0
            and type(frame.get("timestamp_ns")) is int
            and 0 <= now_ns - frame["timestamp_ns"] <= self.target_ttl_ns
        )
        if not visible:
            self.reset()
        else:
            self._target_visible = True

    @staticmethod
    def _stop(readout):
        return make_behavior_intent(
            timestamp_ns=readout["timestamp_ns"], sequence=readout["sequence"],
            stop=True, confidence=0.0,
        )

    def decode(self, readout):
        direct = self.base.decode(readout)
        if not self._target_visible or not readout["runtime_healthy"]:
            self.reset()
            return self._stop(readout)
        if direct["vyaw"] != 0.0:
            self._held_vyaw = direct["vyaw"]
            self._last_evidence_ns = readout["timestamp_ns"]
            return direct
        if (self._last_evidence_ns is not None
                and 0 <= readout["timestamp_ns"] - self._last_evidence_ns <= self.hold_ns):
            return make_behavior_intent(
                timestamp_ns=readout["timestamp_ns"], sequence=readout["sequence"],
                vyaw=self._held_vyaw, confidence=min(1.0, abs(self._held_vyaw)),
            )
        self._held_vyaw = 0.0
        self._last_evidence_ns = None
        return direct
