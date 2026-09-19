"""Typed post-watchdog boundary to robotd's high-level motion intents."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import math
from pathlib import Path

from .robotd_client import RobotdClient
from .watchdog import WatchdogOutput

MAX_ABS_VX_MPS = 0.08
MAX_ABS_VY_MPS = 0.0
MAX_ABS_VYAW_RADPS = 0.50
_ADAPTER_COMMAND_SEAL = object()


class MotionAdapterError(ValueError):
    """A motion config or post-watchdog command violates P6-03."""


@dataclass(frozen=True, slots=True, init=False)
class _BoundedRobotdCommand:
    """A robotd twist minted only after the adapter's final envelope check."""

    vx: float
    vy: float
    vyaw: float

    def __init__(self, *, _seal, vx, vy, vyaw):
        if _seal is not _ADAPTER_COMMAND_SEAL:
            raise TypeError("bounded robotd commands are adapter-minted")
        object.__setattr__(self, "vx", vx)
        object.__setattr__(self, "vy", vy)
        object.__setattr__(self, "vyaw", vyaw)


def _bounded_command(*, vx, vy, vyaw):
    return _BoundedRobotdCommand(
        _seal=_ADAPTER_COMMAND_SEAL, vx=float(vx), vy=float(vy), vyaw=float(vyaw)
    )


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
        if type(output) is not WatchdogOutput:
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
                if self.stop_transport == "zero_twist":
                    self.client._send_motion(_bounded_command(vx=0.0, vy=0.0, vyaw=0.0))
                    self.client.health()
                    result = "zero_twist_refreshed"
                else:
                    # Refresh every watchdog tick. The request/response is also the liveness proof.
                    self.client.stop()
                    result = "robot_stop_refreshed"
            except Exception:
                self._requires_fresh_safe_stop = True
                raise
            self._requires_fresh_safe_stop = False
            self._connection_generation = self.client.status.generation
            return result
        command = _bounded_command(
            vx=intent["vx"], vy=0.0, vyaw=intent["vyaw"]
        )
        try:
            self.client._send_motion(command)
        except Exception:
            self._requires_fresh_safe_stop = True
            raise
        return "move"
