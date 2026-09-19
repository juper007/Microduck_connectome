"""Typed post-watchdog boundary to robotd's high-level motion intents."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import math
from pathlib import Path

from .control_contracts import ControlContractError, validate_behavior_intent
from .robotd_client import RobotdClient

MAX_ABS_VX_MPS = 0.08
MAX_ABS_VY_MPS = 0.0
MAX_ABS_VYAW_RADPS = 0.50
_POST_WATCHDOG_SEAL = object()


class MotionAdapterError(ValueError):
    """A motion config or post-watchdog command violates P6-03."""


@dataclass(frozen=True, slots=True, init=False)
class PostWatchdogIntent:
    """Intent proven to be the final output of ControllerWatchdog.tick()."""

    timestamp_ns: int
    sequence: int
    vx: float
    vy: float
    vyaw: float
    stop: bool
    watchdog_state: str

    def __init__(self, *, _seal, intent, watchdog_state):
        if _seal is not _POST_WATCHDOG_SEAL:
            raise TypeError("PostWatchdogIntent must come from from_watchdog_result")
        object.__setattr__(self, "timestamp_ns", intent["timestamp_ns"])
        object.__setattr__(self, "sequence", intent["sequence"])
        object.__setattr__(self, "vx", intent["vx"])
        object.__setattr__(self, "vy", intent["vy"])
        object.__setattr__(self, "vyaw", intent["vyaw"])
        object.__setattr__(self, "stop", intent["stop"])
        object.__setattr__(self, "watchdog_state", watchdog_state)

    @classmethod
    def from_watchdog_result(cls, result: Mapping) -> "PostWatchdogIntent":
        required = {"intent", "watchdog_state", "stale_reason", "decoder_alive"}
        if not isinstance(result, Mapping) or set(result) != required:
            raise MotionAdapterError("watchdog result fields mismatch")
        state = result["watchdog_state"]
        if state not in ("healthy", "safe_stop"):
            raise MotionAdapterError("watchdog_state must be healthy or safe_stop")
        if type(result["decoder_alive"]) is not bool:
            raise MotionAdapterError("decoder_alive must be bool")
        reason = result["stale_reason"]
        if reason is not None and not isinstance(reason, str):
            raise MotionAdapterError("stale_reason must be a string or null")
        try:
            intent = validate_behavior_intent(result["intent"])
        except ControlContractError as error:
            raise MotionAdapterError("invalid watchdog intent") from error
        if state == "safe_stop":
            if reason is None or not intent["stop"] or any(
                intent[field] != 0.0 for field in ("vx", "vy", "vyaw")
            ):
                raise MotionAdapterError("safe_stop must carry a reason and stop-zero intent")
        elif reason is not None or result["decoder_alive"] is not True:
            raise MotionAdapterError("healthy watchdog output requires a live decoder and no reason")
        return cls(_seal=_POST_WATCHDOG_SEAL, intent=intent, watchdog_state=state)


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
        self._stop_latched = False
        self._stop_generation = None

    def send(self, command: PostWatchdogIntent) -> str:
        if not isinstance(command, PostWatchdogIntent):
            raise TypeError("adapter accepts PostWatchdogIntent only")
        values = (command.vx, command.vy, command.vyaw)
        if not all(math.isfinite(value) for value in values):
            raise MotionAdapterError("motion values must be finite")
        if abs(command.vx) > MAX_ABS_VX_MPS:
            raise MotionAdapterError("vx exceeds the P6-03 envelope")
        if command.vy != 0.0:
            raise MotionAdapterError("vy must remain zero")
        if abs(command.vyaw) > MAX_ABS_VYAW_RADPS:
            raise MotionAdapterError("vyaw exceeds the P6-03 envelope")
        if command.stop:
            if values != (0.0, 0.0, 0.0):
                raise MotionAdapterError("stop intent must be zero twist")
            if self.stop_transport == "zero_twist":
                self.client.move(vx=0.0, vy=0.0, vyaw=0.0)
                return "zero_twist"
            status = getattr(self.client, "status", None)
            generation = getattr(status, "generation", None)
            connected = getattr(status, "connected", True)
            if (
                not self._stop_latched
                or not connected
                or generation != self._stop_generation
            ):
                self.client.stop()
                self._stop_latched = True
                self._stop_generation = generation
                return "robot_stop"
            return "robot_stop_latched"
        self.client.move(vx=command.vx, vy=0.0, vyaw=command.vyaw)
        self._stop_latched = False
        self._stop_generation = None
        return "move"
