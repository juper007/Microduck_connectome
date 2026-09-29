"""Prospective generation gate tests; historical lineage is unchanged."""

import json

import pytest

from microduck_connectome.p8_03_causal_precondition_v1 import (
    CausalPreconditionError, evaluate_causal_precondition,
)


START = 10_000_000_000
GATE = {"duration_s": 1.5, "command_period_ms": 20,
        "minimum_trunk_displacement_m": .01, "minimum_pose_speed_mps": .015,
        "minimum_speed_sustain_ms": 200, "minimum_fresh_applied_vx_mps": .04,
        "maximum_state_age_ms": 100, "maximum_pose_age_ms": 100}


def fixture():
    rows = []
    def move(ident, generation, sent):
        request = {"jsonrpc": "2.0", "id": ident, "method": "robot.move",
                   "params": {"vx": .05, "vy": 0, "vyaw": 0}}
        ack = {"jsonrpc": "2.0", "id": ident,
               "result": {"accepted": True, "accepted_move_generation": generation}}
        rows.extend(({"kind": "robot.move.request", "sent_at_ns": sent,
                      "wire": json.dumps(request) + "\n"},
                     {"kind": "robot.move.ack", "received_at_ns": sent + 100_000,
                      "wire": json.dumps(ack) + "\n"}))
    def state(tick, generation, received, *, limited=None):
        rows.append({"kind": "robot.state", "received_at_ns": received,
                     "state": {"control_tick_sequence": tick,
                               "consumed_move_generation": generation,
                               "t_ns": received - 1_000_000, "policy": "walk",
                               "move": {"requested": [.05, 0, 0],
                                        "applied": [.05, 0, 0],
                                        "limited_by": limited or []},
                               "safety": {"fallen": False, "limp": False}}})
    state(1, 0, START - 20_000_000, limited=["deadman"])
    for i in range(81):
        sent = START - 1_000_000 if i == 0 else START + i * 20_000_000 - 1_000_000
        move(i + 1, i + 1, sent)
        state(i + 2, i + 1, START + i * 20_000_000)
    state(83, 82, START + 1_620_000_000)
    poses = [{"timestamp_ns": START + i * 20_000_000,
              "request_ns": START + i * 20_000_000 - 1_000_000,
              "x_m": i * .0006, "y_m": 0., "raw_body_packet": "{}"}
             for i in range(81)]
    return rows, poses


def score(tmp_path, rows, poses, *, end=START + 1_610_000_000):
    path = tmp_path / "diagnostic.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return evaluate_causal_precondition(path, poses, pre_move_tick=1,
                                        stop_sent_ns=end, gate=GATE)


def test_old_generation_deadman_retained_outside_window(tmp_path):
    rows, poses = fixture()
    result = score(tmp_path, rows, poses)
    assert result["result"] == "PASS"
    assert result["first_causal_tick"] == 2
    assert result["deadman_count_in_window"] == 0


def test_first_consumed_deadman_fails_and_later_clean_cannot_erase(tmp_path):
    rows, poses = fixture()
    first = next(r for r in rows if r["kind"] == "robot.state" and
                 r["state"]["control_tick_sequence"] == 2)
    first["state"]["move"]["limited_by"] = ["deadman"]
    with pytest.raises(CausalPreconditionError, match="deadman"):
        score(tmp_path, rows, poses)


def test_later_fault_fails(tmp_path):
    rows, poses = fixture()
    states = [r for r in rows if r["kind"] == "robot.state"]
    states[20]["state"]["safety"]["fallen"] = True
    with pytest.raises(CausalPreconditionError, match="safety"):
        score(tmp_path, rows, poses)


def test_superseded_and_same_valued_distinct(tmp_path):
    rows, poses = fixture()
    states = [r for r in rows if r["kind"] == "robot.state"]
    states[1]["state"]["consumed_move_generation"] = 0
    result = score(tmp_path, rows, poses)
    assert result["superseded_before_consumption"] == [1]
    assert result["first_consumed_generation"] == 2
    assert result["first_causal_tick"] == 3
    assert result["accepted_move_generations"][:2] == [1, 2]


@pytest.mark.parametrize("change,reason", [
    ("gap", "tick gap"), ("regression", "generation regression"),
    ("missing", "consumed generation"), ("reconnect", "diagnostic stream failed"),
])
def test_stream_fails_closed(tmp_path, change, reason):
    rows, poses = fixture()
    states = [r for r in rows if r["kind"] == "robot.state"]
    if change == "gap":
        states[5]["state"]["control_tick_sequence"] += 1
    elif change == "regression":
        states[5]["state"]["consumed_move_generation"] = 0
    elif change == "missing":
        del states[5]["state"]["consumed_move_generation"]
    else:
        rows.append({"kind": "diagnostic.failure", "error": "reconnected"})
    with pytest.raises(CausalPreconditionError, match=reason):
        score(tmp_path, rows, poses)


def test_physical_movement_required(tmp_path):
    rows, poses = fixture()
    for p in poses:
        p["x_m"] = 0.
    with pytest.raises(CausalPreconditionError, match="physical movement"):
        score(tmp_path, rows, poses)


def test_duration_starts_at_causal_state(tmp_path):
    rows, poses = fixture()
    states = [r for r in rows if r["kind"] == "robot.state"]
    for row in states[75:-1]:
        rows.remove(row)
    states[-1]["state"]["control_tick_sequence"] = 76
    with pytest.raises(CausalPreconditionError, match="causal duration"):
        score(tmp_path, rows, poses)


def test_no_eligibility_before_complete_gate(tmp_path):
    rows, poses = fixture()
    with pytest.raises(CausalPreconditionError):
        score(tmp_path, rows, poses, end=START + 1_000_000_000)


def test_initial_cadence_gap_fails(tmp_path):
    rows, poses = fixture()
    for row in rows:
        if row["kind"] == "robot.move.request" and START <= row["sent_at_ns"] < START + 100_000_000:
            row["sent_at_ns"] += 100_000_000
    with pytest.raises(CausalPreconditionError, match="cadence"):
        score(tmp_path, rows, poses)


def test_late_delivery_of_pre_stop_deadman_fails(tmp_path):
    rows, poses = fixture()
    states = [r for r in rows if r["kind"] == "robot.state"]
    states[-2]["received_at_ns"] = START + 1_615_000_000
    states[-2]["state"]["move"]["limited_by"] = ["deadman"]
    with pytest.raises(CausalPreconditionError, match="deadman"):
        score(tmp_path, rows, poses)


def test_unknown_writer_before_barrier_cannot_close_window(tmp_path):
    rows, poses = fixture()
    states = [r for r in rows if r["kind"] == "robot.state"]
    states[-2]["state"]["consumed_move_generation"] = 82
    states[-1]["state"]["consumed_move_generation"] = 83
    with pytest.raises(CausalPreconditionError, match="unattributed generation"):
        score(tmp_path, rows, poses)


def test_historical_lineage_remains_separate():
    from scripts.p8_03_precondition_lineage import acquisition_contaminated
    assert acquisition_contaminated([{"state": {"move": {"limited_by": ["deadman"]},
                                              "safety": {}}}]) is True
