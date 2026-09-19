"""Bounded client for MicroDuck's official robotd JSON-RPC socket.

The wire contract in this module is derived from MicroDuck commit
344925c9f8fa031f85428a305b1e8ec2eaae29c1.  P6-02 deliberately exposes only
``hello``, health/state reads, and the supported high-level motion intents.
Joint, servo, and motor APIs are deliberately absent.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import re
import socket
import time
from typing import Any, Callable, Protocol


DEFAULT_ROBOTD_SOCKET = "/run/robotd.sock"
ROBOTD_API_VERSION = 31
MAX_LINE_BYTES = 64 * 1024
U16_MAX = (1 << 16) - 1
U32_MAX = (1 << 32) - 1
U64_MAX = (1 << 64) - 1
I32_MIN = -(1 << 31)
I32_MAX = (1 << 31) - 1
_REQUEST_METHODS = frozenset({
    "hello", "robot.health", "robot.subscribe", "robot.stop", "robot.enable"
})
_SEMVER = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-((?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)(?:\."
    r"(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


class RobotdError(RuntimeError):
    """Base error for robotd IPC failures."""


class RobotdConnectionError(RobotdError):
    """The Unix socket could not be connected or was disconnected."""


class RobotdTimeoutError(RobotdError):
    """A bounded IPC operation exceeded its deadline."""


class RobotdProtocolError(RobotdError):
    """robotd returned malformed or unexpected protocol data."""


class RobotdRemoteError(RobotdError):
    """robotd returned a JSON-RPC error response."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(f"robotd error {code}: {message}")
        self.code = code
        self.message = message


class _Socket(Protocol):
    def settimeout(self, value: float | None) -> None: ...
    def sendall(self, data: bytes) -> None: ...
    def recv(self, size: int) -> bytes: ...
    def close(self) -> None: ...


Connector = Callable[[str, float], _Socket]


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant {value}")


@dataclass(frozen=True)
class ConnectionStatus:
    connected: bool
    generation: int
    socket_path: str
    peer_api_version: int | None


def _connect_unix(path: str, timeout_s: float) -> _Socket:
    stream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    stream.settimeout(timeout_s)
    try:
        stream.connect(path)
    except BaseException:
        stream.close()
        raise
    return stream


