"""Typed post-watchdog boundary to robotd's high-level motion intents."""

from __future__ import annotations

from collections.abc import Mapping
import json
import math
from pathlib import Path

from .robotd_client import RobotdClient
from .watchdog import WatchdogOutput, _is_authentic_watchdog_output

MAX_ABS_VX_MPS = 0.08
MAX_ABS_VY_MPS = 0.0
MAX_ABS_VYAW_RADPS = 0.50


class MotionAdapterError(ValueError):
    """A motion config or post-watchdog command violates P6-03."""


def _validate_motion_adapter_config(value) -> dict:
    required = {
        "schema_version", "max_abs_vx_mps", "max_abs_vy_mps",
        "max_abs_vyaw_radps", "stop_transport", "source", "scope",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise MotionAdapterError("motion adapter config fields mismatch")
    if value["schema_version"] != "motion-adapter-v1":
        raise MotionAdapterError("motion adapter schema mismatch")
    if value["source"] != "male-cns-controller":
        raise MotionAdapterError("motion adapter source mismatch")
    expected = {
        "max_abs_vx_mps": MAX_ABS_VX_MPS,
        "max_abs_vy_mps": MAX_ABS_VY_MPS,
        "max_abs_vyaw_radps": MAX_ABS_VYAW_RADPS,
    }
    for field, limit in expected.items():
        actual = value[field]
        if isinstance(actual, bool) or not isinstance(actual, (int, float)):
            raise MotionAdapterError(f"{field} must be numeric")
        if not math.isfinite(float(actual)) or float(actual) != limit:
            raise MotionAdapterError(f"{field} must remain {limit}")
    if value["stop_transport"] not in ("robot_stop", "zero_twist"):
        raise MotionAdapterError("stop_transport must be robot_stop or zero_twist")
    return dict(value)


def load_motion_adapter_config(path) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise MotionAdapterError("cannot load motion adapter config") from error
    return _validate_motion_adapter_config(value)


class RobotMotionAdapter:
    """Send bounded final watchdog output through robotd only."""

    def __init__(self, client: RobotdClient, config):
        self.client = client
        self.config = (
            load_motion_adapter_config(config)
            if isinstance(config, (str, Path))
            else _validate_motion_adapter_config(config)
        )
        self.stop_transport = self.config["stop_transport"]
        status = self.client.status
        self._connection_generation = status.generation
        self._requires_fresh_safe_stop = not status.connected
        self._last_metadata = None

    def send(self, output: WatchdogOutput) -> str:
        if not _is_authentic_watchdog_output(output):
            raise TypeError("adapter accepts ControllerWatchdog.tick output only")
        intent = output["intent"]
        metadata = (intent["timestamp_ns"], intent["sequence"])
        if self._last_metadata is not None and (
            metadata[0] <= self._last_metadata[0] or metadata[1] <= self._last_metadata[1]
        ):
            raise MotionAdapterError("watchdog output must advance; stale replay rejected")
        # Consume before I/O: an ambiguously failed send can never be replayed after reconnect.
        self._last_metadata = metadata
        status = self.client.status
        if status.generation != self._connection_generation or not status.connected:
            self._connection_generation = status.generation
            self._requires_fresh_safe_stop = True
        values = (intent["vx"], intent["vy"], intent["vyaw"])
        if not all(math.isfinite(value) for value in values):
            raise MotionAdapterError("motion values must be finite")
        if abs(intent["vx"]) > MAX_ABS_VX_MPS:
            raise MotionAdapterError("vx exceeds the P6-03 envelope")
        if intent["vy"] != 0.0:
            raise MotionAdapterError("vy must remain zero")
        if abs(intent["vyaw"]) > MAX_ABS_VYAW_RADPS:
            raise MotionAdapterError("vyaw exceeds the P6-03 envelope")
        if not intent["stop"] and self._requires_fresh_safe_stop:
            raise MotionAdapterError("reconnect requires a fresh watchdog safe-stop output")
        if intent["stop"]:
            if values != (0.0, 0.0, 0.0):
                raise MotionAdapterError("stop intent must be zero twist")
            try:
                result = self.client._send_watchdog(output, self.stop_transport)
            except Exception:
                self._requires_fresh_safe_stop = True
                raise
            self._requires_fresh_safe_stop = False
            self._connection_generation = self.client.status.generation
            return result
        try:
            result = self.client._send_watchdog(output, self.stop_transport)
        except Exception:
            self._requires_fresh_safe_stop = True
            raise
        return result
