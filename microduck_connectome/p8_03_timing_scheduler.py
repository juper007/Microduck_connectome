"""Development-only fixed-slot P8 timing scheduler with raw deadline evidence."""

from __future__ import annotations

import threading

from .neural_stop_scheduler import NeuralStopRefreshScheduler
from .p8_03_timing_gate import ReadyStartGate
from .scheduler import NeuralUpdate, SchedulerError


class ReadyTimingScheduler(NeuralStopRefreshScheduler):
    """Run real producers in 50 absolute 20 ms slots after a READY barrier.

    An overdue slot is attempted and recorded late; it is never fabricated,
    backfilled, or counted as a successful on-time slot.  Probe scoring checks
    completion, output lineage, and every slot independently of this summary.
    """

    def __init__(self, *, start_gate: ReadyStartGate, slots: int = 50, **kwargs):
        if type(slots) is not int or slots < 1:
            raise ValueError("slots must be positive")
        super().__init__(**kwargs)
        self.start_gate = start_gate
        self.slots = slots
        self.timing_rows: list[dict] = []
        self._timing_lock = threading.Lock()
        self._scored_arm_ns: int | None = None
        self._neural_slot_complete = [threading.Event() for _ in range(slots)]

    def _periodic(self, domain, hz, step):
        try:
            arm_ns = self.start_gate.arrive_and_wait(f"scheduler:{domain}")
            self._scored_arm_ns = arm_ns
            period_ns = 1_000_000_000 // hz
            for slot in range(self.slots):
                if self._stop.is_set():
                    break
                deadline_ns = arm_ns + slot * period_ns
                wait_ns = deadline_ns - self.clock_ns()
                if wait_ns > 0 and self._stop.wait(wait_ns / 1e9):
                    break
                wake_ns = self.clock_ns()
                if domain == "watchdog":
                    # Publication in slot k must consume that slot's real
                    # neural result, never the pre-arm prime or an older tick.
                    remaining_ns = deadline_ns + period_ns - wake_ns
                    if (remaining_ns <= 0 or not self._neural_slot_complete[slot].wait(
                            remaining_ns / 1e9)):
                        raise SchedulerError(f"neural slot {slot} unavailable for control")
                started_ns = self.clock_ns()
                step(started_ns)
                complete_ns = self.clock_ns()
                if domain == "neural":
                    self._neural_slot_complete[slot].set()
                self._metrics.record(domain, started_ns, complete_ns)
                late = complete_ns >= deadline_ns + period_ns
                if late:
                    self._metrics.missed(domain, 1)
                with self._timing_lock:
                    self.timing_rows.append({
                        "kind": "scheduled_tick", "domain": domain, "slot": slot,
                        "scheduled_deadline_ns": deadline_ns,
                        "worker_wake_ns": wake_ns,
                        "step_start_ns": started_ns,
                        "tick_complete_ns": complete_ns,
                        "thread_id": threading.get_ident(),
                        "late_or_overrun": late,
                    })
        except BaseException as error:
            self._fail(domain, error)

    def _neural_tick(self, now_ns):
        # The production neural scheduler takes this lock before calling the
        # graph. Measure that outer acquisition; a span inside LoomingChain
        # alone would miss contention because its nested lock is reentrant.
        waiting_ns = self.clock_ns()
        with self.motion_arbiter.lock:
            acquired_ns = self.clock_ns()
            try:
                queue_enter_ns = self.clock_ns()
                frame, published_ns, _ = self._perception.get()
                queue_return_ns = self.clock_ns()
                if published_ns is None or now_ns - published_ns > 100_000_000:
                    frame = None
                update = self.neural_step(frame, now_ns)
                if update is None:
                    self._metrics.increment("dropped_neural")
                elif not isinstance(update, NeuralUpdate):
                    raise SchedulerError("neural_step must return NeuralUpdate or None")
                else:
                    self._neural.put(update, now_ns)
            finally:
                with self._timing_lock:
                    self.timing_rows.append({
                        "kind": "neural_outer_arbiter_lock", "timestamp_ns": acquired_ns,
                        "wait_start_ns": waiting_ns, "acquired_ns": acquired_ns,
                        "released_ns": self.clock_ns(),
                        "queue_access_start_ns": locals().get("queue_enter_ns"),
                        "queue_access_end_ns": locals().get("queue_return_ns"),
                        "queue_wait_ns": (queue_return_ns - queue_enter_ns if
                                          locals().get("queue_return_ns") is not None
                                          else None),
                        "perception_wait_ns": 0,
                        "perception_source_age_ns": (now_ns - published_ns if
                                                     locals().get("published_ns") is not None
                                                     else None),
                        "thread_id": threading.get_ident(),
                    })

    def _fail(self, worker, error):
        self.start_gate.abort()
        super()._fail(worker, error)

    def run(self, duration_s: float = 10.0) -> dict:
        # The parent releases the gate only after durable arm and revalidation;
        # it calls request_complete at the frozen 1,000 ms end.  The generous
        # outer timeout protects a failed parent without defining score length.
        super().run(duration_s)
        if self._scored_arm_ns is not None:
            self._started_ns = self._scored_arm_ns
        return self.summary()
