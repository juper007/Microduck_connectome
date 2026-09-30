"""Fail-closed capture of the un-decimated robotd diagnostic stream.

The reader never waits for disk persistence. A single bounded writer preserves
wire, parsed-state, request, and ACK order; successful close drains and fsyncs.
"""

from __future__ import annotations

import copy
from collections import deque
import json
import os
from pathlib import Path
import queue
import threading
import time
from typing import Any

from .robotd_client import RobotdClient, RobotdProtocolError, U64_MAX


class RobotdDiagnosticRecorder:
    """Dedicated reader plus bounded, ordered, checkpointed evidence writer."""

    QUEUE_CAPACITY = 256
    CHECKPOINT_RECORDS = 16
    CHECKPOINT_NS = 20_000_000
    MAX_UNCOMMITTED_NS = 100_000_000

    def __init__(self, client: RobotdClient, path: str | Path) -> None:
        if client.status.connected:
            raise ValueError("diagnostic client must start disconnected and dedicated")
        self.client = client
        self.path = Path(path)
        self._file: Any = None
        self._queue: queue.Queue[tuple[dict[str, Any], threading.Event | None]] = (
            queue.Queue(maxsize=self.QUEUE_CAPACITY)
        )
        self._progress_lock = threading.Lock()
        self._uncommitted: deque[tuple[int, int]] = deque()
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._reader_done = threading.Event()
        self._error: BaseException | None = None
        self._thread: threading.Thread | None = None
        self._writer_thread: threading.Thread | None = None
        self.max_queue_depth = 0
        self.enqueued_records = 0
        self.written_records = 0
        self.synced_records = 0
        self.writer_timings_ns: list[dict[str, int]] = []
        self.callback_durations_ns: list[int] = []

    def start(self) -> None:
        """Return after the first valid state and its preceding wire are durable."""
        if self._thread is not None:
            raise RuntimeError("diagnostic recorder already started")
        self._file = self.path.open("xb", buffering=0)
        self._writer_thread = threading.Thread(
            target=self._write_records, name="robotd-diagnostic-writer", daemon=True
        )
        self._writer_thread.start()
        self._thread = threading.Thread(
            target=self._read_states, name="robotd-diagnostic-reader", daemon=True
        )
        self._thread.start()
        if not self._ready.wait(self.client.timeout_s * 2):
            self.close()
            raise RobotdProtocolError("diagnostic stream did not deliver an initial state")
        try:
            self.assert_healthy()
            self.checkpoint()
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
                self._error = exc
                try:
                    self._enqueue({"kind": "diagnostic.failure", "error": str(exc)},
                                  allow_failed=True)
                except BaseException:
                    pass
                self._ready.set()
        finally:
            self.client.disconnect()
            self._reader_done.set()

    def _record_state(self, state: dict[str, Any]) -> None:
        start = time.monotonic_ns()
        observed_ns = self.client._last_message_observed_ns
        if observed_ns is None:
            raise RobotdProtocolError("diagnostic state has no reader observation")
        self._enqueue({
            "kind": "robot.state", "received_at_ns": observed_ns,
            "reader_observed_ns": observed_ns, "state": copy.deepcopy(state),
        })
        self.callback_durations_ns.append(time.monotonic_ns() - start)

    def _record_raw(self, raw_line: bytes) -> None:
        start = time.monotonic_ns()
        observed_ns = self.client._last_message_observed_ns
        if observed_ns is None:
            raise RobotdProtocolError("diagnostic wire has no reader observation")
        self._enqueue({
            "kind": "robotd.wire", "received_at_ns": observed_ns,
            "reader_observed_ns": observed_ns, "wire_bytes": bytes(raw_line),
        })
        self.callback_durations_ns.append(time.monotonic_ns() - start)

    def record_move_request(self, raw_line: bytes, *, sent_at_ns: int) -> None:
        """Sync the exact request before its caller sends it to robotd."""
        request = self._parse_wire(raw_line)
        if request.get("method") != "robot.move" or "id" not in request:
            raise RobotdProtocolError("diagnostic move request must have method and id")
        self._require_ns(sent_at_ns)
        self._sync_record({"kind": "robot.move.request", "sent_at_ns": sent_at_ns,
                           "wire": raw_line.decode("utf-8")})

    def record_move_ack(self, raw_line: bytes, *, received_at_ns: int) -> None:
        """Sync the exact ACK before its caller judges the move outcome."""
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
        self._sync_record({"kind": "robot.move.ack", "received_at_ns": received_at_ns,
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

    def _enqueue(self, record: dict[str, Any], *,
                 done: threading.Event | None = None,
                 allow_failed: bool = False) -> None:
        if not allow_failed:
            self.assert_healthy()
        # The queue holds immutable wire bytes and a private state copy. The
        # writer alone performs JSON encoding and all file operations.
        with self._progress_lock:
            record["queue_depth_at_enqueue"] = self._queue.qsize() + 1
            try:
                self._queue.put_nowait((record, done))
            except queue.Full as exc:
                self._error = RobotdProtocolError("diagnostic evidence queue overflow")
                raise self._error from exc
            self.enqueued_records += 1
            self._uncommitted.append((self.enqueued_records, time.monotonic_ns()))
            self.max_queue_depth = max(self.max_queue_depth, self._queue.qsize())

    def checkpoint(self) -> None:
        """Durably fence all records enqueued before this call."""
        done = threading.Event()
        self._enqueue({"kind": "diagnostic.checkpoint"}, done=done)
        while not done.wait(0.01):
            if self._error is not None or self._writer_thread is None or not self._writer_thread.is_alive():
                self.assert_healthy()
        self.assert_healthy()

    def _sync_record(self, record: dict[str, Any]) -> None:
        done = threading.Event()
        self._enqueue(record, done=done)
        while not done.wait(0.01):
            self.assert_healthy()
        self.assert_healthy()

    def _fsync(self) -> tuple[int, int]:
        assert self._file is not None
        flush_start = time.monotonic_ns()
        self._file.flush()
        flush_end = time.monotonic_ns()
        os.fsync(self._file.fileno())
        with self._progress_lock:
            self.synced_records = self.written_records
            while self._uncommitted and self._uncommitted[0][0] <= self.synced_records:
                self._uncommitted.popleft()
        return flush_end - flush_start, time.monotonic_ns() - flush_end

    def _write_records(self) -> None:
        pending: list[threading.Event] = []
        last_sync = time.monotonic_ns()
        unsynced = 0
        try:
            while not (self._reader_done.is_set() and self._queue.empty()):
                try:
                    record, done = self._queue.get(timeout=self.CHECKPOINT_NS / 1e9)
                except queue.Empty:
                    record = None
                    done = None
                if record is not None:
                    if "wire_bytes" in record:
                        record["wire_hex"] = record.pop("wire_bytes").hex()
                    serial_start = time.monotonic_ns()
                    data = (json.dumps(record, separators=(",", ":"), allow_nan=False)
                            + "\n").encode("utf-8")
                    serial_end = time.monotonic_ns()
                    assert self._file is not None
                    self._file.write(data)
                    write_end = time.monotonic_ns()
                    self.written_records += 1
                    unsynced += 1
                    if done is not None:
                        pending.append(done)
                    timing = {
                        "serialize_ns": serial_end - serial_start,
                        "write_ns": write_end - serial_end,
                        "flush_ns": 0, "fsync_ns": 0,
                    }
                    self.writer_timings_ns.append(timing)
                    self._queue.task_done()
                else:
                    timing = None
                now = time.monotonic_ns()
                if unsynced and (pending or unsynced >= self.CHECKPOINT_RECORDS
                                 or now - last_sync >= self.CHECKPOINT_NS
                                 or (self._reader_done.is_set() and self._queue.empty())):
                    flush_ns, fsync_ns = self._fsync()
                    if timing is not None:
                        timing["flush_ns"] = flush_ns
                        timing["fsync_ns"] = fsync_ns
                    unsynced = 0
                    last_sync = time.monotonic_ns()
                    for event in pending:
                        event.set()
                    pending.clear()
            if unsynced:
                self._fsync()
        except BaseException as exc:
            self._error = exc
            for event in pending:
                event.set()

    def assert_healthy(self) -> None:
        if self._error is not None:
            raise RobotdProtocolError(f"diagnostic stream failed: {self._error}") from self._error
        with self._progress_lock:
            if (self._uncommitted and
                    time.monotonic_ns() - self._uncommitted[0][1] > self.MAX_UNCOMMITTED_NS):
                self._error = RobotdProtocolError("diagnostic evidence checkpoint overdue")
                raise self._error
        if self._thread is None or not self._thread.is_alive():
            raise RobotdProtocolError("diagnostic stream is not running")
        if self._writer_thread is None or not self._writer_thread.is_alive():
            raise RobotdProtocolError("diagnostic evidence writer is not running")

    def close(self) -> None:
        self._stop.set()
        self.client.disconnect()
        if self._thread is not None:
            self._thread.join(timeout=self.client.timeout_s * 2)
            if self._thread.is_alive():
                raise RobotdProtocolError("diagnostic stream did not stop")
        self._reader_done.set()
        if self._writer_thread is not None:
            self._writer_thread.join(timeout=self.client.timeout_s * 2)
            if self._writer_thread.is_alive():
                raise RobotdProtocolError("diagnostic evidence writer did not drain")
        if self._file is not None:
            self._file.close()
            self._file = None
        if self._error is not None:
            raise RobotdProtocolError(f"diagnostic stream failed: {self._error}") from self._error

    def __enter__(self) -> RobotdDiagnosticRecorder:
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
