"""Reusable per-trial fault latch and production-cadence stop refresh.

The latch records source health independently of neural intent.  It never
publishes robot commands; only the production Watchdog and MotionAdapter can
turn the latched fault into an acknowledged robot.stop request.
"""

from __future__ import annotations

from dataclasses import dataclass
import threading
from contextlib import contextmanager
from collections.abc import Callable, Mapping

from .control_contracts import ControlContractError, validate_neural_readout
from .g8_r5d_fixture import ProductionStopRefreshScheduler
from .perception_frame import PerceptionFrameError, make_perception_frame
from .scheduler import NeuralUpdate


FAULT_REASONS = frozenset({
    "camera_loss", "camera_stale", "tof_loss", "camera_and_tof_loss",
    "intermittent_frame_loss", "malformed_perception", "nan_feature",
    "inf_feature", "stale_neural", "neural_freeze", "neural_crash",
    "malformed_neural", "nan_neural", "inf_neural",
    "worker_exception_perception", "worker_exception_neural",
})


@dataclass(frozen=True)
class FaultRecord:
    reason: str
    detected_ns: int
    planned: bool
    last_healthy_sensor_ns: int | None
    last_healthy_neural_ns: int | None


class FaultStopLatch:
    """First-fault-wins latch.  A later healthy sample cannot clear it."""

    def __init__(self):
        self._lock = threading.RLock()
        self._record = None
        self._last_sensor_ns = None
        self._last_neural_ns = None

    def observe_healthy(self, domain: str, timestamp_ns: int) -> None:
        if domain not in ("sensor", "neural"):
            raise ValueError("domain must be sensor or neural")
        if type(timestamp_ns) is not int or timestamp_ns < 0:
            raise ValueError("timestamp_ns must be a non-negative integer")
        with self._lock:
            if self._record is not None:
                return
            field = "_last_sensor_ns" if domain == "sensor" else "_last_neural_ns"
            previous = getattr(self, field)
            if previous is not None and timestamp_ns <= previous:
                raise ValueError("healthy timestamps must increase")
            setattr(self, field, timestamp_ns)

    def latch(self, reason: str, *, detected_ns: int, planned: bool) -> FaultRecord:
        if reason not in FAULT_REASONS:
            raise ValueError("unknown fault reason")
        if type(detected_ns) is not int or detected_ns < 0 or type(planned) is not bool:
            raise ValueError("invalid fault metadata")
        with self._lock:
            if self._record is None:
                self._record = FaultRecord(
                    reason, detected_ns, planned,
                    self._last_sensor_ns, self._last_neural_ns,
                )
            return self._record

    def snapshot(self) -> FaultRecord | None:
        with self._lock:
            return self._record

    @contextmanager
    def transport_guard(self):
        """Serialize fault-latch transition with one watchdog publication.

        An RPC already in flight may finish before the fault latch is acquired;
        the caller must record that interval and bound the RPC deadline.
        """
        with self._lock:
            yield


class PlannedFault(Exception):
    """A named injected fault, distinct from an unexpected worker exception."""

    def __init__(self, reason: str):
        if reason not in FAULT_REASONS:
            raise ValueError("unknown planned fault")
        super().__init__(reason)
        self.reason = reason


