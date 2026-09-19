"""Independent monotonic timing domains for Phase-6 closed-loop integration."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
import math
from pathlib import Path
import statistics
import threading
import time


class SchedulerError(ValueError):
    """Invalid scheduler configuration or lifecycle operation."""


class SchedulerWorkerError(RuntimeError):
    """A scheduler worker failed; the original exception is retained."""

    def __init__(self, worker: str, error: BaseException):
        super().__init__(f"{worker} worker failed: {error}")
        self.worker = worker
        self.original = error


@dataclass(frozen=True)
class NeuralUpdate:
    """One atomic neural/decoded/post-safety update for the watchdog."""

    readout: Mapping
    behavior_intent: Mapping
    trace: Mapping | None = None


def load_scheduler_config(path: str | Path) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SchedulerError("cannot load scheduler config") from error
    return _validate_scheduler_config(value)


def _validate_scheduler_config(value) -> dict:
    required = {
        "schema_version", "perception_hz", "neural_hz", "control_hz",
        "perception_ttl_ms", "neural_readout_ttl_ms",
        "behavior_intent_ttl_ms", "source",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise SchedulerError("scheduler config fields mismatch")
    if value["schema_version"] != "scheduler-v1" or value["source"] != "male-cns-controller":
        raise SchedulerError("scheduler schema/source mismatch")
    for name, minimum in (("perception_hz", 25), ("neural_hz", 20), ("control_hz", 50)):
        if type(value[name]) is not int or value[name] < minimum:
            raise SchedulerError(f"{name} must be an integer >= {minimum}")
    if value["control_hz"] != 50:
        raise SchedulerError("control_hz must remain 50")
    for name in ("perception_ttl_ms", "neural_readout_ttl_ms", "behavior_intent_ttl_ms"):
        if type(value[name]) is not int or value[name] != 100:
            raise SchedulerError(f"{name} must remain 100")
    return dict(value)


class _Latest:
    def __init__(self):
        self._lock = threading.Lock()
        self._value = None
        self._published_ns = None
        self._version = 0

    def put(self, value, published_ns: int) -> None:
        with self._lock:
            self._value = value
            self._published_ns = published_ns
            self._version += 1

    def get(self):
        with self._lock:
            return self._value, self._published_ns, self._version


class _Metrics:
    _DOMAINS = ("perception", "neural", "watchdog", "publish")

    def __init__(self):
        self.lock = threading.Lock()
        self.tick_ns = {name: [] for name in self._DOMAINS}
        self.latency_ns = {name: [] for name in self._DOMAINS}
        self.dropped_perception = 0
        self.dropped_neural = 0
        self.stale_events = 0
        self.scheduler_exceptions = 0
        self.missed_deadlines = {name: 0 for name in ("perception", "neural", "watchdog")}

    def record(self, domain: str, started_ns: int, ended_ns: int) -> None:
        with self.lock:
            self.tick_ns[domain].append(started_ns)
            self.latency_ns[domain].append(ended_ns - started_ns)

    def increment(self, name: str, amount: int = 1) -> None:
        with self.lock:
            setattr(self, name, getattr(self, name) + amount)

    def missed(self, domain: str, amount: int) -> None:
        with self.lock:
            self.missed_deadlines[domain] += amount


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


class ClosedLoopScheduler:
    """Run producers independently and publish only fresh watchdog-minted output.

    ``perception_step(now_ns)`` returns a frame or ``None`` for a skipped frame.
    ``neural_step(frame_or_none, now_ns)`` must neutralize ``None`` input and return
    a :class:`NeuralUpdate`, or ``None`` for a skipped neural update.  ``publisher``
    is normally ``RobotMotionAdapter.send`` and therefore rejects anything not
    minted by the watchdog.
    """

    def __init__(
        self,
        *,
        config,
        watchdog,
        perception_step: Callable[[int], object | None],
        neural_step: Callable[[object | None, int], NeuralUpdate | None],
        publisher: Callable[[object], object],
        control_observer: Callable[[NeuralUpdate | None, object, object], None] | None = None,
        clock_ns: Callable[[], int] = time.monotonic_ns,
    ):
        self.config = (
            load_scheduler_config(config)
            if isinstance(config, (str, Path))
            else _validate_scheduler_config(config)
        )
        self.watchdog = watchdog
        self.perception_step = perception_step
        self.neural_step = neural_step
        self.publisher = publisher
        self.control_observer = control_observer
        self.clock_ns = clock_ns
        self._stop = threading.Event()
        self._failure = threading.Event()
        self._failure_value = None
        self._failure_lock = threading.Lock()
        self._perception = _Latest()
        self._neural = _Latest()
        self._metrics = _Metrics()
        self._threads = []
        self._output_sequence = 0
        self._started_ns = None
        self._ended_ns = None

    def _fail(self, worker: str, error: BaseException) -> None:
        with self._failure_lock:
            if self._failure_value is None:
                self._failure_value = (worker, error)
                self._metrics.increment("scheduler_exceptions")
        self._failure.set()
        self._stop.set()

    def _periodic(self, domain: str, hz: int, step: Callable[[int], None]) -> None:
        period_ns = int(1_000_000_000 / hz)
        deadline = self.clock_ns()
        try:
            while not self._stop.is_set():
                now = self.clock_ns()
                wait_ns = deadline - now
                if wait_ns > 0 and self._stop.wait(wait_ns / 1_000_000_000):
                    break
                started = self.clock_ns()
                step(started)
                ended = self.clock_ns()
                self._metrics.record(domain, started, ended)
                deadline += period_ns
                if ended >= deadline:
                    skipped = (ended - deadline) // period_ns + 1
                    self._metrics.missed(domain, int(skipped))
                    deadline += skipped * period_ns
        except BaseException as error:
            self._fail(domain, error)

    def _perception_tick(self, now_ns: int) -> None:
        frame = self.perception_step(now_ns)
        if frame is None:
            self._metrics.increment("dropped_perception")
            return
        if not isinstance(frame, Mapping):
            self._metrics.increment("dropped_perception")
            return
        source_ns = frame.get("timestamp_ns")
        if type(source_ns) is not int or source_ns < 0 or source_ns > now_ns:
            self._metrics.increment("dropped_perception")
            return
        # Preserve source time. Receiving an old sample now must not refresh it.
        self._perception.put(frame, source_ns)

    def _neural_tick(self, now_ns: int) -> None:
        frame, published_ns, _ = self._perception.get()
        if published_ns is None or now_ns - published_ns > 100_000_000:
            frame = None
        update = self.neural_step(frame, now_ns)
        if update is None:
            self._metrics.increment("dropped_neural")
        elif not isinstance(update, NeuralUpdate):
            raise SchedulerError("neural_step must return NeuralUpdate or None")
        else:
            self._neural.put(update, now_ns)

    def _control_tick(self, now_ns: int) -> None:
        update, _, version = self._neural.get()
        if version > getattr(self, "_observed_neural_version", 0):
            self.watchdog.observe_neural(update.readout)
            self.watchdog.observe_behavior(update.behavior_intent)
            self._observed_neural_version = version
        self._output_sequence += 1
        output = self.watchdog.tick(now_ns=now_ns, output_sequence=self._output_sequence)
        if output["watchdog_state"] != "healthy":
            self._metrics.increment("stale_events")
        publish_started = self.clock_ns()
        publish_result = self.publisher(output)
        if self.control_observer is not None:
            self.control_observer(update, output, publish_result)
        self._metrics.record("publish", publish_started, self.clock_ns())

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
        self._threads = [
            threading.Thread(target=self._periodic, args=worker, name=f"p6-{worker[0]}", daemon=False)
            for worker in workers
        ]
        for thread in self._threads:
            thread.start()
        self._failure.wait(float(duration_s))
        # Close the measurement window before waiting for a potentially slow
        # producer to return.  Shutdown latency is not scheduler cadence.
        self._ended_ns = self.clock_ns()
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=2.0)
        alive = [thread.name for thread in self._threads if thread.is_alive()]
        if alive and self._failure_value is None:
            self._failure_value = ("shutdown", SchedulerError(f"workers did not stop: {alive}"))
            self._metrics.increment("scheduler_exceptions")
        # A clean or faulted shutdown invalidates decoder liveness and attempts one
        # current stop.  Publisher errors remain visible and cannot be replayed.
        try:
            self.watchdog.mark_decoder_crashed(1)
            now_ns = self.clock_ns()
            self._output_sequence += 1
            output = self.watchdog.tick(now_ns=now_ns, output_sequence=self._output_sequence)
            publish_result = self.publisher(output)
            if self.control_observer is not None:
                update, _, _ = self._neural.get()
                self.control_observer(update, output, publish_result)
        except BaseException as error:
            if self._failure_value is None:
                self._failure_value = ("shutdown_stop", error)
                self._metrics.increment("scheduler_exceptions")
        if self._failure_value is not None:
            worker, error = self._failure_value
            raise SchedulerWorkerError(worker, error) from error
        return self.summary()

    def summary(self) -> dict:
        if self._started_ns is None or self._ended_ns is None:
            raise SchedulerError("summary is available after run")
        with self._metrics.lock:
            ticks = {name: list(values) for name, values in self._metrics.tick_ns.items()}
            latency = {name: list(values) for name, values in self._metrics.latency_ns.items()}
            dropped_perception = self._metrics.dropped_perception
            dropped_neural = self._metrics.dropped_neural
            stale_events = self._metrics.stale_events
            scheduler_exceptions = self._metrics.scheduler_exceptions
            missed = dict(self._metrics.missed_deadlines)
        duration_s = (self._ended_ns - self._started_ns) / 1_000_000_000

        def periods_ms(domain):
            return [(b - a) / 1_000_000 for a, b in zip(ticks[domain], ticks[domain][1:])]

        result = {
            "duration_s": duration_s,
            "perception_hz": len(ticks["perception"]) / duration_s,
            "neural_hz": len(ticks["neural"]) / duration_s,
            "watchdog_hz": len(ticks["watchdog"]) / duration_s,
            "publish_hz": len(ticks["publish"]) / duration_s,
            "dropped_perception": dropped_perception,
            "dropped_neural": dropped_neural,
            "stale_events": stale_events,
            "scheduler_exceptions": scheduler_exceptions,
            "missed_deadlines": missed,
        }
        for domain in ("perception", "neural", "watchdog", "publish"):
            samples = periods_ms(domain)
            target_ms = 1000.0 / (self.config["control_hz"] if domain in ("watchdog", "publish") else self.config[f"{domain}_hz"])
            jitter = [abs(value - target_ms) for value in samples]
            for label, percentile in (("p50", .50), ("p95", .95), ("p99", .99)):
                result[f"{domain}_period_ms_{label}"] = _percentile(samples, percentile)
                result[f"{domain}_jitter_ms_{label}"] = _percentile(jitter, percentile)
                result[f"{domain}_processing_latency_ms_{label}"] = _percentile(
                    [value / 1_000_000 for value in latency[domain]], percentile
                )
        return result
