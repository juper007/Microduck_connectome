"""P8-R3 neural stop persistence, fault priority, and command ordering."""

import threading
import unittest
from pathlib import Path

from microduck_connectome.control_contracts import make_behavior_intent
from microduck_connectome.fault_stop import FaultStopLatch
from microduck_connectome.neural_stop_arbiter import NeuralStopMotionArbiter
from microduck_connectome.neural_stop_latch import NeuralStopIntentLatch
from microduck_connectome.neural_stop_scheduler import NeuralStopRefreshScheduler
from microduck_connectome.safety_clamp import SafetyClamp
from microduck_connectome.scheduler import NeuralUpdate
from microduck_connectome.watchdog import ControllerWatchdog


CONFIG = {"neural_readout_ttl_ms": 100, "behavior_intent_ttl_ms": 100}
ROOT = Path(__file__).resolve().parents[1]


def readout(t, seq, escape):
    return {"timestamp_ns": t, "sequence": seq, "steering_left": 0.0,
            "steering_right": 0.0, "escape": escape, "runtime_healthy": True}


def decoded(sample, stop):
    return make_behavior_intent(timestamp_ns=sample["timestamp_ns"],
                                sequence=sample["sequence"],
                                vx=0.0 if stop else 0.05, stop=stop,
                                confidence=sample["escape"])


def checked_update(latch, safety, sample, stop):
    intent, safe, held = latch.apply(
        readout=sample, decoded_intent=decoded(sample, stop), safety=safety,
        now_ns=sample["timestamp_ns"], graph_runtime_step=sample["sequence"])
    trace = {"neural_stop_latch": {"source": "healthy_neural_escape"}} if latch.snapshot() else {}
    return NeuralUpdate(sample, safe["intent"], trace), held


def tick(watchdog, update, t, seq):
    assert watchdog.observe_neural(update.readout)
    assert watchdog.observe_behavior(update.behavior_intent)
    return watchdog.tick(now_ns=t, output_sequence=seq)


def setup():
    latch = NeuralStopIntentLatch(escape_threshold=0.5)
    safety = SafetyClamp()
    watchdog = ControllerWatchdog(CONFIG)
    arbiter = NeuralStopMotionArbiter()
    fault = FaultStopLatch()
    return latch, safety, watchdog, arbiter, fault


def test_neural_then_fault_overrides_source_and_ack_attribution():
    latch, safety, watchdog, arbiter, fault = setup()
    update, _ = checked_update(latch, safety, readout(100, 1, 0.6), True)
    arbiter.neural_step(lambda: update)
    assert arbiter.latch_reason == "healthy_neural_escape"
    healthy = tick(watchdog, update, 101, 1)
    assert healthy["watchdog_state"] == "healthy"
    fault.latch("camera_loss", detected_ns=102, planned=True)
    scheduler = NeuralStopRefreshScheduler(
        motion_arbiter=arbiter, fault_latch=fault,
        config=ROOT / "config/scheduler_v1.json",
        watchdog=watchdog, perception_step=lambda t: None,
        neural_step=lambda frame, t: None, publisher=lambda output: "robot_stop_refreshed")
    scheduler._output_sequence = 1
    scheduler._control_tick(103)
    assert arbiter.latch_reason == "fault_camera_loss"
    output = watchdog.tick(now_ns=104, output_sequence=3)
    assert output["stale_reason"] == "fault_camera_loss"
    assert latch.confirm(output=output, transport_result="robot_stop_refreshed",
                         ack_ns=105, source_neural_sequence=1,
                         source_intent_stop=True).first_healthy_stop_ack_ns is None


def test_fault_then_neural_keeps_fault_authority():
    latch, safety, watchdog, arbiter, fault = setup()
    fault.latch("tof_loss", detected_ns=100, planned=True)
    arbiter.latch("fault_tof_loss")
    update, _ = checked_update(latch, safety, readout(110, 1, 0.7), True)
    arbiter.neural_step(lambda: update)
    assert arbiter.latch_reason == "fault_tof_loss"
    watchdog.latch_fault("tof_loss")
    output = tick(watchdog, update, 111, 1)
    assert output["stale_reason"] == "fault_tof_loss"
    assert latch.confirm(output=output, transport_result="robot_stop_refreshed",
                         ack_ns=112, source_neural_sequence=1,
                         source_intent_stop=True).first_healthy_stop_ack_ns is None


def test_fault_during_stop_ack_remains_highest_priority():
    latch, safety, watchdog, arbiter, fault = setup()
    update, _ = checked_update(latch, safety, readout(100, 1, 0.6), True)
    arbiter.neural_step(lambda: update)
    output = tick(watchdog, update, 101, 1)
    entered, release = threading.Event(), threading.Event()
    result = []

    def send(_output):
        entered.set()
        assert release.wait(2)
        return "robot_stop_refreshed"

    worker = threading.Thread(target=lambda: result.append(arbiter.publish(output, send)))
    worker.start()
    assert entered.wait(2)
    fault_worker = threading.Thread(target=lambda: (fault.latch(
        "camera_loss", detected_ns=102, planned=True), arbiter.latch("fault_camera_loss")))
    fault_worker.start()
    release.set()
    worker.join(2)
    fault_worker.join(2)
    assert not worker.is_alive() and not fault_worker.is_alive()
    assert result == ["robot_stop_refreshed"]
    assert arbiter.latch_reason == "fault_camera_loss"
    watchdog.latch_fault("camera_loss")
    later = watchdog.tick(now_ns=103, output_sequence=2)
    assert later["stale_reason"] == "fault_camera_loss"


