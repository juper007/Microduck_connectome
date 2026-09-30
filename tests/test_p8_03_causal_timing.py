"""Prospective causal timing arm tests using the frozen CPDEV state fixture."""

import json

import pytest

from microduck_connectome.p8_03_causal_timing import (
    CausalTimingError, evaluate_causal_arm)
from scripts.p8_03_timing_score import (
    _body_motion_continuous, _distinct_visual_slots,
    _scored_generations_consumed)
from test_p8_03_causal_precondition_v2 import START, GATE, fixture


ARM = START + 1_610_000_000


def check(tmp_path, rows, poses, *, end=None):
    path = tmp_path / "diagnostic.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return evaluate_causal_arm(path, poses, pre_move_tick=1,
                               arm_ns=ARM, gate=GATE, scored_end_ns=end)


def test_causal_arm_uses_first_consumed_generation_and_qualified_pose(tmp_path):
    rows, poses = fixture()
    proof = check(tmp_path, rows, poses)
    assert proof["result"] == "PASS"
    assert proof["duration_start"] == "FIRST_CAUSAL_TICK"
    assert proof["first_causal_tick"] == 2
    assert proof["first_qualifying_tick"] >= 2
    assert proof["postqualification_displacement_m"] >= .01
    assert proof["prearm_command_count"] >= 75


@pytest.mark.parametrize("change,reason", [
    ("deadman", "deadman"), ("tick_gap", "tick"),
    ("generation_regression", "generation"), ("stopped_body", "moving"),
    ("missing_ack", "incomplete"), ("stale_endpoint", "freshness"),
])
def test_prearm_failures_cannot_arm(tmp_path, change, reason):
    rows, poses = fixture()
    states = [row for row in rows if row["kind"] == "robot.state"]
    if change == "deadman":
        states[1]["state"]["move"]["limited_by"] = ["deadman"]
    elif change == "tick_gap":
        states[12]["state"]["control_tick_sequence"] += 1
    elif change == "generation_regression":
        states[12]["state"]["consumed_move_generation"] = 0
    elif change == "stopped_body":
        for pose in poses:
            pose["x_m"] = 0.
    elif change == "missing_ack":
        rows.remove(next(row for row in rows if row["kind"] == "robot.move.ack"))
    else:
        states[-2]["received_at_ns"] = ARM - 150_000_000
    with pytest.raises(CausalTimingError, match=reason):
        check(tmp_path, rows, poses)


def scored_fixture():
    rows, poses = fixture()
    rows.pop()  # Remove the CPDEV stop-generation state.
    for i in range(51):
        ident = 82 + i
        received = START + 1_620_000_000 + i * 20_000_000
        request = {"jsonrpc": "2.0", "id": ident, "method": "robot.move",
                   "params": {"vx": .05, "vy": 0, "vyaw": 0}}
        ack = {"jsonrpc": "2.0", "id": ident,
               "result": {"accepted": True, "accepted_move_generation": ident}}
        rows.extend((
            {"kind": "robot.move.request", "sent_at_ns": received - 2_000_000,
             "wire": json.dumps(request) + "\n"},
            {"kind": "robot.move.ack", "received_at_ns": received - 1_000_000,
             "wire": json.dumps(ack) + "\n"},
            {"kind": "robot.state", "received_at_ns": received,
             "state": {"control_tick_sequence": ident + 1,
                       "consumed_move_generation": ident,
                       "t_ns": received - 500_000, "policy": "walk",
                       "move": {"requested": [.05, 0, 0], "applied": [.05, 0, 0]},
                       "safety": {"fallen": False, "limp": False}}}))
    return rows, poses


def test_scored_stream_requires_real_contiguous_states_and_barrier(tmp_path):
    rows, poses = scored_fixture()
    proof = check(tmp_path, rows, poses, end=ARM + 1_000_000_000)
    assert proof["scored_state_count"] == 50
    rows[-4]["state"]["move"]["limited_by"] = ["deadman"]
    with pytest.raises(CausalTimingError, match="deadman"):
        check(tmp_path, rows, poses, end=ARM + 1_000_000_000)


def test_scored_gap_and_missing_barrier_fail(tmp_path):
    rows, poses = scored_fixture()
    rows.pop()
    with pytest.raises(CausalTimingError, match="barrier"):
        check(tmp_path, rows, poses, end=ARM + 1_000_000_000)
    rows, poses = scored_fixture()
    states = [row for row in rows if row["kind"] == "robot.state"]
    rows.remove(states[-10])
    with pytest.raises(CausalTimingError, match="tick"):
        check(tmp_path, rows, poses, end=ARM + 1_000_000_000)


def test_visual_frames_must_occupy_each_distinct_slot():
    frames = [{"timestamp_ns": ARM + i * 50_000_000} for i in range(20)]
    assert _distinct_visual_slots(frames, ARM)
    frames[1]["timestamp_ns"] = frames[0]["timestamp_ns"] + 1
    assert not _distinct_visual_slots(frames, ARM)


def test_each_scored_ack_generation_requires_scored_state_consumption():
    motion = [{"result": {"accepted_move_generation": i + 1},
               "move_ack_ns": ARM + i * 20_000_000} for i in range(50)]
    rows = [{"kind": "robot.move.ack", "received_at_ns": row["move_ack_ns"],
             "wire": json.dumps({"result": row["result"]})}
            for row in motion]
    rows.extend({"kind": "robot.state",
                 "state": {"t_ns": row["move_ack_ns"] + 1,
                           "consumed_move_generation": row["result"]["accepted_move_generation"]}}
                for row in motion)
    assert _scored_generations_consumed(motion, rows, ARM, ARM + 1_000_000_000)
    rows[-1]["state"]["consumed_move_generation"] = 49
    assert not _scored_generations_consumed(motion, rows, ARM, ARM + 1_000_000_000)


def test_causal_body_continuity_rejects_one_stopped_interval():
    poses = [(ARM + i * 20_000_000, i * .001, 0.) for i in range(50)]
    gate = {"minimum_pose_speed_mps": .02,
            "minimum_trunk_displacement_m": .01}
    assert _body_motion_continuous(poses, gate, causal=True)
    poses[25] = (poses[25][0], poses[24][1], 0.)
    assert not _body_motion_continuous(poses, gate, causal=True)
