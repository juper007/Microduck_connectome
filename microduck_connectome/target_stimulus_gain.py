"""Explicit bounded Phase-7 LC10a stimulus gain layered over P4 mapping v1."""

from __future__ import annotations

import json
import math
from pathlib import Path

from .sensory_mapping import SensoryMapper


def load_target_stimulus_gain(path: str | Path) -> dict:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if set(value) != {"schema_version", "target_gain", "max_channel_amplitude", "source", "scope"}:
        raise ValueError("target gain fields mismatch")
    if value["schema_version"] != "target-stimulus-gain-v1" or value["source"] != "phase-7-engineering-calibration":
        raise ValueError("target gain identity mismatch")
    gain = value["target_gain"]
    limit = value["max_channel_amplitude"]
    if (isinstance(gain, bool) or not isinstance(gain, (int, float))
            or not math.isfinite(gain) or not 0 < gain <= 50):
        raise ValueError("target gain must be finite in (0, 50]")
    if type(limit) not in (int, float) or limit != 1.0:
        raise ValueError("target channel bound must remain 1")
    if not isinstance(value["scope"], str) or not value["scope"]:
        raise ValueError("target gain scope is required")
    return value


class TargetGainSensoryMapper(SensoryMapper):
    """Keep P4 lateral split and TTL, then scale only LC10a target channels."""

    def __init__(self, runtime_body_ids, sensory_config, gain_config):
        super().__init__(runtime_body_ids, sensory_config)
        self.gain = float(gain_config["target_gain"])
        self.limit = float(gain_config["max_channel_amplitude"])

    def map_channels(self, frame, *, now_ns):
        channels = super().map_channels(frame, now_ns=now_ns)
        for side in ("lc10a_left", "lc10a_right"):
            channels[side] = min(self.limit, channels[side] * self.gain)
        return channels