class RobotdClient:
    """Synchronous, deadline-bounded reader for the official robotd socket."""

    def __init__(
        self,
        socket_path: str = DEFAULT_ROBOTD_SOCKET,
        *,
        timeout_s: float = 1.0,
        connector: Connector = _connect_unix,
    ) -> None:
        if not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("timeout_s must be finite and greater than zero")
        self.socket_path = socket_path
        self.timeout_s = timeout_s
        self._connector = connector
        self._socket: _Socket | None = None
        self._buffer = bytearray()
        self._next_id = 1
        self._generation = 0
        self._peer_api_version: int | None = None
        self._last_motion_metadata: tuple[int, int] | None = None
        self._motion_generation = 0
        self._motion_requires_fresh_safe_stop = False

    @property
    def status(self) -> ConnectionStatus:
        return ConnectionStatus(
            connected=self._socket is not None,
            generation=self._generation,
            socket_path=self.socket_path,
            peer_api_version=self._peer_api_version,
        )

    def connect(self) -> ConnectionStatus:
        if self._socket is not None:
            return self.status
        try:
            stream = self._connector(self.socket_path, self.timeout_s)
        except (socket.timeout, TimeoutError) as exc:
            raise RobotdTimeoutError(
                f"timed out connecting to robotd at {self.socket_path}"
            ) from exc
        except OSError as exc:
            raise RobotdConnectionError(
                f"could not connect to robotd at {self.socket_path}: {exc}"
            ) from exc
        self._socket = stream
        self._buffer.clear()
        self._generation += 1
        self._peer_api_version = None
        try:
            hello = self._call("hello", {"api_version": ROBOTD_API_VERSION})
            self._validate_hello(hello)
            self._peer_api_version = hello["api_version"]
        except BaseException:
            self.disconnect()
            raise
        return self.status

    def disconnect(self) -> None:
        stream, self._socket = self._socket, None
        self._buffer.clear()
        self._peer_api_version = None
        if stream is not None:
            stream.close()

    def reconnect(self) -> ConnectionStatus:
        """Open a new generation; no buffered response or state survives."""
        self.disconnect()
        return self.connect()

    def health(self) -> dict[str, Any]:
        result = self._call("robot.health", {})
        self._validate_health(result)
        return result

    def _send_watchdog(self, output: object, stop_transport: str) -> str:
        """Transport one authentic, fresh watchdog output through the safe envelope."""
        from .motion_adapter import (
            MAX_ABS_VX_MPS,
            MAX_ABS_VYAW_RADPS,
        )
        from .watchdog import _is_authentic_watchdog_output

        if not _is_authentic_watchdog_output(output):
            raise TypeError("robotd transport requires a genuine ControllerWatchdog.tick output")
        intent = output["intent"]
        metadata = (intent["timestamp_ns"], intent["sequence"])
        if self._last_motion_metadata is not None and (
            metadata[0] <= self._last_motion_metadata[0]
            or metadata[1] <= self._last_motion_metadata[1]
        ):
            raise ValueError("watchdog output must advance; stale replay rejected")
        # Consume before I/O so an ambiguous failure cannot be replayed after reconnect.
        self._last_motion_metadata = metadata
        status = self.status
        if not status.connected or (
            self._motion_generation != 0
            and status.generation != self._motion_generation
        ):
            self._motion_requires_fresh_safe_stop = True
        if self._motion_generation == 0:
            self._motion_generation = status.generation

        values = (intent["vx"], intent["vy"], intent["vyaw"])
        if not all(
            not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(float(value))
            for value in values
        ):
            raise ValueError("adapter motion command must be finite numeric")
        if (
            abs(intent["vx"]) > MAX_ABS_VX_MPS
            or intent["vy"] != 0.0
            or abs(intent["vyaw"]) > MAX_ABS_VYAW_RADPS
        ):
            raise ValueError("motion command exceeds the P6-03 envelope")

        def write_move(vx: float, vy: float, vyaw: float) -> None:
            stream = self._require_socket()
            request = {
                "jsonrpc": "2.0",
                "method": "robot.move",
                "params": {"vx": vx, "vy": vy, "vyaw": vyaw},
            }
            wire = json.dumps(
                request, separators=(",", ":"), allow_nan=False
            ).encode() + b"\n"
            deadline = time.monotonic() + self.timeout_s
            try:
                stream.settimeout(self._remaining(deadline))
                stream.sendall(wire)
            except socket.timeout as exc:
                self.disconnect()
                self._motion_requires_fresh_safe_stop = True
                raise RobotdTimeoutError("timed out sending robot.move") from exc
            except OSError as exc:
                self.disconnect()
                self._motion_requires_fresh_safe_stop = True
                raise RobotdConnectionError(
                    f"connection lost sending robot.move: {exc}"
                ) from exc

        if intent["stop"]:
            if values != (0.0, 0.0, 0.0):
                raise ValueError("stop intent must be zero twist")
            if stop_transport == "robot_stop":
                self.stop()
                result = "robot_stop_refreshed"
            elif stop_transport == "zero_twist":
                write_move(0.0, 0.0, 0.0)
                self.health()
                result = "zero_twist_refreshed"
            else:
                raise ValueError("unknown stop transport")
            self._motion_requires_fresh_safe_stop = False
            self._motion_generation = self.status.generation
            return result
        if self._motion_requires_fresh_safe_stop:
            raise ValueError("reconnect requires a fresh watchdog safe-stop output")
        write_move(*values)
        return "move"

    def stop(self) -> dict[str, Any]:
        """Request the upstream discrete stop and require an accepted result."""
        result = self._call("robot.stop", {})
        if not isinstance(result, dict) or set(result) - {"accepted", "reason"}:
            raise RobotdProtocolError("robot.stop result has unexpected fields")
        if not isinstance(result.get("accepted"), bool):
            raise RobotdProtocolError("robot.stop result must contain boolean accepted")
        if result.get("reason") is not None and not isinstance(result["reason"], str):
            raise RobotdProtocolError("robot.stop reason must be a string or null")
        if not result["accepted"]:
            raise RobotdRemoteError(-1, result.get("reason") or "robot.stop refused")
        return result

    def enable(self, on: bool) -> dict[str, Any]:
        """Enable or disable official policy execution for controlled fixtures."""
        if type(on) is not bool:
            raise ValueError("on must be boolean")
        result = self._call("robot.enable", {"on": on, "toggle": False})
        if not isinstance(result, dict) or set(result) - {"accepted", "reason"}:
            raise RobotdProtocolError("robot.enable result has unexpected fields")
        if not isinstance(result.get("accepted"), bool):
            raise RobotdProtocolError("robot.enable result must contain boolean accepted")
        if result.get("reason") is not None and not isinstance(result["reason"], str):
            raise RobotdProtocolError("robot.enable reason must be a string or null")
        if not result["accepted"]:
            raise RobotdRemoteError(-1, result.get("reason") or "robot.enable refused")
        return result

    def state(self, *, hz: int = 1) -> dict[str, Any]:
        """Subscribe and return one newly received ``robot.state`` notification."""
        if isinstance(hz, bool) or not isinstance(hz, int) or hz <= 0:
            raise ValueError("hz must be a positive integer")
        accepted = self._call("robot.subscribe", {"hz": hz})
        self._validate_subscribe(accepted)
        if accepted.get("accepted") is not True:
            raise RobotdProtocolError("robot.subscribe returned an unexpected result")

        deadline = time.monotonic() + self.timeout_s
        while True:
            message = self._read_message(deadline)
            if not isinstance(message, dict):
                raise RobotdProtocolError("robotd message must be a JSON object")
            if message.get("jsonrpc") != "2.0":
                raise RobotdProtocolError("robotd message has an invalid jsonrpc version")
            if "id" in message:
                self._validate_wire_id(message["id"])
                # A response to an older request is stale and cannot become state.
                continue
            if message.get("method") != "robot.state":
                continue
            params = message.get("params")
            self._validate_state(params)
            return params

    def close(self) -> None:
        self.disconnect()

    def __enter__(self) -> RobotdClient:
        self.connect()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _call(self, method: str, params: dict[str, Any]) -> Any:
        if method not in _REQUEST_METHODS:
            raise TypeError(f"robotd request method is not exposed: {method}")
        stream = self._require_socket()
        request_id = self._next_id
        self._next_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }
        wire = json.dumps(request, separators=(",", ":"), allow_nan=False).encode() + b"\n"
        deadline = time.monotonic() + self.timeout_s
        try:
            stream.settimeout(self._remaining(deadline))
            stream.sendall(wire)
        except socket.timeout as exc:
            self.disconnect()
            raise RobotdTimeoutError(f"timed out sending {method}") from exc
        except OSError as exc:
            self.disconnect()
            raise RobotdConnectionError(f"connection lost sending {method}: {exc}") from exc

        while True:
            message = self._read_message(deadline)
            if not isinstance(message, dict):
                raise RobotdProtocolError("robotd response must be a JSON object")
            if message.get("jsonrpc") != "2.0":
                raise RobotdProtocolError("robotd response has an invalid jsonrpc version")
            if "id" not in message:
                # State/progress notifications may be interleaved with call responses.
                continue
            response_id = message["id"]
            self._validate_wire_id(response_id)
            if response_id != request_id:
                # A delayed answer is stale. IDs never reset, including across reconnects.
                continue
            has_result = "result" in message
            has_error = "error" in message
            if has_result == has_error:
                raise RobotdProtocolError(
                    "robotd response must contain exactly one of result or error"
                )
            if has_error:
                error = message["error"]
                if (
                    not isinstance(error, dict)
                    or isinstance(error.get("code"), bool)
                    or not isinstance(error.get("code"), int)
                    or not I32_MIN <= error.get("code") <= I32_MAX
                    or not isinstance(error.get("message"), str)
                ):
                    raise RobotdProtocolError("robotd returned an invalid error object")
                raise RobotdRemoteError(error["code"], error["message"])
            return message["result"]

    def _read_message(self, deadline: float) -> Any:
        stream = self._require_socket()
        while True:
            newline = self._buffer.find(b"\n")
            if newline >= 0:
                if newline > MAX_LINE_BYTES:
                    self.disconnect()
                    raise RobotdProtocolError("robotd response exceeds the 64 KiB line limit")
                raw = bytes(self._buffer[:newline])
                del self._buffer[: newline + 1]
                if not raw.strip():
                    continue
                try:
                    message = json.loads(raw, parse_constant=_reject_json_constant)
                    self._reject_nonfinite(message)
                    return message
                except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                    raise RobotdProtocolError("robotd returned malformed JSON") from exc
            if len(self._buffer) > MAX_LINE_BYTES:
                self.disconnect()
                raise RobotdProtocolError("robotd response exceeds the 64 KiB line limit")
            try:
                stream.settimeout(self._remaining(deadline))
                chunk = stream.recv(4096)
            except socket.timeout as exc:
                self.disconnect()
                raise RobotdTimeoutError("timed out waiting for robotd response") from exc
            except OSError as exc:
                self.disconnect()
                raise RobotdConnectionError(f"robotd connection lost: {exc}") from exc
            if not chunk:
                self.disconnect()
                raise RobotdConnectionError("robotd closed the connection")
            self._buffer.extend(chunk)

    def _require_socket(self) -> _Socket:
        if self._socket is None:
            raise RobotdConnectionError("robotd client is not connected")
        return self._socket

    @staticmethod
    def _remaining(deadline: float) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RobotdTimeoutError("robotd operation deadline expired")
        return remaining

    @staticmethod
    def _validate_hello(result: Any) -> None:
        if not isinstance(result, dict):
            raise RobotdProtocolError("hello result must be an object")
        if "daemon_version" not in result or "revision" not in result:
            raise RobotdProtocolError("hello result lacks version identity fields")
        RobotdClient._require_uint(
            result.get("api_version"), "hello api_version", maximum=U32_MAX
        )
        if result.get("daemon_version") is not None and not isinstance(
            result.get("daemon_version"), str
        ):
            raise RobotdProtocolError("hello daemon_version must be a string or null")
        if isinstance(result.get("daemon_version"), str):
            match = _SEMVER.fullmatch(result["daemon_version"])
            if match is None or any(int(part) > U64_MAX for part in match.groups()[:3]):
                raise RobotdProtocolError("hello daemon_version must be valid semantic version")
        if result.get("revision") is not None and not isinstance(result.get("revision"), str):
            raise RobotdProtocolError("hello revision must be a string or null")

    @staticmethod
    def _validate_health(result: Any) -> None:
        if not isinstance(result, dict) or not isinstance(result.get("healthy"), bool):
            raise RobotdProtocolError("robot.health result must contain boolean healthy")
        if "degraded" in result and not isinstance(result["degraded"], bool):
            raise RobotdProtocolError("robot.health degraded must be boolean")
        if result.get("reason") is not None and not isinstance(result.get("reason"), str):
            raise RobotdProtocolError("robot.health reason must be a string or null")
        RobotdClient._validate_optional_object(
            result,
            "battery",
            {"volts": "number", "percent": "number"},
            required={"volts", "percent"},
        )
        RobotdClient._validate_optional_object(
            result,
            "motors",
            {"hottest": str, "max_c": "number", "mean_c": "number"},
            required={"hottest", "max_c", "mean_c"},
        )
        if "cpu_temp_c" in result and result["cpu_temp_c"] is not None:
            RobotdClient._require_finite_number(result["cpu_temp_c"], "robot.health cpu_temp_c")
        control_loop = RobotdClient._validate_optional_object(result, "control_loop", {
            "target_hz": "number",
            "achieved_hz": "optional_number",
            "ticks": "u64",
            "missed": "u64",
            "last_tick_age_ms": "u64",
        })
        if control_loop is not None:
            for field in ("target_hz", "ticks", "missed", "last_tick_age_ms"):
                if field not in control_loop:
                    raise RobotdProtocolError(f"robot.health control_loop lacks {field}")
        RobotdClient._validate_optional_object(
            result,
            "bus",
            {"consecutive_errors": "u32", "startup_failures": "u32"},
            allow_null=False,
        )
        RobotdClient._validate_optional_object(result, "imu", {
            "ready": bool,
            "stale_blocks": "u64",
            "consecutive_stale_blocks": "u64",
        })

    @staticmethod
    def _validate_state(result: Any) -> None:
        if not isinstance(result, dict):
            raise RobotdProtocolError("robot.state params must be an object")
        if isinstance(result.get("t"), bool) or not isinstance(result.get("t"), (int, float)):
            raise RobotdProtocolError("robot.state t must be numeric")
        if not math.isfinite(float(result["t"])):
            raise RobotdProtocolError("robot.state t must be finite")
        move = RobotdClient._require_object(result, "move", "robot.state")
        for field in ("requested", "applied"):
            RobotdClient._require_number_array(move.get(field), 3, f"robot.state move.{field}")
        limited_by = move.get("limited_by", [])
        if not isinstance(limited_by, list) or not all(isinstance(x, str) for x in limited_by):
            raise RobotdProtocolError("robot.state move.limited_by must be a string array")
        RobotdClient._require_number_array(result.get("head"), 4, "robot.state head")
        if not isinstance(result.get("policy"), str):
            raise RobotdProtocolError("robot.state policy must be str")
        safety = RobotdClient._require_object(result, "safety", "robot.state")
        for field in ("fallen", "limp"):
            if not isinstance(safety.get(field), bool):
                raise RobotdProtocolError(f"robot.state safety.{field} must be bool")
        if "gravity" in safety:
            RobotdClient._require_number_array(
                safety["gravity"], 3, "robot.state safety.gravity"
            )
        if "gain" in safety and safety["gain"] is not None:
            RobotdClient._require_uint(
                safety["gain"], "robot.state safety.gain", maximum=U16_MAX
            )
        loop = RobotdClient._require_object(result, "loop", "robot.state")
        RobotdClient._require_finite_number(loop.get("hz"), "robot.state loop.hz")
        RobotdClient._require_uint(
            loop.get("missed"), "robot.state loop.missed", maximum=U64_MAX
        )
        RobotdClient._require_number_array(result.get("joints"), None, "robot.state joints")
        RobotdClient._require_number_array(result.get("targets"), None, "robot.state targets")
        if "odom" in result:
            odom = RobotdClient._require_object(result, "odom", "robot.state")
            RobotdClient._require_number_array(
                odom.get("position"), 3, "robot.state odom.position"
            )
            RobotdClient._require_finite_number(odom.get("yaw"), "robot.state odom.yaw")
        if "t_ns" in result:
            RobotdClient._require_uint(
                result["t_ns"], "robot.state t_ns", maximum=U64_MAX
            )
        RobotdClient._validate_state_imu(result.get("imu"))
        RobotdClient._validate_theremin(result.get("theremin"))
        RobotdClient._validate_chorale(result.get("chorale"))
        if result.get("frames") is not None:
            frames = RobotdClient._require_object(result, "frames", "robot.state")
            for frame_name in ("camera", "tof"):
                if frame_name in frames:
                    RobotdClient._validate_pose(
                        frames[frame_name], f"robot.state frames.{frame_name}"
                    )
            if frames.get("head_imu") is not None:
                RobotdClient._validate_pose(
                    frames["head_imu"], "robot.state frames.head_imu"
                )
        if "skeleton" in result:
            skeleton = result["skeleton"]
            if not isinstance(skeleton, list) or not all(isinstance(item, dict) for item in skeleton):
                raise RobotdProtocolError("robot.state skeleton must be an object array")
            for index, pose in enumerate(skeleton):
                RobotdClient._validate_pose(pose, f"robot.state skeleton[{index}]")

    @staticmethod
    def _require_object(container: dict[str, Any], field: str, context: str) -> dict[str, Any]:
        value = container.get(field)
        if not isinstance(value, dict):
            raise RobotdProtocolError(f"{context} {field} must be dict")
        return value

    @staticmethod
    def _validate_optional_object(
        container: dict[str, Any],
        field: str,
        fields: dict[str, object],
        *,
        required: set[str] | None = None,
        allow_null: bool = True,
    ) -> dict[str, Any] | None:
        if field not in container:
            return None
        value = container[field]
        if value is None and allow_null:
            return None
        if not isinstance(value, dict):
            suffix = " or null" if allow_null else ""
            raise RobotdProtocolError(f"robot.health {field} must be an object{suffix}")
        for child in required or set():
            if child not in value:
                raise RobotdProtocolError(f"robot.health {field} lacks {child}")
        for child, expected in fields.items():
            if child not in value:
                continue
            item = value[child]
            label = f"robot.health {field}.{child}"
            if expected == "number":
                RobotdClient._require_finite_number(item, label)
            elif expected == "optional_number":
                if item is not None:
                    RobotdClient._require_finite_number(item, label)
            elif expected == "u32":
                RobotdClient._require_uint(item, label, maximum=U32_MAX)
            elif expected == "u64":
                RobotdClient._require_uint(item, label, maximum=U64_MAX)
            elif not isinstance(item, expected):
                raise RobotdProtocolError(f"{label} has an unexpected type")
        return value

    @staticmethod
    def _require_finite_number(value: Any, label: str) -> None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise RobotdProtocolError(f"{label} must be numeric")
        if not math.isfinite(float(value)):
            raise RobotdProtocolError(f"{label} must be finite")

    @staticmethod
    def _require_uint(value: Any, label: str, *, maximum: int) -> None:
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 0
            or value > maximum
        ):
            raise RobotdProtocolError(f"{label} must be an integer from 0 through {maximum}")

    @staticmethod
    def _require_number_array(value: Any, length: int | None, label: str) -> None:
        if not isinstance(value, list) or (length is not None and len(value) != length):
            suffix = "" if length is None else f" of length {length}"
            raise RobotdProtocolError(f"{label} must be a numeric array{suffix}")
        for item in value:
            RobotdClient._require_finite_number(item, label)

    @staticmethod
    def _validate_wire_id(value: Any) -> None:
        if isinstance(value, str):
            return
        RobotdClient._require_uint(value, "robotd response id", maximum=U64_MAX)

    @staticmethod
    def _validate_state_imu(value: Any) -> None:
        if value is None:
            return
        if not isinstance(value, dict):
            raise RobotdProtocolError("robot.state imu must be an object or null")
        if "gyro" in value:
            RobotdClient._require_number_array(value["gyro"], 3, "robot.state imu.gyro")
        if "quat" in value:
            RobotdClient._require_number_array(value["quat"], 4, "robot.state imu.quat")

    @staticmethod
    def _validate_subscribe(value: Any) -> None:
        if not isinstance(value, dict):
            raise RobotdProtocolError("robot.subscribe result must be an object")
        if "accepted" in value and not isinstance(value["accepted"], bool):
            raise RobotdProtocolError("robot.subscribe accepted must be boolean")
        for field in ("walk", "stand", "unavailable", "sitstand", "ground_pick"):
            if field in value and value[field] is not None and not isinstance(value[field], str):
                raise RobotdProtocolError(
                    f"robot.subscribe {field} must be a string or null"
                )
        if "skills" in value and (
            not isinstance(value["skills"], list)
            or not all(isinstance(item, str) for item in value["skills"])
        ):
            raise RobotdProtocolError("robot.subscribe skills must be a string array")

    @staticmethod
    def _validate_theremin(value: Any) -> None:
        if value is None:
            return
        if not isinstance(value, dict):
            raise RobotdProtocolError("robot.state theremin must be an object or null")
        for field in ("hand_range_m", "note_hz"):
            if field in value and value[field] is not None:
                RobotdClient._require_finite_number(
                    value[field], f"robot.state theremin.{field}"
                )
        if "mouth" in value:
            RobotdClient._require_finite_number(
                value["mouth"], "robot.state theremin.mouth"
            )
        if "zones" in value:
            RobotdClient._require_uint(
                value["zones"], "robot.state theremin.zones", maximum=U32_MAX
            )
        if "held" in value and not isinstance(value["held"], bool):
            raise RobotdProtocolError("robot.state theremin.held must be boolean")
        if "sensor" in value and value["sensor"] is not None and not isinstance(
            value["sensor"], str
        ):
            raise RobotdProtocolError("robot.state theremin.sensor must be a string or null")

    @staticmethod
    def _validate_chorale(value: Any) -> None:
        if value is None:
            return
        if not isinstance(value, dict):
            raise RobotdProtocolError("robot.state chorale must be an object or null")
        for field in ("listening", "joining"):
            if field in value and not isinstance(value[field], bool):
                raise RobotdProtocolError(f"robot.state chorale.{field} must be boolean")
        if "part" in value and value["part"] is not None and not isinstance(value["part"], str):
            raise RobotdProtocolError("robot.state chorale.part must be a string or null")
        if "beats" in value and value["beats"] is not None:
            RobotdClient._require_finite_number(value["beats"], "robot.state chorale.beats")
        if "voices" in value:
            RobotdClient._require_uint(
                value["voices"], "robot.state chorale.voices", maximum=U32_MAX
            )

    @staticmethod
    def _validate_pose(value: Any, label: str) -> None:
        if not isinstance(value, dict):
            raise RobotdProtocolError(f"{label} must be an object")
        if "pos" in value:
            RobotdClient._require_number_array(value["pos"], 3, f"{label}.pos")
        if "quat" in value:
            RobotdClient._require_number_array(value["quat"], 4, f"{label}.quat")

    @staticmethod
    def _reject_nonfinite(value: Any, path: str = "$") -> None:
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f"non-finite number at {path}")
        if isinstance(value, list):
            for index, item in enumerate(value):
                RobotdClient._reject_nonfinite(item, f"{path}[{index}]")
        elif isinstance(value, dict):
            for key, item in value.items():
                RobotdClient._reject_nonfinite(item, f"{path}.{key}")
