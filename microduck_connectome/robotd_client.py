"""Bounded read-only client for MicroDuck's official robotd JSON-RPC socket.

The wire contract in this module is derived from MicroDuck commit
344925c9f8fa031f85428a305b1e8ec2eaae29c1.  P6-02 deliberately exposes only
``hello``, ``robot.health`` and the ``robot.subscribe``/``robot.state`` stream.
Motion transport belongs to P6-03.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import socket
import time
from typing import Any, Callable, Protocol


DEFAULT_ROBOTD_SOCKET = "/run/robotd.sock"
ROBOTD_API_VERSION = 31
MAX_LINE_BYTES = 64 * 1024


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

    def state(self, *, hz: int = 1) -> dict[str, Any]:
        """Subscribe and return one newly received ``robot.state`` notification."""
        if isinstance(hz, bool) or not isinstance(hz, int) or hz <= 0:
            raise ValueError("hz must be a positive integer")
        accepted = self._call("robot.subscribe", {"hz": hz})
        if not isinstance(accepted, dict) or accepted.get("accepted") is not True:
            raise RobotdProtocolError("robot.subscribe returned an unexpected result")

        deadline = time.monotonic() + self.timeout_s
        while True:
            message = self._read_message(deadline)
            if not isinstance(message, dict):
                raise RobotdProtocolError("robotd message must be a JSON object")
            if message.get("jsonrpc") != "2.0":
                raise RobotdProtocolError("robotd message has an invalid jsonrpc version")
            if "id" in message:
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
            if isinstance(response_id, bool) or not isinstance(response_id, (int, str)):
                raise RobotdProtocolError("robotd response has an invalid id")
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
                raw = bytes(self._buffer[:newline])
                del self._buffer[: newline + 1]
                if not raw.strip():
                    continue
                try:
                    return json.loads(raw)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
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
        if isinstance(result.get("api_version"), bool) or not isinstance(
            result.get("api_version"), int
        ):
            raise RobotdProtocolError("hello result has no integer api_version")
        if result.get("daemon_version") is not None and not isinstance(
            result.get("daemon_version"), str
        ):
            raise RobotdProtocolError("hello daemon_version must be a string or null")
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

    @staticmethod
    def _validate_state(result: Any) -> None:
        if not isinstance(result, dict):
            raise RobotdProtocolError("robot.state params must be an object")
        required_types: dict[str, type] = {
            "move": dict,
            "head": list,
            "policy": str,
            "safety": dict,
            "loop": dict,
            "joints": list,
            "targets": list,
        }
        if isinstance(result.get("t"), bool) or not isinstance(result.get("t"), (int, float)):
            raise RobotdProtocolError("robot.state t must be numeric")
        if not math.isfinite(float(result["t"])):
            raise RobotdProtocolError("robot.state t must be finite")
        for field, expected in required_types.items():
            if not isinstance(result.get(field), expected):
                raise RobotdProtocolError(
                    f"robot.state {field} must be {expected.__name__}"
                )
        if len(result["head"]) != 4:
            raise RobotdProtocolError("robot.state head must contain four joints")
        if "t_ns" in result and (
            isinstance(result["t_ns"], bool)
            or not isinstance(result["t_ns"], int)
            or result["t_ns"] < 0
        ):
            raise RobotdProtocolError("robot.state t_ns must be a non-negative integer")
