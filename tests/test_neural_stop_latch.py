"""P8-R1 high-level neural stop persistence and source-priority checks."""

import threading
import unittest
from types import SimpleNamespace

from microduck_connectome.control_contracts import make_behavior_intent
from microduck_connectome.neural_stop_latch import NeuralStopIntentLatch
from microduck_connectome.neural_stop_scheduler import NeuralStopRefreshScheduler
from microduck_connectome.p8_probe_motion_arbiter import ProbeMotionArbiter
from microduck_connectome.fault_stop import FaultStopLatch
from microduck_connectome.safety_clamp import SafetyClamp
from microduck_connectome.scheduler import NeuralUpdate
from microduck_connectome.watchdog import ControllerWatchdog
from scripts.p8_r1_stop_persistence_trial import (
    ensure_healthy_neutral_priming, last_pre_stop_state, neural_stop_origin,
    precondition_deadman_after_motion,
)
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


WATCHDOG_CONFIG = {"neural_readout_ttl_ms": 100, "behavior_intent_ttl_ms": 100}


def _readout(timestamp_ns, sequence, escape):
    return {"timestamp_ns": timestamp_ns, "sequence": sequence,
            "steering_left": 0.0, "steering_right": 0.0,
            "escape": escape, "runtime_healthy": True}


def _decoded(readout, stop):
    return make_behavior_intent(
        timestamp_ns=readout["timestamp_ns"], sequence=readout["sequence"],
        vx=0.0 if stop else 0.05, stop=stop,
        confidence=readout["escape"],
    )


def _tick(watchdog, readout, safe, timestamp_ns, sequence):
    assert watchdog.observe_neural(readout)
    assert watchdog.observe_behavior(safe["intent"])
    return watchdog.tick(now_ns=timestamp_ns, output_sequence=sequence)


def _mint(stop, timestamp_ns):
    watchdog = ControllerWatchdog(WATCHDOG_CONFIG)
    readout = _readout(timestamp_ns, 1, 0.6 if stop else 0.0)
    intent = _decoded(readout, stop)
    return _tick(watchdog, readout, {"intent": intent}, timestamp_ns + 1, 1)


def test_healthy_escape_persists_through_fresh_safety_and_watchdog_updates():
    latch = NeuralStopIntentLatch(escape_threshold=0.5)
    safety = SafetyClamp()
    watchdog = ControllerWatchdog(WATCHDOG_CONFIG)
    before = _readout(100_000_000, 1, 0.0)
    selected, safe, held = latch.apply(
        readout=before, decoded_intent=_decoded(before, False),
        safety=safety, now_ns=before["timestamp_ns"], graph_runtime_step=1)
    assert not selected["stop"] and not safe["intent"]["stop"] and not held
    first = _readout(120_000_000, 2, 0.6)
    selected, safe, held = latch.apply(
        readout=first, decoded_intent=_decoded(first, True),
        safety=safety, now_ns=first["timestamp_ns"], graph_runtime_step=2)
    assert selected["stop"] and safe["intent"]["stop"] and not held
    assert latch.snapshot().first_healthy_stop_ack_ns is None
    output = _tick(watchdog, first, safe, 121_000_000, 1)
    record = latch.confirm(
        output=output, transport_result="robot_stop_refreshed",
        ack_ns=122_000_000, source_neural_sequence=2,
        source_intent_stop=True)
    assert record.first_healthy_stop_ack_ns == 122_000_000
    assert (record.source, record.cause, record.graph_runtime_step) == (
        "healthy_neural_escape", "DNp01_EscapeDecoder", 2)
    later = _readout(140_000_000, 3, 0.0)
    selected, safe, held = latch.apply(
        readout=later, decoded_intent=_decoded(later, False),
        safety=safety, now_ns=later["timestamp_ns"], graph_runtime_step=3)
    assert held and selected["stop"] and safe["intent"]["stop"]
    assert selected["timestamp_ns"] == later["timestamp_ns"]
    assert selected["sequence"] == later["sequence"]
    output = _tick(watchdog, later, safe, 141_000_000, 2)
    assert output["watchdog_state"] == "healthy" and output["intent"]["stop"]
    assert latch.snapshot() == record