def test_scheduler_orders_inflight_ack_before_fault_transition():
    latch, safety, watchdog, arbiter, fault = setup()
    update, _ = checked_update(latch, safety, readout(100, 1, 0.6), True)
    arbiter.neural_step(lambda: update)
    assert watchdog.observe_neural(update.readout)
    assert watchdog.observe_behavior(update.behavior_intent)
    entered, release = threading.Event(), threading.Event()
    results = []

    def send(output):
        entered.set()
        assert release.wait(10)
        results.append(output["stale_reason"])
        return "robot_stop_refreshed"

    scheduler = NeuralStopRefreshScheduler(
        motion_arbiter=arbiter, fault_latch=fault,
        config=ROOT / "config/scheduler_v1.json", watchdog=watchdog,
        perception_step=lambda t: None, neural_step=lambda frame, t: None,
        publisher=send)
    control = threading.Thread(target=lambda: scheduler._control_tick(101))
    control.start()
    assert entered.wait(5)
    fault_started, fault_done = threading.Event(), threading.Event()

    def inject_fault():
        fault_started.set()
        fault.latch("camera_loss", detected_ns=102, planned=True)
        fault_done.set()

    fault_worker = threading.Thread(target=inject_fault)
    fault_worker.start()
    assert fault_started.wait(5)
    assert not fault_done.is_set()
    release.set()
    control.join(5)
    fault_worker.join(5)
    assert not control.is_alive() and not fault_worker.is_alive()
    assert results == [None]
    scheduler._control_tick(103)
    assert results == [None, "fault_camera_loss"]
    assert arbiter.latch_reason == "fault_camera_loss"


def test_fault_after_neural_ack_supersedes_future_outputs():
    latch, safety, watchdog, arbiter, fault = setup()
    update, _ = checked_update(latch, safety, readout(100, 1, 0.6), True)
    arbiter.neural_step(lambda: update)
    output = tick(watchdog, update, 101, 1)
    assert arbiter.publish(output, lambda _: "robot_stop_refreshed") == "robot_stop_refreshed"
    assert latch.confirm(output=output, transport_result="robot_stop_refreshed",
                         ack_ns=102, source_neural_sequence=1,
                         source_intent_stop=True).first_healthy_stop_ack_ns == 102
    fault.latch("tof_loss", detected_ns=103, planned=True)
    arbiter.latch("fault_tof_loss")
    watchdog.latch_fault("tof_loss")
    assert watchdog.tick(now_ns=104, output_sequence=2)["stale_reason"] == "fault_tof_loss"
    assert latch.snapshot().first_healthy_stop_ack_ns == 102


def test_fresh_normal_updates_remain_stopped_until_body_confirmation():
    latch, safety, watchdog, arbiter, _ = setup()
    first, _ = checked_update(latch, safety, readout(100, 1, 0.6), True)
    arbiter.neural_step(lambda: first)
    assert arbiter.publish(tick(watchdog, first, 101, 1),
                           lambda _: "robot_stop_refreshed") == "robot_stop_refreshed"
    for seq, t in ((2, 120), (3, 140), (4, 160)):
        update, held = checked_update(latch, safety, readout(t, seq, 0.0), False)
        assert held and update.behavior_intent["stop"]
        arbiter.neural_step(lambda update=update: update)
        output = tick(watchdog, update, t + 1, seq)
        assert output["watchdog_state"] == "healthy" and output["intent"]["stop"]
        assert arbiter.publish(output, lambda _: "robot_stop_refreshed") == "robot_stop_refreshed"
    # Only an independent pose observer may end the trial; neither fresh input nor ACK clears it.
    assert arbiter.latched.is_set()


def test_inflight_move_completes_before_latch_and_no_move_afterward():
    latch, safety, watchdog, arbiter, _ = setup()
    old = NeuralUpdate(readout(100, 1, 0.0), decoded(readout(100, 1, 0.0), False), {})
    output = tick(watchdog, old, 101, 1)
    entered, release = threading.Event(), threading.Event()
    sent = []

    def send(_output):
        entered.set()
        assert release.wait(2)
        sent.append("move")
        return "move"

    move = threading.Thread(target=lambda: arbiter.publish(output, send))
    move.start()
    assert entered.wait(2)
    stop, _ = checked_update(latch, safety, readout(120, 2, 0.6), True)
    stopping = threading.Thread(target=lambda: arbiter.neural_step(lambda: stop))
    stopping.start()
    assert not arbiter.latched.is_set()
    release.set()
    move.join(2)
    stopping.join(2)
    assert not move.is_alive() and not stopping.is_alive()
    assert sent == ["move"] and arbiter.latched.is_set()
    with unittest.TestCase().assertRaisesRegex(RuntimeError, "non-stop watchdog output"):
        arbiter.publish(output, send)
    with unittest.TestCase().assertRaises(RuntimeError):
        arbiter.move(lambda: ("move", 130, 131, 132))
    assert sent == ["move"]


class NeuralStopLatchTests(unittest.TestCase):
    def test_neural_then_fault(self):
        test_neural_then_fault_overrides_source_and_ack_attribution()

    def test_fault_then_neural(self):
        test_fault_then_neural_keeps_fault_authority()

    def test_fault_during_ack(self):
        test_fault_during_stop_ack_remains_highest_priority()

    def test_scheduler_ack_fault_order(self):
        test_scheduler_orders_inflight_ack_before_fault_transition()

    def test_fault_after_ack(self):
        test_fault_after_neural_ack_supersedes_future_outputs()

    def test_fresh_updates(self):
        test_fresh_normal_updates_remain_stopped_until_body_confirmation()

    def test_move_ordering(self):
        test_inflight_move_completes_before_latch_and_no_move_afterward()
