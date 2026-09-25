"""Atomic neural-stop handoff with fault-stop priority."""

from __future__ import annotations

from .fault_stop import FaultStopRefreshScheduler
from .neural_stop_arbiter import NeuralStopMotionArbiter
from .scheduler import ClosedLoopScheduler


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
                ClosedLoopScheduler._control_tick(self, now_ns)

    def _fail(self, worker, error):
        super()._fail(worker, error)
        self.motion_arbiter.latch(f"scheduler_{worker}_fault")
