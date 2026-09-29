"""Development-only, instrumented P8-03 motion refresh coordinator.

The caller owns robotd and the motion arbiter. ``send_move`` must use that
arbiter and return its (result, call_ns, write_ns, ack_ns) tuple. Observation
callbacks only read robotd state and body pose; they never issue commands.
"""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable, Mapping


class MotionTimingError(RuntimeError):
    pass


class MotionTimingCoordinator:
    def __init__(self, *, send_move: Callable[[], tuple],
                 observe_state: Callable[[int], Mapping],
                 observe_pose: Callable[[int], Mapping],
                 fault: Callable[[str], None], period_ns: int = 20_000_000,
                 max_observation_age_ns: int = 100_000_000,
                 queue_capacity: int = 8,
                 clock_ns: Callable[[], int] = time.monotonic_ns,
                 wait_until: Callable[[int, threading.Event], None] | None = None,
                 gate: object | None = None, scored_slots: int = 50):
        if (period_ns <= 0 or max_observation_age_ns <= 0 or queue_capacity <= 0
                or scored_slots <= 0):
            raise ValueError("timing and queue limits must be positive")
        self.send_move = send_move
        self.observe_state = observe_state
        self.observe_pose = observe_pose
        self.fault = fault
        self.period_ns = period_ns
        self.max_observation_age_ns = max_observation_age_ns
        self.clock_ns = clock_ns
        self.wait_until = wait_until or self._wait_until
        self.gate = gate
        self.scored_slots = scored_slots
        self._state_queue: queue.Queue[int] = queue.Queue(maxsize=queue_capacity)
        self._pose_queue: queue.Queue[int] = queue.Queue(maxsize=queue_capacity)
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._command_lock = threading.Lock()
        self._workers_ready = {name: threading.Event() for name in ("motion", "state", "pose")}
        self._lock = threading.Lock()
        self._threads: list[threading.Thread] = []
        self._rows: list[dict] = []
        self._arm_ns: int | None = None
        self._first_ack_ns: int | None = None
        self._last_ack_ns: int | None = None
        self._last_observed_ns = {"state": None, "pose": None}
        self._missed_periods = 0
        self._scored_slots_sent = 0
        self._late_periods = 0
        self._queue_drops = 0
        self._fault_reason: str | None = None

    def _wait_until(self, deadline_ns: int, stop: threading.Event) -> None:
        stop.wait(max(0, (deadline_ns - self.clock_ns()) / 1e9))

    def _record(self, row: dict) -> None:
        with self._lock:
            self._rows.append(row)

    def _fail(self, reason: str) -> None:
        with self._lock:
            if self._fault_reason is not None:
                return
            self._fault_reason = reason
            self._rows.append({"kind": "motion_fault", "timestamp_ns": self.clock_ns(),
                               "reason": reason, "thread_id": threading.get_ident()})
        self._stop.set()
        self.fault(reason)

    def _observe(self, kind: str, pending: queue.Queue[int], callback: Callable) -> None:
        self._workers_ready[kind].set()
        if self.gate is not None:
            self.gate.mark_ready(kind)
        while not self._stop.is_set():
            try:
                ack_ns = pending.get(timeout=.01)
            except queue.Empty:
                continue
            started_ns = self.clock_ns()
            try:
                value = callback(ack_ns)
                completed_ns = self.clock_ns()
                if not isinstance(value, Mapping) or type(value.get("timestamp_ns")) is not int:
                    raise MotionTimingError(f"{kind} observation lacks source timestamp")
                source_ns = value["timestamp_ns"]
                if source_ns > completed_ns or completed_ns - source_ns > self.max_observation_age_ns:
                    raise MotionTimingError(f"{kind} observation stale")
                with self._lock:
                    self._last_observed_ns[kind] = completed_ns
                    depth = pending.qsize()
                    self._rows.append({"kind": f"{kind}_observation",
                                       "timestamp_ns": completed_ns,
                                       "source_timestamp_ns": source_ns,
                                       "move_ack_ns": ack_ns,
                                       "started_ns": started_ns,
                                       "thread_id": threading.get_ident(),
                                       "queue_depth": depth, "value": dict(value)})
            except BaseException as error:
                self._fail(f"{kind}_observation_failed:{type(error).__name__}:{error}")
                return

    def _move(self) -> None:
        self._workers_ready["motion"].set()
        if self.gate is not None:
            self.gate.mark_ready("motion")
        deadline = self.clock_ns()
        period_index = 0
        scored_index: int | None = None
        while not self._stop.is_set():
            arm_ns = self.gate.arm_ns if self.gate is not None else self._arm_ns
            if arm_ns is not None and scored_index is None:
                # Switch phase at arm. The first genuine move occupies slot 0;
                # no pre-arm ACK is recounted and no missed slot is backfilled.
                scored_index = 0
                deadline = arm_ns
                with self._lock:
                    self._rows.append({"kind": "motion_arm", "timestamp_ns": arm_ns,
                                       "thread_id": threading.get_ident(),
                                       "last_move_ack_ns": self._last_ack_ns,
                                       "handoff_gap_ns": (arm_ns - self._last_ack_ns
                                                          if self._last_ack_ns is not None else None)})
            # Poll arm while keeping the pre-arm 20 ms refresh; the release
            # event never blocks the move worker behind observer I/O.
            wait_deadline = (min(deadline, self.clock_ns() + 1_000_000)
                             if scored_index is None else deadline)
            self.wait_until(wait_deadline, self._stop)
            if self._stop.is_set():
                break
            wake_ns = self.clock_ns()
            if scored_index is None and wake_ns < deadline:
                continue
            if scored_index is None and self.gate is not None and self.gate.arm_ns is not None:
                continue
            if wake_ns >= deadline + self.period_ns:
                skipped = (wake_ns - deadline) // self.period_ns
                with self._lock:
                    self._missed_periods += skipped
                self._fail(f"motion_deadline_missed:{skipped}")
                break
            if wake_ns > deadline:
                with self._lock:
                    self._late_periods += 1
            self._command_lock.acquire()
            try:
                if scored_index is None and self.gate is not None and self.gate.arm_ns is not None:
                    continue
                result, call_ns, write_ns, ack_ns = self.send_move()
                if result is None or (isinstance(result, Mapping)
                                      and result.get("accepted") is False):
                    raise MotionTimingError("move was not acknowledged")
                if not (type(call_ns) is type(write_ns) is type(ack_ns) is int
                        and wake_ns <= call_ns <= write_ns <= ack_ns <= self.clock_ns()):
                    raise MotionTimingError("invalid move call/ACK timestamps")
                if (scored_index is None and self.gate is not None
                        and self.gate.arm_ns is not None and ack_ns >= self.gate.arm_ns):
                    self._fail("arm_race_prearm_ack_after_arm")
                    return
                if ack_ns >= deadline + self.period_ns:
                    with self._lock:
                        self._missed_periods += (ack_ns - deadline) // self.period_ns
                    self._fail("motion_slot_missed:ACK_after_next_deadline")
                    return
                with self._lock:
                    if self._first_ack_ns is None:
                        self._first_ack_ns = ack_ns
                    self._last_ack_ns = ack_ns
                    phase = ("prearm" if scored_index is None else
                             "scored" if scored_index < self.scored_slots else "postscore")
                    if phase == "scored":
                        self._scored_slots_sent += 1
                    self._rows.append({"kind": "motion_refresh", "timestamp_ns": ack_ns,
                                       "period_index": period_index,
                                       "scored_slot": scored_index if phase == "scored" else None,
                                       "scheduled_deadline_ns": deadline,
                                       "wake_ns": wake_ns, "move_call_ns": call_ns,
                                       "move_write_ns": write_ns, "move_ack_ns": ack_ns,
                                       "result": result, "phase": phase,
                                       "thread_id": threading.get_ident(),
                                       "state_queue_depth": self._state_queue.qsize(),
                                       "pose_queue_depth": self._pose_queue.qsize()})
                for pending in (self._state_queue, self._pose_queue):
                    try:
                        pending.put_nowait(ack_ns)
                    except queue.Full:
                        with self._lock:
                            self._queue_drops += 1
                        self._fail("observation_queue_overflow")
                        return
                self._ready.set()
                now_ns = self.clock_ns()
                with self._lock:
                    last = dict(self._last_observed_ns)
                for kind, observed_ns in last.items():
                    reference_ns = observed_ns if observed_ns is not None else self._first_ack_ns
                    if reference_ns is not None and now_ns - reference_ns > self.max_observation_age_ns:
                        self._fail(f"{kind}_observation_timeout")
                        return
            except BaseException as error:
                self._fail(f"move_failed:{type(error).__name__}:{error}")
                return
            finally:
                self._command_lock.release()
            period_index += 1
            if scored_index is not None:
                scored_index += 1
                deadline = arm_ns + scored_index * self.period_ns
            else:
                deadline += self.period_ns

    def start(self) -> None:
        if self._threads:
            raise MotionTimingError("coordinator is single-use")
        self._threads = [
            threading.Thread(target=self._observe, args=("state", self._state_queue,
                             self.observe_state), name="p8-state-observer", daemon=True),
            threading.Thread(target=self._observe, args=("pose", self._pose_queue,
                             self.observe_pose), name="p8-pose-observer", daemon=True),
            threading.Thread(target=self._move, name="p8-motion-refresh", daemon=True),
        ]
        for thread in self._threads:
            thread.start()

    def wait_ready(self, timeout_s: float) -> bool:
        deadline = time.monotonic() + timeout_s
        for worker_ready in self._workers_ready.values():
            if not worker_ready.wait(max(0, deadline - time.monotonic())):
                return False
        return self._ready.wait(max(0, deadline - time.monotonic())) and self._fault_reason is None

    def arm(self, arm_ns: int) -> None:
        with self._lock:
            if self.gate is not None:
                raise MotionTimingError("release the shared gate to arm")
            if not self._ready.is_set() or self._fault_reason is not None:
                raise MotionTimingError("cannot arm before healthy motion READY")
            if self._arm_ns is not None or type(arm_ns) is not int or arm_ns < self._first_ack_ns:
                raise MotionTimingError("invalid or duplicate arm timestamp")
            self._arm_ns = arm_ns

    def release_arm(self, prepare_callback: Callable[[], None],
                    at_arm: Callable[[int], None] | None = None) -> int:
        """Atomically validate and release arm between genuine move RPCs.

        The caller must persist the durable ARMED marker first. A slow
        validation is visible as a missed motion deadline, never concealed.
        """
        if self.gate is None:
            raise MotionTimingError("shared gate is required for release_arm")
        with self._command_lock:
            if not self.wait_ready(0):
                raise MotionTimingError("cannot release arm before motion READY")
            try:
                prepare_callback()
                arm_ns = self.clock_ns()
                if at_arm is not None:
                    at_arm(arm_ns)
                self.gate.release(arm_ns)
                return arm_ns
            except BaseException as error:
                self.gate.abort()
                self._fail(f"arm_prepare_failed:{type(error).__name__}:{error}")
                raise

    def stop(self, timeout_s: float = 2.0) -> dict:
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout_s)
        if any(thread.is_alive() for thread in self._threads):
            self._fail("motion_worker_join_timeout")
        return self.snapshot()

    def snapshot(self) -> dict:
        with self._lock:
            return {"rows": list(self._rows), "arm_ns": self.gate.arm_ns if self.gate
                    is not None else self._arm_ns,
                    "first_move_ack_ns": self._first_ack_ns,
                    "last_move_ack_ns": self._last_ack_ns,
                    "missed_periods": self._missed_periods,
                    "scored_slots_sent": self._scored_slots_sent,
                    "late_periods": self._late_periods,
                    "queue_drops": self._queue_drops,
                    "fault_reason": self._fault_reason,
                    "state_queue_depth": self._state_queue.qsize(),
                    "pose_queue_depth": self._pose_queue.qsize()}
