"""Race tests for development-only positive-move/stop arbitration."""

import threading
import time
import unittest

from microduck_connectome.p8_probe_motion_arbiter import MotionLatched, ProbeMotionArbiter


class Update:
    def __init__(self, stop):
        self.behavior_intent = {"stop": stop}


class ProbeMotionArbiterTest(unittest.TestCase):
    def test_stop_before_move_request_prevents_write(self):
        arbiter = ProbeMotionArbiter()
        arbiter.neural_step(lambda: Update(True))
        sent = []
        with self.assertRaises(MotionLatched):
            arbiter.move(lambda: sent.append(True))
        self.assertEqual(sent, [])

    def test_in_flight_move_ack_precedes_stop_ack(self):
        arbiter = ProbeMotionArbiter()
        move_entered = threading.Event()
        release_move = threading.Event()
        calls = []

        def send_move():
            started = time.monotonic_ns()
            move_entered.set()
            self.assertTrue(release_move.wait(2))
            ack = time.monotonic_ns()
            calls.append("move_ack")
            return {"accepted": True}, started, started, ack

        mover = threading.Thread(target=lambda: arbiter.move(send_move))
        mover.start()
        self.assertTrue(move_entered.wait(2))
        neural = threading.Thread(target=lambda: arbiter.neural_step(lambda: Update(True)))
        neural.start()
        self.assertFalse(arbiter.latched.is_set())
        release_move.set()
        mover.join(2)
        neural.join(2)
        self.assertFalse(mover.is_alive() or neural.is_alive())
        self.assertTrue(arbiter.latched.is_set())
        result = arbiter.publish({"intent": {"stop": True}},
                                 lambda _: calls.append("stop_ack") or "robot_stop_refreshed")
        self.assertEqual(result, "robot_stop_refreshed")
        self.assertEqual(calls, ["move_ack", "stop_ack"])
        self.assertLess(arbiter.move_transactions[-1]["ack_ns"], arbiter.first_stop_ack_ns)

    def test_fault_latch_prevents_later_move(self):
        arbiter = ProbeMotionArbiter()
        arbiter.latch("sensor_fault")
        with self.assertRaises(MotionLatched):
            arbiter.move(lambda: self.fail("positive move sent after fault"))
        self.assertEqual(arbiter.latch_reason, "sensor_fault")


if __name__ == "__main__":
    unittest.main()