class FaultAwareInputs:
    """Contain planned input faults and latch source health before control.

    `source_fault_reason` can read compositor diagnostics to distinguish an
    invalid ToF source from an invalid camera.  It must return a frozen reason
    or None.  Unexpected exceptions propagate for scheduler fault accounting.
    """

    def __init__(self, *, fault_latch: FaultStopLatch, started_ns: int,
                 perception_step: Callable, neural_step: Callable,
                 source_fault_reason: Callable | None = None):
        if type(started_ns) is not int or started_ns < 0:
            raise ValueError("started_ns must be a non-negative integer")
        self.fault_latch = fault_latch
        self.started_ns = started_ns
        self.perception_step = perception_step
        self.neural_step = neural_step
        self.source_fault_reason = source_fault_reason
        self.last_sensor_ns = None
        self.last_neural_ns = None

    def _planned(self, reason, now_ns):
        self.fault_latch.latch(reason, detected_ns=now_ns, planned=True)

    @staticmethod
    def _nonfinite_reason(frame):
        if isinstance(frame, Mapping):
            for value in frame.values():
                if type(value) is float:
                    if value != value:
                        return "nan_feature"
                    if value in (float("inf"), -float("inf")):
                        return "inf_feature"
        return "malformed_perception"

    def perception(self, now_ns):
        if self.fault_latch.snapshot() is not None:
            return None
        try:
            frame = self.perception_step(now_ns)
        except PlannedFault as error:
            self._planned(error.reason, now_ns)
            return None
        if frame is None:
            previous = self.last_sensor_ns if self.last_sensor_ns is not None else self.started_ns
            age_ns = now_ns - previous
            if age_ns > 100_000_000:
                self._planned("camera_loss", now_ns)
            return None
        try:
            canonical = make_perception_frame(**dict(frame))
        except (TypeError, ValueError, PerceptionFrameError):
            self._planned(self._nonfinite_reason(frame), now_ns)
            return None
        reason = self.source_fault_reason(frame) if self.source_fault_reason else None
        if reason is not None:
            self._planned(reason, now_ns)
            return None
        if not canonical["valid"]:
            self._planned("malformed_perception", now_ns)
            return None
        if canonical["timestamp_ns"] > now_ns or now_ns - canonical["timestamp_ns"] > 100_000_000:
            self._planned("camera_stale", now_ns)
            return None
        if self.last_sensor_ns is not None and canonical["timestamp_ns"] <= self.last_sensor_ns:
            self._planned("camera_stale", now_ns)
            return None
        self.last_sensor_ns = canonical["timestamp_ns"]
        self.fault_latch.observe_healthy("sensor", canonical["timestamp_ns"])
        return canonical

    def neural(self, frame, now_ns):
        if self.fault_latch.snapshot() is not None:
            return None
        try:
            update = self.neural_step(frame, now_ns)
        except PlannedFault as error:
            self._planned(error.reason, now_ns)
            return None
        if update is None:
            previous = self.last_neural_ns if self.last_neural_ns is not None else self.started_ns
            age_ns = now_ns - previous
            if age_ns > 100_000_000:
                self._planned("stale_neural", now_ns)
            return None
        if not isinstance(update, NeuralUpdate):
            self._planned("malformed_neural", now_ns)
            return None
        try:
            validate_neural_readout(update.readout)
        except (AttributeError, ControlContractError):
            reason = "malformed_neural"
            if hasattr(update, "readout"):
                feature_reason = self._nonfinite_reason(update.readout)
                if feature_reason == "nan_feature":
                    reason = "nan_neural"
                elif feature_reason == "inf_feature":
                    reason = "inf_neural"
            self._planned(reason, now_ns)
            return None
        source_ns = update.readout["timestamp_ns"]
        if source_ns > now_ns or now_ns - source_ns > 100_000_000:
            self._planned("stale_neural", now_ns)
            return None
        if self.last_neural_ns is not None and update.readout["timestamp_ns"] <= self.last_neural_ns:
            self._planned("stale_neural", now_ns)
            return None
        self.last_neural_ns = update.readout["timestamp_ns"]
        self.fault_latch.observe_healthy("neural", self.last_neural_ns)
        return update


class FaultStopRefreshScheduler(ProductionStopRefreshScheduler):
    """Keep the authentic 50 Hz watchdog publisher alive after producer faults.

    Planned faults are latched by the sensor/neural wrapper.  Unexpected
    perception/neural worker exceptions are also latched, but remain scheduler
    failures; the eventual run raises after the independent pose observer calls
    request_complete.  A failed control/publisher cannot promise ACK refresh.
    """

    def __init__(self, *, fault_latch: FaultStopLatch, **kwargs):
        if not isinstance(fault_latch, FaultStopLatch):
            raise TypeError("fault_latch must be FaultStopLatch")
        super().__init__(**kwargs)
        self.fault_latch = fault_latch

    def _control_tick(self, now_ns: int) -> None:
        with self.fault_latch.transport_guard():
            fault = self.fault_latch.snapshot()
            if fault is not None:
                self.watchdog.latch_fault(fault.reason)
            super()._control_tick(now_ns)

    def _fail(self, worker: str, error: BaseException) -> None:
        if worker not in ("perception", "neural"):
            super()._fail(worker, error)
            return
        reason = "worker_exception_" + worker
        self.fault_latch.latch(reason, detected_ns=self.clock_ns(), planned=False)
        with self._failure_lock:
            if self._failure_value is None:
                self._failure_value = (worker, error)
                self._metrics.increment("scheduler_exceptions")
        # This producer exits after _periodic catches its exception.  Do not
        # stop the watchdog/control worker: it must refresh robot.stop until
        # the independent pose observer confirms cessation or the bounded
        # trial deadline expires.