def test_earlier_inflight_ack_or_failed_ack_cannot_confirm_candidate():
    latch = NeuralStopIntentLatch(escape_threshold=0.5)
    safety = SafetyClamp()
    watchdog = ControllerWatchdog(WATCHDOG_CONFIG)
    earlier = _readout(100_000_000, 1, 0.0)
    earlier_stop = safety.apply(_decoded(earlier, True),
                                now_ns=earlier["timestamp_ns"], fallback_sequence=1)
    earlier_output = _tick(watchdog, earlier, earlier_stop, 101_000_000, 1)
    candidate = _readout(120_000_000, 2, 0.6)
    _, safe, _ = latch.apply(
        readout=candidate, decoded_intent=_decoded(candidate, True),
        safety=safety, now_ns=candidate["timestamp_ns"], graph_runtime_step=2)
    assert latch.confirm(output=earlier_output, transport_result="robot_stop_refreshed",
                         ack_ns=123_000_000, source_neural_sequence=1,
                         source_intent_stop=True).first_healthy_stop_ack_ns is None
    current = _tick(watchdog, candidate, safe, 121_000_000, 2)
    assert latch.confirm(output=current, transport_result="send_failed",
                         ack_ns=123_000_000, source_neural_sequence=2,
                         source_intent_stop=True).first_healthy_stop_ack_ns is None
    assert latch.confirm(output=current, transport_result="robot_stop_refreshed",
                         ack_ns=124_000_000, source_neural_sequence=2,
                         source_intent_stop=True).first_healthy_stop_ack_ns == 124_000_000


def test_fault_and_stale_watchdog_sources_override_neural_candidate():
    latch = NeuralStopIntentLatch(escape_threshold=0.5)
    safety = SafetyClamp()
    watchdog = ControllerWatchdog(WATCHDOG_CONFIG)
    first = _readout(100_000_000, 1, 0.6)
    _, safe, _ = latch.apply(readout=first, decoded_intent=_decoded(first, True),
                             safety=safety, now_ns=first["timestamp_ns"],
                             graph_runtime_step=1)
    _tick(watchdog, first, safe, 101_000_000, 1)
    stale = watchdog.tick(now_ns=202_000_000, output_sequence=2)
    assert stale["watchdog_state"] == "safe_stop"
    assert stale["stale_reason"] == "stale_neural"
    assert latch.confirm(output=stale, transport_result="robot_stop_refreshed",
                         ack_ns=203_000_000, source_neural_sequence=1,
                         source_intent_stop=True).first_healthy_stop_ack_ns is None
    watchdog.latch_fault("camera_loss")
    newer = _readout(220_000_000, 2, 0.0)
    selected, safe, held = latch.apply(readout=newer,
        decoded_intent=_decoded(newer, False), safety=safety,
        now_ns=newer["timestamp_ns"], graph_runtime_step=2)
    assert held and selected["stop"] and safe["intent"]["stop"]
    fault = _tick(watchdog, newer, safe, 221_000_000, 3)
    assert fault["watchdog_state"] == "safe_stop"
    assert fault["stale_reason"] == "fault_camera_loss"
    assert latch.confirm(output=fault, transport_result="robot_stop_refreshed",
                         ack_ns=222_000_000, source_neural_sequence=2,
                         source_intent_stop=True).first_healthy_stop_ack_ns is None


