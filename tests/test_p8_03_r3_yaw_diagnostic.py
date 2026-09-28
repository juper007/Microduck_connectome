"""Frozen diagnostic matrix and non-result-driven scoring checks."""
import copy
import hashlib
import json
import math
from pathlib import Path
import tempfile
import time
from unittest import mock

from scripts.p8_03_r3_yaw_diagnostic import (
    R1_CONFIG, REFERENCE, heading_median, matrix, sampled, score, score_root,
    trace_integrity, wrapped_delta,
)

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


def complete_record(item):
    yaw = {"positive": .2, "negative": -.2, "sham": 0.}[item["condition"]]
    final_heading = REFERENCE["heading_rad"] + (
        .02 if yaw > 0 else -.02 if yaw < 0 else 0.)

    def samples(count, start_s, interval_s, heading, policy, applied_yaw=0.):
        result = []
        for index in range(count):
            seconds = start_s + index * interval_s
            tick_ns = round(seconds * 1e9)
            result.append({
                "pose": {"request_ns": tick_ns, "response_ns": tick_ns + 1_000_000,
                         "sim_time_s": seconds, "x_m": REFERENCE["x_m"],
                         "y_m": REFERENCE["y_m"],
                         "trunk_z_m": REFERENCE["trunk_z_m"],
                         "heading_rad": heading, "roll_rad": 0., "pitch_rad": 0.},
                "robot_t_ns": tick_ns, "requested": [0., 0., applied_yaw],
                "applied": [0., 0., applied_yaw], "limited_by": [],
                "policy": policy, "safety": {"fallen": False, "limp": False}})
        return result

    initial = samples(21, 1., .05, REFERENCE["heading_rad"], "stand")
    moving = samples(10, 2.02, .02, final_heading, "walk", yaw)
    stopped = samples(21, 2.25, .05, final_heading, "stand")
    final = samples(21, 3.35, .05, final_heading, "stand")
    requests = [{"ack": {"accepted": True}, "call_ns": 2_000_000_000 + i * 20_000_000,
                 "write_ns": 2_000_100_000 + i * 20_000_000,
                 "ack_ns": 2_001_000_000 + i * 20_000_000}
                for i in range(10)]
    return dict(item, result="VALID", initial_stop={"result": "PASS"},
                cleanup_stop={"result": "PASS"}, down_before_exit=0, up_exit=0,
                down_after_exit=0, final_probe={"result": "PASS"},
                health={"healthy": True, "degraded": False},
                policy_verified={"loaded_walk_sha256":
                                 R1_CONFIG["walking_policy_sha256"]},
                initial_plateau=initial,
                pulses=[{"vyaw_radps": yaw, "duration_s": .2,
                         "active_through_stop_s": .23,
                         "stop": {"result": "PASS"}, "requests": requests,
                         "trajectory": moving, "post_stop_trajectory": stopped,
                         "plateau": final}],
                delta_heading_rad=wrapped_delta(
                    heading_median(final), heading_median(initial)))


def test_frozen_matrix_is_disjoint_balanced_and_development_only():
    rows = matrix(PROTOCOL)
    assert PROTOCOL["command"]["pulse_count"] == 1
    assert (.2 * .3 < PROTOCOL["command"]["max_command_integral_rad"])
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


def test_complete_raw_traces_score_and_safety_faults_fail():
    items = matrix(PROTOCOL)
    rows = [complete_record(item) for item in items]
    assert all(trace_integrity(row, item) for row, item in zip(rows, items))
    assert score(PROTOCOL, rows)["result"] == "PASS"
    corrupted = copy.deepcopy(rows)
    corrupted[0]["pulses"][0]["trajectory"][2]["policy"] = "stand"
    assert score(PROTOCOL, corrupted)["result"] == "FAIL"
    corrupted = copy.deepcopy(rows)
    corrupted[0]["pulses"][0]["trajectory"][2]["pose"]["x_m"] += .02
    assert score(PROTOCOL, corrupted)["result"] == "FAIL"
    corrupted = copy.deepcopy(rows)
    corrupted[0]["pulses"][0]["requests"][2]["call_ns"] += 20_000_000
    assert score(PROTOCOL, corrupted)["result"] == "FAIL"


def test_downloaded_manifest_covers_every_scored_trace():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        entries = []
        for item in matrix(PROTOCOL):
            folder = root / item["id"]
            folder.mkdir()
            raw = json.dumps(complete_record(item), sort_keys=True).encode()
            path = folder / "trace.json"
            path.write_bytes(raw)
            entries.append({"path": f"{item['id']}/trace.json",
                            "sha256": hashlib.sha256(raw).hexdigest(),
                            "bytes": len(raw), "record_count": 1})
        manifest = {"schema_version": "p8-03-r3-manifest-v1",
                    "files": entries, "source_head": "synthetic"}
        (root / "manifest.json").write_text(json.dumps(manifest))
        assert score_root(root)["result"] == "PASS"
        (root / "D00" / "trace.json").write_bytes(b"{}")
        try:
            score_root(root)
        except RuntimeError as error:
            assert "manifest mismatch" in str(error)
        else:
            raise AssertionError("altered raw trace accepted")
        (root / "D00" / "trace.json").write_bytes(
            json.dumps(complete_record(matrix(PROTOCOL)[0]), sort_keys=True).encode())
        manifest["files"] = entries[1:]
        (root / "manifest.json").write_text(json.dumps(manifest))
        try:
            score_root(root)
        except RuntimeError as error:
            assert "inventory mismatch" in str(error)
        else:
            raise AssertionError("unlisted raw trace accepted")
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
    try:
        sampled(reader, stream, previous, previous,
                moving=True, require_walk=True)
    except RuntimeError as error:
        assert "walk policy" in str(error)
    else:
        raise AssertionError("stand accepted during active yaw")
    reader.read.side_effect = [fresh]
    stream.state.return_value["policy"] = "walk"
    assert sampled(reader, stream, previous, previous,
                   moving=True, require_walk=True)["policy"] == "walk"
    reader.read.side_effect = [fresh]
    stream.state.return_value["policy"] = "sit"
    try:
        sampled(reader, stream, previous, previous, moving=False)
    except RuntimeError as error:
        assert "policy" in str(error)
    else:
        raise AssertionError("wrong policy state accepted")
