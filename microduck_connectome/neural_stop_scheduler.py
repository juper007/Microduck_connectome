"""Atomic neural-stop handoff with fault-stop priority."""

from __future__ import annotations

from collections.abc import Mapping

from .fault_stop import FaultStopRefreshScheduler
from .neural_stop_arbiter import NeuralStopMotionArbiter
from .perception_frame import PerceptionFrameError, make_perception_frame
from .scheduler import ClosedLoopScheduler, SchedulerError


class NeuralStopRefreshScheduler(FaultStopRefreshScheduler):
    """Keep stop candidate publication and watchdog transport in one order.

    Fault guard is always acquired before motion arbiter in the control thread.
    The neural thread acquires only the motion arbiter, including the _Latest
    update.  Thus a candidate cannot latch while the control thread publishes
    an older non-stop update, and no later move RPC can cross that latch.
    """

    def __init__(self, *, motion_arbiter, **kwargs):
        if not isinstance(motion_arbiter, NeuralStopMotionArbiter):
            raise TypeError("motion_arbiter must be NeuralStopMotionArbiter")
        publisher = kwargs["publisher"]
        kwargs["publisher"] = lambda output: motion_arbiter.publish(output, publisher)
        super().__init__(**kwargs)
        self.motion_arbiter = motion_arbiter
        self._primed_source_ns = None

    def prime_perception(self, frame, *, now_ns: int) -> dict:
        """Seed the pre-run cache with the already used, fresh camera frame.

        Cache insertion does not run a neural step or refresh the source time.
        The first ordinary perception publication replaces this entry.
        """
        if self._started_ns is not None or self._threads or self._perception.get()[2]:
            raise SchedulerError("perception priming must occur once before scheduler start")
        if type(now_ns) is not int or now_ns < 0 or not isinstance(frame, Mapping):
            raise SchedulerError("perception priming requires a frame and monotonic time")
        try:
            canonical = make_perception_frame(**dict(frame))
        except (TypeError, ValueError, PerceptionFrameError) as error:
            raise SchedulerError("invalid perception priming frame") from error
        source_ns = canonical["timestamp_ns"]
        if (not canonical["valid"] or source_ns > now_ns
                or now_ns - source_ns > self.config["perception_ttl_ms"] * 1_000_000):
            raise SchedulerError("perception priming frame is invalid, future, or stale")
        self._perception.put(canonical, source_ns)
        self._primed_source_ns = source_ns
        return canonical

    def run(self, duration_s: float) -> dict:
        if self._primed_source_ns is not None:
            now_ns = self.clock_ns()
            if (now_ns < self._primed_source_ns
                    or now_ns - self._primed_source_ns
                    >= self.config["perception_ttl_ms"] * 1_000_000):
                raise SchedulerError("primed perception expired before scheduler start")
        return super().run(duration_s)

    def _neural_tick(self, now_ns):
        with self.motion_arbiter.lock:
            super()._neural_tick(now_ns)

    def _control_tick(self, now_ns):
        with self.fault_latch.transport_guard():
            fault = self.fault_latch.snapshot()
            if fault is not None:
                self.watchdog.latch_fault(fault.reason)
                self.motion_arbiter.latch("fault_" + fault.reason)
            with self.motion_arbiter.lock:
                # A watchdog safe-stop is terminal for this trial.  Fresh input
                # on a later tick must not turn the next authentic output back
                # into a move and end the 50 Hz stop-refresh worker.
                if (fault is None
                        and self.motion_arbiter.watchdog_stop_reason is not None):
                    self.watchdog.latch_fault(self.motion_arbiter.watchdog_stop_reason)
                ClosedLoopScheduler._control_tick(self, now_ns)

    def _fail(self, worker, error):
        super()._fail(worker, error)
        self.motion_arbiter.latch(f"scheduler_{worker}_fault")