def test_held_ack_uses_origin_escape_not_current_readout():
    latch = NeuralStopIntentLatch(escape_threshold=0.5)
    safety = SafetyClamp()
    watchdog = ControllerWatchdog(WATCHDOG_CONFIG)
    first = _readout(120_000_000, 2, 0.6)
    latch.apply(readout=first, decoded_intent=_decoded(first, True),
                safety=safety, now_ns=first["timestamp_ns"],
                graph_runtime_step=2)
    later = _readout(140_000_000, 3, 0.0)
    _, safe, held = latch.apply(readout=later,
        decoded_intent=_decoded(later, False), safety=safety,
        now_ns=later["timestamp_ns"], graph_runtime_step=3)
    assert held
    output = _tick(watchdog, later, safe, 141_000_000, 1)
    latch.confirm(output=output, transport_result="robot_stop_refreshed",
                  ack_ns=142_000_000, source_neural_sequence=3,
                  source_intent_stop=True)
    chain = SimpleNamespace(neural_stop_latch=latch, graph_identity="graph-v2",
        neural_ledger=[{
            "runtime_step": 2, "dn_sequence": 2,
            "dn_timestamp_ns": 120_000_000, "dn_escape": 0.6,
            "raw_decoder_stop": True, "post_safety_stop": True,
            "dn_runtime_healthy": True, "male_cns_healthy": True,
            "graph_identity": "graph-v2",
        }])
    ack_record = {
        "robot_state": {"publish_ack_returned_ns": 142_000_000},
        "watchdog_state": "healthy", "pre_safety_intent": {"stop": True},
        "post_safety_intent": {"stop": True},
        "robot_facing_command_type": "robot.stop",
        "robotd_transport_result": "robot_stop_refreshed",
        "dn_activity": {"sequence": 3, "escape": 0.0},
    }
    origin = neural_stop_origin(chain, ack_record, threshold=0.5)
    assert origin is not None
    assert origin[0].neural_sequence == 2
    assert origin[1]["dn_escape"] == 0.6
    assert ack_record["dn_activity"]["escape"] == 0.0
    assert neural_stop_origin(chain, ack_record, threshold=0.7) is None


def test_motion_arbiter_serializes_inflight_move_then_rejects_all_post_stop_moves():
    arbiter = ProbeMotionArbiter()
    entered = threading.Event()
    release = threading.Event()
    outcomes = []

    def delayed_move():
        entered.set()
        assert release.wait(1)
        return "accepted", 10, 11, 12

    moving = threading.Thread(target=lambda: outcomes.append(arbiter.move(delayed_move)))
    moving.start()
    assert entered.wait(1)
    readout = _readout(20, 1, 0.6)
    stop = _decoded(readout, True)
    update = NeuralUpdate(readout, stop, {"neural_stop_latch": {
        "source": "healthy_neural_escape"}})
    stopping = threading.Thread(target=lambda: arbiter.neural_step(lambda: update))
    stopping.start()
    release.set()
    moving.join(1)
    stopping.join(1)
    assert outcomes and arbiter.latch_reason == "healthy_neural_escape"
    assert arbiter.move_transactions[0]["ack_ns"] == 12
    stop_output = _mint(True, 25)
    assert arbiter.publish(stop_output,
                           lambda output: "robot_stop_refreshed") == "robot_stop_refreshed"
    assert arbiter.first_stop_ack_ns is not None
    try:
        arbiter.publish(_mint(False, 30), lambda output: "move")
        assert False, "non-stop output was accepted after latch"
    except RuntimeError as error:
        assert "non-stop watchdog output" in str(error)
    try:
        arbiter.move(lambda: ("accepted", 30, 31, 32))
        assert False, "move was accepted after latch"
    except RuntimeError:
        pass


