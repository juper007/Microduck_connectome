"""Frozen diagnostic matrix and non-result-driven scoring checks."""
import copy
import json
import math
from pathlib import Path
import time
from unittest import mock

from scripts.p8_03_r3_yaw_diagnostic import matrix, sampled, score, trace_integrity

PROTOCOL = json.loads((Path(__file__).parents[1] /
                       "config/p8_03_r3_yaw_diagnostic_v1.json").read_text())


def records():
    rows = matrix(PROTOCOL)
    for row in rows:
        row["result"] = "VALID"
        row["delta_heading_rad"] = (
            .02 if row["condition"] == "positive" else
            -.02 if row["condition"] == "negative" else .001)
    return rows


def test_frozen_matrix_is_disjoint_balanced_and_development_only():
    rows = matrix(PROTOCOL)
    assert len(rows) == 50
    assert [row["seed"] for row in rows] == list(range(887700, 887750))
    assert [sum(row["condition"] == condition for row in rows)
            for condition in ("positive", "negative", "sham")] == [20, 20, 10]
    assert [row["condition"] for row in rows[:5]] == [
        "positive", "negative", "sham", "negative", "positive"]
    assert [row["condition"] for row in rows[5:10]] == [
        "negative", "positive", "sham", "positive", "negative"]
    assert all(seed not in range(887400, 887620) for seed in
               [row["seed"] for row in rows])


def test_scoring_uses_sham_floor_and_requires_every_direction():
    rows = records()
    with mock.patch(
        "scripts.p8_03_r3_yaw_diagnostic.trace_integrity", return_value=True
    ):
        passed = score(PROTOCOL, rows)
        assert passed["result"] == "PASS"
        assert passed["noise_floor_rad"] == .005
        changed = copy.deepcopy(rows)
        changed[0]["delta_heading_rad"] = .001
        failed = score(PROTOCOL, changed)
        assert failed["result"] == "FAIL"
        assert failed["classifications"]["D00"] == "INCONCLUSIVE"
        changed = copy.deepcopy(rows)
        changed[0]["delta_heading_rad"] = -.02
        assert score(PROTOCOL, changed)["classifications"]["D00"] == "WRONG_SIGN"
        changed = copy.deepcopy(rows)
        sham = next(row for row in changed if row["condition"] == "sham")
        sham["delta_heading_rad"] = .019
        assert score(PROTOCOL, changed)["result"] == "FAIL"
        assert math.isclose(score(PROTOCOL, changed)["noise_floor_rad"], .021)


def test_missing_or_unverified_raw_cannot_pass():
    rows = records()
    assert score(PROTOCOL, rows[:-1])["result"] == "FAIL"
    assert score(PROTOCOL, rows)["result"] == "FAIL"
    assert trace_integrity(rows[0], matrix(PROTOCOL)[0]) is False


def test_pose_wait_accepts_next_sim_tick_and_rejects_wrong_policy():
    now = time.monotonic_ns()
    previous = {"request_ns": now - 20_000_000,
                "response_ns": now - 20_000_000, "sim_time_s": 1.0,
                "x_m": .03457887954384973, "y_m": .0010909211238251523,
                "trunk_z_m": .11587609862790209, "heading_rad": .11693358424258107,
                "roll_rad": 0., "pitch_rad": 0.}
    stale = dict(previous, request_ns=now, response_ns=now)
    fresh = dict(previous, request_ns=now + 1_000_000,
                 response_ns=now + 2_000_000, sim_time_s=1.02)
    reader = mock.Mock()
    reader.read.side_effect = [stale, fresh]
    stream = mock.Mock()
    stream.state.return_value = {
        "safety": {"fallen": False, "limp": False}, "policy": "stand",
        "t_ns": 100, "move": {"requested": [0, 0, 0],
                              "applied": [0, 0, 0], "limited_by": []}}
    assert sampled(reader, stream, previous, previous, moving=False)["pose"] == fresh
    assert reader.read.call_count == 2
    reader.read.side_effect = [fresh]
    stream.state.return_value["policy"] = "sit"
    try:
        sampled(reader, stream, previous, previous, moving=False)
    except RuntimeError as error:
        assert "policy" in str(error)
    else:
        raise AssertionError("wrong policy state accepted")
