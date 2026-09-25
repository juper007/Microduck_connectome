"""Persist a source-derived stop intent until the trial's body has ceased.

This is a behavior-intent component.  It never publishes robot commands.
Every held stop is rebuilt with the current neural timestamp and passes through
SafetyClamp, ControllerWatchdog, and RobotMotionAdapter in the ordinary path.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import threading

from .control_contracts import make_behavior_intent, validate_neural_readout
from .watchdog import _is_authentic_watchdog_output


@dataclass(frozen=True)
class NeuralStopRecord:
    source: str
    cause: str
    graph_runtime_step: int
    neural_timestamp_ns: int
    neural_sequence: int
    detected_ns: int
    escape_activity: float
    first_healthy_stop_ack_ns: int | None = None


class NeuralStopIntentLatch:
    """First healthy escape wins; later activity cannot clear its stop intent.

    A candidate is held as soon as its decoded stop survives SafetyClamp.  It
    becomes confirmed only after a healthy Watchdog output reaches an official
    robot.stop ACK.  This pending state closes the neural/control race without
    attributing a watchdog fault stop to healthy neural escape.
    """

    def __init__(self, *, escape_threshold: float):
        if type(escape_threshold) not in (float, int) or not 0 < escape_threshold <= 1:
            raise ValueError("escape_threshold must be in (0, 1]")
        self.escape_threshold = float(escape_threshold)
        self._lock = threading.RLock()
        self._record: NeuralStopRecord | None = None

    def snapshot(self) -> NeuralStopRecord | None:
        with self._lock:
            return self._record

    def apply(self, *, readout, decoded_intent, safety, now_ns: int,
              graph_runtime_step: int):
        """Return (selected intent, SafetyClamp result, raw-stop suppressed).

        ``decoded_intent`` must be EscapeDecoder's ordinary high-level output.
        The caller retains it in telemetry even when a later non-stop is held.
        """
        neural = validate_neural_readout(readout)
        if type(graph_runtime_step) is not int or graph_runtime_step <= 0:
            raise ValueError("graph_runtime_step must be a positive integer")
        with self._lock:
            record = self._record
            selected = decoded_intent
            if record is not None:
                selected = make_behavior_intent(
                    timestamp_ns=neural["timestamp_ns"],
                    sequence=neural["sequence"], stop=True,
                    confidence=record.escape_activity,
                )
            safe = safety.apply(selected, now_ns=now_ns,
                                fallback_sequence=neural["sequence"])
            if record is None and (
                neural["runtime_healthy"]
                and neural["escape"] >= self.escape_threshold
                and decoded_intent["stop"] is True
                and safe["intent"]["stop"] is True
                and safe["reasons"] == ["stop_override"]
            ):
                self._record = NeuralStopRecord(
                    source="healthy_neural_escape", cause="DNp01_EscapeDecoder",
                    graph_runtime_step=graph_runtime_step,
                    neural_timestamp_ns=neural["timestamp_ns"],
                    neural_sequence=neural["sequence"], detected_ns=now_ns,
                    escape_activity=neural["escape"],
                )
            return selected, safe, bool(record is not None and not decoded_intent["stop"])

    def confirm(self, *, output, transport_result: str, ack_ns: int,
                source_neural_sequence: int, source_intent_stop: bool) -> NeuralStopRecord | None:
        """Bind the pending source event to an authentic healthy stop ACK."""
        if type(ack_ns) is not int or ack_ns < 0:
            raise ValueError("ack_ns must be a non-negative integer")
        if (type(source_neural_sequence) is not int or source_neural_sequence < 0
                or type(source_intent_stop) is not bool):
            raise ValueError("source update metadata is invalid")
        if not _is_authentic_watchdog_output(output):
            raise TypeError("confirmation requires authentic WatchdogOutput")
        with self._lock:
            record = self._record
            if (record is not None and record.first_healthy_stop_ack_ns is None
                    and output["watchdog_state"] == "healthy"
                    and output["intent"]["stop"] is True
                    and output["intent"]["timestamp_ns"] >= record.detected_ns
                    and source_neural_sequence >= record.neural_sequence
                    and source_intent_stop
                    and transport_result == "robot_stop_refreshed"
                    and ack_ns >= record.detected_ns):
                self._record = replace(record, first_healthy_stop_ack_ns=ack_ns)
            return self._record