def test_nonstop_publish_finishes_before_concurrent_neural_latch():
    arbiter = ProbeMotionArbiter()
    send_entered = threading.Event()
    release_send = threading.Event()
    stop_started = threading.Event()
    ordering = []

    def send(output):
        ordering.append("send_start")
        send_entered.set()
        assert release_send.wait(1)
        ordering.append("send_end")
        return "move"

    publishing = threading.Thread(target=lambda: arbiter.publish(_mint(False, 100), send))
    publishing.start()
    assert send_entered.wait(1)
    readout = _readout(120, 2, 0.6)
    update = NeuralUpdate(readout, _decoded(readout, True),
                          {"neural_stop_latch": {"source": "healthy_neural_escape"}})

    def latch_after_send():
        stop_started.set()
        arbiter.neural_step(lambda: update)
        ordering.append("latch")

    stopping = threading.Thread(target=latch_after_send)
    stopping.start()
    assert stop_started.wait(1)
    assert not arbiter.latched.is_set()
    release_send.set()
    publishing.join(1)
    stopping.join(1)
    assert not publishing.is_alive() and not stopping.is_alive()
    assert ordering == ["send_start", "send_end", "latch"]
    with unittest.TestCase().assertRaisesRegex(RuntimeError, "non-stop watchdog output"):
        arbiter.publish(_mint(False, 140), send)
    assert ordering == ["send_start", "send_end", "latch"]


def test_scheduler_publishes_candidate_before_control_reads_latest():
    arbiter = ProbeMotionArbiter()
    fault = FaultStopLatch()
    watchdog = ControllerWatchdog(WATCHDOG_CONFIG)
    candidate_ready = threading.Event()
    release_candidate = threading.Event()
    outputs = []
    old = _readout(100, 1, 0.0)
    new = _readout(120, 2, 0.6)
    old_update = NeuralUpdate(old, _decoded(old, False), {})
    candidate = NeuralUpdate(new, _decoded(new, True),
                             {"neural_stop_latch": {"source": "healthy_neural_escape"}})

    def neural_step(frame, now_ns):
        result = arbiter.neural_step(lambda: candidate)
        candidate_ready.set()
        assert release_candidate.wait(1)
        return result

    def publish(output):
        outputs.append(output)
        return arbiter.publish(output,
            lambda current: "robot_stop_refreshed" if current["intent"]["stop"] else "move")

    scheduler = NeuralStopRefreshScheduler(
        motion_arbiter=arbiter, fault_latch=fault,
        config=ROOT / "config/scheduler_v1.json", watchdog=watchdog,
        perception_step=lambda now_ns: None, neural_step=neural_step,
        publisher=publish,
    )
    scheduler._perception.put({"timestamp_ns": 120}, 120)
    scheduler._neural.put(old_update, 100)
    neural_thread = threading.Thread(target=lambda: scheduler._neural_tick(120))
    neural_thread.start()
    assert candidate_ready.wait(1) and arbiter.latched.is_set()
    control_thread = threading.Thread(target=lambda: scheduler._control_tick(121))
    control_thread.start()
    release_candidate.set()
    neural_thread.join(1)
    control_thread.join(1)
    assert not neural_thread.is_alive() and not control_thread.is_alive()
    assert len(outputs) == 1
    assert outputs[0]["watchdog_state"] == "healthy"
    assert outputs[0]["intent"]["stop"]
    assert arbiter.first_stop_ack_ns is not None
    assert scheduler._neural.get()[0] is candidate


def test_fault_before_ack_overrides_pending_neural_attribution():
    arbiter = ProbeMotionArbiter()
    fault = FaultStopLatch()
    latch = NeuralStopIntentLatch(escape_threshold=0.5)
    safety = SafetyClamp()
    watchdog = ControllerWatchdog(WATCHDOG_CONFIG)
    readout = _readout(120, 2, 0.6)
    _, safe, _ = latch.apply(readout=readout,
        decoded_intent=_decoded(readout, True), safety=safety,
        now_ns=120, graph_runtime_step=2)
    update = NeuralUpdate(readout, safe["intent"],
        {"neural_stop_latch": {"source": "healthy_neural_escape"}})
    arbiter.neural_step(lambda: update)
    observed = []

    def observe(source, output, result):
        observed.append(output)
        latch.confirm(output=output, transport_result=result,
                      ack_ns=122, source_neural_sequence=source.readout["sequence"],
                      source_intent_stop=source.behavior_intent["stop"])

    scheduler = NeuralStopRefreshScheduler(
        motion_arbiter=arbiter, fault_latch=fault,
        config=ROOT / "config/scheduler_v1.json", watchdog=watchdog,
        perception_step=lambda now_ns: None, neural_step=lambda frame, now_ns: None,
        publisher=lambda output: arbiter.publish(output,
            lambda current: "robot_stop_refreshed"),
        control_observer=observe,
    )
    scheduler._neural.put(update, 120)
    fault.latch("camera_loss", detected_ns=121, planned=True)
    scheduler._control_tick(121)
    assert len(observed) == 1
    assert observed[0]["watchdog_state"] == "safe_stop"
    assert observed[0]["stale_reason"] == "fault_camera_loss"
    assert latch.snapshot().first_healthy_stop_ack_ns is None


