"""Per-trial arbitration of official high-level move and stop RPCs.

Neural computation and each positive move share one transaction lock. The
neural stop latches while holding that lock, so no later move request can begin.
Stop publication also uses the lock, ordering its ACK after any in-flight move.
"""

from __future__ import annotations

import threading
import time

from .watchdog import _is_authentic_watchdog_output


class MotionLatched(RuntimeError):
    pass


class NeuralStopMotionArbiter:
    def __init__(self):
        self.lock = threading.RLock()
        self.latched = threading.Event()
        self.latch_reason = None
        self.latch_at_ns = None
        self.first_stop_ack_ns = None
        self.move_transactions = []

    def neural_step(self, compute):
        with self.lock:
            update = compute()
            if update is not None and update.behavior_intent.get("stop"):
                trace = update.trace or {}
                neural = trace.get("neural_stop_latch", {})
                reason = ("healthy_neural_escape" if neural.get("source") == "healthy_neural_escape"
                          and update.readout.get("runtime_healthy") else "neural_or_safety_fault")
                self.latch(reason)
            return update

    def latch(self, reason):
        with self.lock:
            if not self.latched.is_set():
                self.latch_reason = reason
                self.latch_at_ns = time.monotonic_ns()
                self.latched.set()
            elif reason.startswith(("fault_", "scheduler_")):
                # Fault authority supersedes the source of a prior neural stop.
                self.latch_reason = reason

    def move(self, send):
        with self.lock:
            if self.latched.is_set():
                raise MotionLatched(self.latch_reason)
            result, call_ns, write_ns, ack_ns = send()
            if self.first_stop_ack_ns is not None and ack_ns >= self.first_stop_ack_ns:
                raise RuntimeError("move ACK after first stop ACK")
            self.move_transactions.append({"call_ns": call_ns, "write_ns": write_ns,
                                           "ack_ns": ack_ns})
            return result, call_ns, write_ns, ack_ns

    def publish(self, output, send):
        if not _is_authentic_watchdog_output(output):
            raise TypeError("motion arbiter requires authentic WatchdogOutput")
        if output["intent"]["stop"]:
            with self.lock:
                self.latch("watchdog_stop" if self.latch_reason is None else self.latch_reason)
                result = send(output)
                if result == "robot_stop_refreshed" and self.first_stop_ack_ns is None:
                    self.first_stop_ack_ns = time.monotonic_ns()
                return result
        with self.lock:
            if self.latched.is_set():
                raise RuntimeError("non-stop watchdog output after stop latch")
            return send(output)
