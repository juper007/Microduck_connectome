"""Development-only arbitration of official positive move and stop RPCs.

Neural computation and each positive move share one transaction lock. The
neural stop latches while holding that lock, so no later move request can begin.
Stop publication also uses the lock, ordering its ACK after any in-flight move.
"""

from __future__ import annotations

import threading
import time


class MotionLatched(RuntimeError):
    pass


class ProbeMotionArbiter:
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
                self.latch("neural_stop")
            return update

    def latch(self, reason):
        with self.lock:
            if not self.latched.is_set():
                self.latch_reason = reason
                self.latch_at_ns = time.monotonic_ns()
                self.latched.set()

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
        if output["intent"]["stop"]:
            with self.lock:
                self.latch("watchdog_stop" if self.latch_reason is None else self.latch_reason)
                result = send(output)
                if self.first_stop_ack_ns is None:
                    self.first_stop_ack_ns = time.monotonic_ns()
                return result
        if self.latched.is_set() and any(output["intent"][key] != 0.0
                                         for key in ("vx", "vy", "vyaw")):
            raise RuntimeError("nonzero watchdog output after stop latch")
        return send(output)