def test_priming_stop_is_invalid_before_scheduler_handoff():
    latch = NeuralStopIntentLatch(escape_threshold=0.5)
    chain = SimpleNamespace(neural_stop_latch=latch)
    healthy = _readout(100, 1, 0.0)
    ensure_healthy_neutral_priming(chain, NeuralUpdate(
        healthy, _decoded(healthy, False), {}))
    with unittest.TestCase().assertRaisesRegex(RuntimeError, "during priming"):
        ensure_healthy_neutral_priming(chain, NeuralUpdate(
            healthy, _decoded(healthy, True), {}))
    unhealthy = dict(healthy, runtime_healthy=False)
    with unittest.TestCase().assertRaisesRegex(RuntimeError, "during priming"):
        ensure_healthy_neutral_priming(chain, NeuralUpdate(
            unhealthy, _decoded(healthy, False), {}))


def test_pre_stop_state_excludes_late_arriving_sample():
    history = [{"state_received_ns": 90, "state": "prior"},
               {"state_received_ns": 101, "state": "after_stop_call"}]
    assert last_pre_stop_state(history, 100)["state"] == "prior"
    assert last_pre_stop_state(history, 89) is None


def test_precondition_deadman_uses_sample_time_after_established_motion():
    rows = [
        {"robot_state": {"robot_t_ns": 90, "limited_by": ["deadman"]}},
        {"robot_state": {"robot_t_ns": 101, "limited_by": []}},
    ]
    assert not precondition_deadman_after_motion(rows, 100)
    rows.append({"robot_state": {"robot_t_ns": 102, "limited_by": ["deadman"]}})
    assert precondition_deadman_after_motion(rows, 100)
    assert precondition_deadman_after_motion(rows[:1], None)
    rows[-1]["robot_state"]["robot_t_ns"] = None
    assert precondition_deadman_after_motion(rows, 100)


class NeuralStopLatchTests(unittest.TestCase):
    def test_healthy_escape_persists(self):
        test_healthy_escape_persists_through_fresh_safety_and_watchdog_updates()

    def test_earlier_or_failed_ack(self):
        test_earlier_inflight_ack_or_failed_ack_cannot_confirm_candidate()

    def test_fault_priority(self):
        test_fault_and_stale_watchdog_sources_override_neural_candidate()

    def test_held_ack_origin(self):
        test_held_ack_uses_origin_escape_not_current_readout()

    def test_motion_race(self):
        test_motion_arbiter_serializes_inflight_move_then_rejects_all_post_stop_moves()

    def test_publish_race(self):
        test_nonstop_publish_finishes_before_concurrent_neural_latch()

    def test_scheduler_handoff_race(self):
        test_scheduler_publishes_candidate_before_control_reads_latest()

    def test_fault_before_ack(self):
        test_fault_before_ack_overrides_pending_neural_attribution()

    def test_priming_stop(self):
        test_priming_stop_is_invalid_before_scheduler_handoff()

    def test_pre_stop_sample_order(self):
        test_pre_stop_state_excludes_late_arriving_sample()

    def test_precondition_deadman_sample_time(self):
        test_precondition_deadman_uses_sample_time_after_established_motion()
