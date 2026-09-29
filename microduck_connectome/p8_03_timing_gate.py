"""Development-only shared READY barrier for a scored timing probe."""

from __future__ import annotations

import threading


class TimingGateError(RuntimeError):
    """The probe workers cannot enter a common scored interval."""


class ReadyStartGate:
    """Release named workers at one durable, externally chosen arm timestamp.

    All participants must be waiting before the caller can release the gate.
    The caller writes the arm marker and revalidates moving/health conditions
    before supplying ``arm_ns``.  A failed preparation aborts every waiter.
    """

    def __init__(self, participants: int):
        if type(participants) is not int or participants < 1:
            raise ValueError("participants must be positive")
        self.participants = participants
        self._lock = threading.Lock()
        self._arrived: set[str] = set()
        self._ready = threading.Event()
        self._release = threading.Event()
        self._arm_ns: int | None = None
        self._aborted = False

    def arrive_and_wait(self, name: str, timeout_s: float = 10.0) -> int:
        self.mark_ready(name)
        if not self._release.wait(timeout_s):
            self.abort()
            raise TimingGateError("READY barrier release timed out")
        with self._lock:
            if self._aborted or self._arm_ns is None:
                raise TimingGateError("READY barrier aborted")
            return self._arm_ns

    def mark_ready(self, name: str) -> None:
        """Register a worker that must keep working before scored arm."""
        if not name:
            raise TimingGateError("worker name is required")
        with self._lock:
            if self._aborted or self._release.is_set() or name in self._arrived:
                raise TimingGateError("worker arrived after release, abort, or twice")
            self._arrived.add(name)
            if len(self._arrived) == self.participants:
                self._ready.set()

    def wait_ready(self, timeout_s: float) -> bool:
        return self._ready.wait(timeout_s)

    def release(self, arm_ns: int) -> None:
        if type(arm_ns) is not int or arm_ns < 0:
            raise TimingGateError("arm_ns must be a nonnegative monotonic timestamp")
        with self._lock:
            if self._aborted or not self._ready.is_set() or self._release.is_set():
                raise TimingGateError("all workers must be READY before arm")
            self._arm_ns = arm_ns
            self._release.set()

    def abort(self) -> None:
        with self._lock:
            self._aborted = True
            self._release.set()

    @property
    def arrived(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._arrived))

    @property
    def arm_ns(self) -> int | None:
        with self._lock:
            return self._arm_ns
