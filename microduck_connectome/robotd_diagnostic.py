"""Fail-closed, lossless capture of robotd diagnostic state and move lineage.

This module only observes robotd. A command sender may record its exact wire
request and ACK here; motor authority remains with robotd.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import time
from typing import Any

from .robotd_client import RobotdClient, RobotdProtocolError, U64_MAX


class RobotdDiagnosticRecorder:
    """One dedicated subscription and one append-only, synced JSONL ledger."""

    def __init__(self, client: RobotdClient, path: str | Path) -> None:
        if client.status.connected:
            raise ValueError("diagnostic client must start disconnected and dedicated")
        self.client = client
        self.path = Path(path)
        self._file: Any = None
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._error: BaseException | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Return only after the first contiguous state is durable, before acquisition."""
        if self._thread is not None:
            raise RuntimeError("diagnostic recorder already started")
        self._file = self.path.open("x", encoding="utf-8", newline="\n")
        self._thread = threading.Thread(target=self._read_states, name="robotd-diagnostic", daemon=True)
        self._thread.start()
        if not self._ready.wait(self.client.timeout_s * 2):
            self.close()
            raise RobotdProtocolError("diagnostic stream did not deliver an initial state")
        try:
            self.assert_healthy()
        except BaseException:
            self.close()
            raise

    def _read_states(self) -> None:
        try:
            self.client.connect()
            while not self._stop.is_set():
                state = self.client.diagnostic_state(
                    on_frame=self._record_state, on_raw=self._record_raw
                )
                if state["control_tick_sequence"] > 0:
                    self._ready.set()
        except BaseException as exc:
            if not self._stop.is_set():
                try:
                    self._append({"kind": "diagnostic.failure", "error": str(exc)})
                except BaseException:
                    pass
                self._error = exc
                self._ready.set()
        finally:
            self.client.disconnect()

    def _record_state(self, state: dict[str, Any]) -> None:
        self._append({"kind": "robot.state",
                      "received_at_ns": time.clock_gettime_ns(time.CLOCK_MONOTONIC),
                      "state": state})

    def _record_raw(self, raw_line: bytes) -> None:
        self._append({"kind": "robotd.wire", "received_at_ns":
                      time.clock_gettime_ns(time.CLOCK_MONOTONIC),
                      "wire_hex": raw_line.hex()})

    def record_move_request(self, raw_line: bytes, *, sent_at_ns: int) -> None:
        """Persist the exact request bytes before sending them to robotd."""
        request = self._parse_wire(raw_line)
        if request.get("method") != "robot.move" or "id" not in request:
            raise RobotdProtocolError("diagnostic move request must have method and id")
        self._require_ns(sent_at_ns)
        self.assert_healthy()
        self._append({"kind": "robot.move.request", "sent_at_ns": sent_at_ns,
                      "wire": raw_line.decode("utf-8")})

    def record_move_ack(self, raw_line: bytes, *, received_at_ns: int) -> None:
        """Persist the exact ACK, including its accepted generation or refusal."""
        response = self._parse_wire(raw_line)
        if "id" not in response or ("result" in response) == ("error" in response):
            raise RobotdProtocolError("diagnostic move ACK is malformed")
        result = response.get("result")
        if "result" in response and (not isinstance(result, dict)
                                     or type(result.get("accepted")) is not bool):
            raise RobotdProtocolError("diagnostic move ACK lacks acceptance result")
        if isinstance(result, dict) and result.get("accepted") is True:
            generation = result.get("accepted_move_generation")
            if type(generation) is not int or not 1 <= generation <= U64_MAX:
                raise RobotdProtocolError("accepted move ACK lacks generation")
        elif isinstance(result, dict) and "accepted_move_generation" in result:
            raise RobotdProtocolError("rejected move ACK carries an accepted generation")
        self._require_ns(received_at_ns)
        self.assert_healthy()
        self._append({"kind": "robot.move.ack", "received_at_ns": received_at_ns,
                      "wire": raw_line.decode("utf-8")})

    @staticmethod
    def _parse_wire(raw_line: bytes) -> dict[str, Any]:
        try:
            value = json.loads(raw_line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RobotdProtocolError("diagnostic wire record is not JSON") from exc
        if not isinstance(value, dict) or value.get("jsonrpc") != "2.0":
            raise RobotdProtocolError("diagnostic wire record is not JSON-RPC")
        return value

    @staticmethod
    def _require_ns(value: int) -> None:
        if type(value) is not int or not 0 <= value <= U64_MAX:
            raise ValueError("event timestamp must be a uint64 nanosecond value")

    def _append(self, record: dict[str, Any]) -> None:
        with self._lock:
            if self._file is None:
                raise RuntimeError("diagnostic recorder is not open")
            self._file.write(json.dumps(record, separators=(",", ":"), allow_nan=False) + "\n")
            self._file.flush()
            os.fsync(self._file.fileno())

    def assert_healthy(self) -> None:
        if self._error is not None:
            raise RobotdProtocolError(f"diagnostic stream failed: {self._error}") from self._error
        if self._thread is None or not self._thread.is_alive():
            raise RobotdProtocolError("diagnostic stream is not running")

    def close(self) -> None:
        self._stop.set()
        self.client.disconnect()
        if self._thread is not None:
            self._thread.join(timeout=self.client.timeout_s * 2)
            if self._thread.is_alive():
                raise RobotdProtocolError("diagnostic stream did not stop")
        with self._lock:
            if self._file is not None:
                self._file.close()
                self._file = None

    def __enter__(self) -> RobotdDiagnosticRecorder:
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
