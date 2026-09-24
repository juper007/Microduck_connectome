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


def load_target_stimulus_drive(path: str | Path) -> dict:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if set(value) != {"schema_version", "target_gain", "max_channel_amplitude",
                      "lateral_deadzone_x", "source", "scope"}:
        raise ValueError("target drive fields mismatch")
    if value["schema_version"] != "target-stimulus-drive-v2" or value["source"] != "phase-7-engineering-calibration":
        raise ValueError("target drive identity mismatch")
    gain, limit, deadzone = (value[name] for name in
                             ("target_gain", "max_channel_amplitude", "lateral_deadzone_x"))
    if (isinstance(gain, bool) or not isinstance(gain, (int, float))
            or not math.isfinite(gain) or not 0 < gain <= 50):
        raise ValueError("target drive gain must be finite in (0, 50]")
    if type(limit) not in (int, float) or limit != 1.0:
        raise ValueError("target channel bound must remain 1")
    if (isinstance(deadzone, bool) or not isinstance(deadzone, (int, float))
            or not math.isfinite(deadzone) or not 0 <= deadzone < 0.25):
        raise ValueError("lateral deadzone must be finite in [0, .25)")
    if not isinstance(value["scope"], str) or not value["scope"]:
        raise ValueError("target drive scope is required")
    return value


class TargetDriveSensoryMapper(SensoryMapper):
    """P7 engineering side competition at the neural input, never at motor output."""

    def __init__(self, runtime_body_ids, sensory_config, drive_config):
        super().__init__(runtime_body_ids, sensory_config)
        self.gain = float(drive_config["target_gain"])
        self.limit = float(drive_config["max_channel_amplitude"])
        self.deadzone = float(drive_config["lateral_deadzone_x"])

    def map_channels(self, frame, *, now_ns):
        channels = super().map_channels(frame, now_ns=now_ns)
        # Base mapper enforces validity and freshness; never revive stale data.
        strength = channels["lc10a_left"] + channels["lc10a_right"]
        if strength == 0.0:
            return channels
        signed_x = (channels["lc10a_right"] - channels["lc10a_left"]) / strength
        amplitude = min(self.limit, strength * self.gain)
        if signed_x < -self.deadzone:
            channels["lc10a_left"], channels["lc10a_right"] = amplitude, 0.0
        elif signed_x > self.deadzone:
            channels["lc10a_left"], channels["lc10a_right"] = 0.0, amplitude
        else:
            channels["lc10a_left"] = channels["lc10a_right"] = amplitude / 2.0
        return channels
