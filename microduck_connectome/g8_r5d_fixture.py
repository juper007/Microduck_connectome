"""Fixture-only production cadence stop refresh; production scheduler is unchanged."""
from __future__ import annotations

import threading

from .scheduler import ClosedLoopScheduler, SchedulerError, SchedulerWorkerError
from .watchdog import _is_authentic_watchdog_output

SUPPRESSED_NEUTRAL = "suppressed_neutral_for_stop_causality_fixture"


class UnexpectedNonzeroOutput(RuntimeError):
    """A robot-facing non-stop command violates this trial's isolation."""


class IsolatedStopPublisher:
    def __init__(self, adapter):
        self.adapter = adapter
        self.suppressed_count = 0
        self.nonzero_count = 0
        self.stop_refreshing = False
        self.post_stop_move_count = 0

    def send(self, output):
        if not _is_authentic_watchdog_output(output):
            raise TypeError("fixture publisher requires authentic watchdog output")
        intent = output["intent"]
        if intent["stop"]:
            result = self.adapter.send(output)
            if result != "robot_stop_refreshed":
                raise RuntimeError("official stop was not acknowledged")
            self.stop_refreshing = True
            return result
        if self.stop_refreshing:
            self.post_stop_move_count += 1
            raise UnexpectedNonzeroOutput("robot.move after first robot.stop ACK")
        if (intent["vx"], intent["vy"], intent["vyaw"]) == (0.0, 0.0, 0.0):
            self.suppressed_count += 1
            return SUPPRESSED_NEUTRAL
        self.nonzero_count += 1
        raise UnexpectedNonzeroOutput("unexpected nonzero neural command; trial must abort")


class ProductionStopRefreshScheduler(ClosedLoopScheduler):
    """Retain watchdog/control after visual producer ends until actual stop."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._fixture_complete = threading.Event()
        self._fixture_wake = threading.Event()

    def _fail(self, worker, error):
        super()._fail(worker, error)
        self._fixture_wake.set()

    def request_complete(self):
        self._fixture_complete.set()
        self._fixture_wake.set()

    def run(self, duration_s: float) -> dict:
        if isinstance(duration_s, bool) or not isinstance(duration_s, (int, float)) or duration_s <= 0:
            raise SchedulerError("duration_s must be positive")
        if self._threads:
            raise SchedulerError("scheduler instances are single-use")
        self._observed_neural_version = 0
        self._started_ns = self.clock_ns()
        workers = (
            ("perception", self.config["perception_hz"], self._perception_tick),
            ("neural", self.config["neural_hz"], self._neural_tick),
            ("watchdog", self.config["control_hz"], self._control_tick),
        )
        self._threads = [threading.Thread(target=self._periodic, args=worker,
                                          name=f"g8-r5d-{worker[0]}", daemon=False)
                         for worker in workers]
        for thread in self._threads:
            thread.start()
        self._fixture_wake.wait(float(duration_s))
        self._ended_ns = self.clock_ns()
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=2.0)
        alive = [thread.name for thread in self._threads if thread.is_alive()]
        if alive and self._failure_value is None:
            self._failure_value = ("shutdown", SchedulerError(f"workers did not stop: {alive}"))
            self._metrics.increment("scheduler_exceptions")
        if not self._fixture_complete.is_set() or self._failure_value is not None:
            try:
                self.watchdog.mark_decoder_crashed(1)
                now_ns = self.clock_ns()
                self._output_sequence += 1
                output = self.watchdog.tick(now_ns=now_ns, output_sequence=self._output_sequence)
                result = self.publisher(output)
                if self.control_observer is not None:
                    update, _, _ = self._neural.get()
                    self.control_observer(update, output, result)
            except BaseException as error:
                if self._failure_value is None:
                    self._failure_value = ("shutdown_stop", error)
                    self._metrics.increment("scheduler_exceptions")
        if self._failure_value is not None:
            worker, error = self._failure_value
            raise SchedulerWorkerError(worker, error) from error
        if not self._fixture_complete.is_set():
            raise SchedulerError("actual stopped confirmation did not occur before deadline")
        return self.summary()
