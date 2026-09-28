"""Focused R5 matrix, durability, phase, and fail-closed scoring checks."""
import json
import math
from pathlib import Path
import time
from unittest import mock

import pytest

import scripts.p8_03_r5_yaw_coupling as runner
from scripts.p8_03_r5_score import (expected_matrix, phase_metrics, read_journal,
                                   score, score_root, verify_trace)

PROTOCOL = json.loads((Path(__file__).parents[1] /
                       "config/p8_03_r5_yaw_coupling_v1.json").read_text())


def pose(t, ns, x=0.):
    return {"request_ns": ns - 1_000_000, "response_ns": ns,
            "raw_body_packet": "raw", "sim_time_s": t,
            "x_m": runner.REFERENCE["x_m"] + x,
            "y_m": runner.REFERENCE["y_m"],
            "trunk_z_m": runner.REFERENCE["trunk_z_m"],
            "heading_rad": runner.REFERENCE["heading_rad"],
            "roll_rad": 0., "pitch_rad": 0.,
            "imu_quat_wxyz": [1., 0., 0., 0.]}


def test_frozen_fresh_balanced_matrix():
    rows = runner.matrix(PROTOCOL)
    assert rows == expected_matrix(PROTOCOL)
    assert [row["seed"] for row in rows] == list(range(888200, 888230))
    assert all(row["seed"] not in set(range(887100, 887750)) |
               set(range(888100, 888130)) |
               set(range(881000, 881020)) |
               set(range(882000, 882020)) for row in rows)
    assert {r["condition"] for r in rows} == {
        "sham", "positive_low", "negative_low", "positive_medium", "negative_medium"}
    assert all(sum(r["condition"] == condition for r in rows) == 6
               for condition in {r["condition"] for r in rows})
    assert max(row["ticks"] for row in rows) == 5
    assert PROTOCOL["pose"]["max_motion_xy_from_initial_m"] == .01
    assert PROTOCOL["unchanged_final_reset_heading_tolerance_rad"] == .08
    assert PROTOCOL["unchanged_r2_qualification_guard_rad"] == .06


def test_raw_pose_fsynced_before_derivation_and_equal_bound_aborts(tmp_path):
    journal = runner.SampleJournal(tmp_path / "samples.jsonl")
    now = time.monotonic_ns()
    base = pose(1., now - 20_000_000)
    journal.append("pose", {"phase": "PRE", "pose": base})
    reader = mock.Mock()
    reader.read.return_value = pose(1.02, now, .010001)
    state = {"t_ns": now, "move": {"requested": [0., 0., .2],
             "applied": [0., 0., .2], "limited_by": []},
             "policy": "walk", "safety": {"fallen": False, "limp": False}}
    stream = mock.Mock(latest=state, received_ns=now)
    health = mock.Mock()
    health.health.return_value = {"healthy": True, "degraded": False}
    cache = {"value": {"healthy": True, "degraded": False}, "received_ns": now}
    original = runner.validate_pose
    def validate_after_raw(*args, **kwargs):
        raw = read_journal(tmp_path / "samples.jsonl")
        assert raw[-1]["kind"] == "pose"
        assert raw[-1]["pose"] == reader.read.return_value
        return original(*args, **kwargs)
    with (mock.patch.object(runner, "validate_pose", side_effect=validate_after_raw),
          mock.patch.object(runner, "bounded_stop", return_value={"result": "PASS"})):
        with pytest.raises(runner.SafetyAbort) as error:
            runner.sampled(reader, stream, journal, health, base, cache,
                           {"vyaw_radps": .2, "ack": {}, "active_duration_s": .02,
                            "command_start_pose": base},
                           phase="COMMAND", moving=True)
    journal.close()
    kinds = [entry["kind"] for entry in read_journal(tmp_path / "samples.jsonl")]
    assert kinds[-3:] == ["pose", "violation", "safety_stop_ack"]
    assert error.value.trigger["threshold"] == .01
    assert error.value.trigger["measured"] >= .01
    equality_row = {"sample_index": 9, "pose": base,
                    "displacement_from_reset_start_m": .01,
                    "displacement_from_command_start_m": 0.}
    with pytest.raises(runner.SafetyAbort):
        runner.validate_pose(equality_row, None, base, moving=True)
    with pytest.raises(runner.SafetyAbort):
        runner.validate_pose(equality_row, {"sample_index": 0, "pose": base},
                             None, moving=False, check_clock=False)


def test_abort_stops_after_first_move_without_feedback(tmp_path):
    journal = runner.SampleJournal(tmp_path / "samples.jsonl")
    journal.append("pose", {"phase": "PRE", "pose": pose(1., time.monotonic_ns())})
    now = time.monotonic_ns()
    trigger = {"sample_index": 2, "pose": pose(1.02, now, .01)}
    violation = runner.SafetyAbort("displacement_from_command_start_m_bound_exceeded",
                                   trigger, journal.last_pose, .01, .01)
    stop = {"result": "PASS", "ack": {"accepted": True},
            "started_ns": now, "completed_ns": now + 1_000_000,
            "latency_s": .001}
    item = expected_matrix(PROTOCOL)[1]
    with (mock.patch.object(runner, "acknowledged_precondition_move",
                            return_value=({"accepted": True}, now, now, now)) as move,
          mock.patch.object(runner, "sampled", side_effect=violation),
          mock.patch.object(runner, "bounded_stop", return_value=stop) as stopped):
        with pytest.raises(runner.SafetyAbort):
            runner.pulse(None, None, journal, None, None, None,
                         journal.last_pose["pose"], item, {})
    journal.close()
    assert move.call_count == 1
    assert stopped.call_count == 1
    assert read_journal(tmp_path / "samples.jsonl")[-1]["kind"] == "stop_ack"


def test_phase_decomposition_includes_post_stop_translation():
    ns = 1_000_000_000
    def row(index, ms, x):
        return {"sample_index": index, "pose": pose(1 + ms / 1000,
                ns + ms * 1_000_000, x)}
    pre = [row(0, -100, 0.), row(1, -20, 0.)]
    command = [row(2, 0, .001)]
    stop = row(3, 10, .002)
    post = [row(4 + i, 20 + 20 * i, .002 + i * .0001) for i in range(50)]
    settle = [row(54, 1100, .007), row(55, 1150, .007)]
    record = {"initial_plateau": pre, "delta_heading_rad": .01,
        "pulses": [{"trajectory": command,
        "stop_ack_pose": stop, "post_stop_trajectory": post,
        "plateau": settle, "stop": {"completed_ns": ns}}]}
    result = phase_metrics(record)
    assert result["POST_STOP_0_250MS"]["net_planar_m"] > 0
    assert result["POST_STOP_250_500MS"]["net_planar_m"] > 0
    assert result["post_stop_additional_excursion_m"] > .0049
    assert result == phase_metrics(record)


def test_incomplete_raw_and_manifest_cannot_pass(tmp_path):
    assert score(PROTOCOL, [], tmp_path)["result"] == "FAIL"
    path = tmp_path / "torn.jsonl"
    path.write_bytes(b'{"sample_index":0}')
    with pytest.raises(ValueError, match="torn"):
        read_journal(path)
    (tmp_path / "manifest.json").write_text(json.dumps({
        "schema_version": "p8-03-r5-manifest-v1", "files": []}))
    (tmp_path / "unlisted.txt").write_text("orphan")
    with pytest.raises(RuntimeError, match="inventory"):
        score_root(tmp_path, Path(__file__).parents[1] /
                   "config/p8_03_r5_yaw_coupling_v1.json")


def test_cleanup_and_trigger_are_required():
    item = expected_matrix(PROTOCOL)[1]
    assert verify_trace(dict(item, result="SAFETY_ABORT"), item, [])[0] is False
    assert verify_trace(dict(item, result="VALID", cleanup_stop={"result": "PASS"},
                             down_after_exit=0, final_probe={"result": "FAIL"}),
                        item, [])[0] is False


def test_offline_scorer_reconstructs_exact_abort(tmp_path):
    item = expected_matrix(PROTOCOL)[1]
    now = time.monotonic_ns()
    base, crossing = pose(1., now), pose(1.02, now + 20_000_000, .011)
    journal = runner.SampleJournal(tmp_path / "samples.jsonl")
    def raw(p, phase, previous):
        return journal.append("pose", {"phase": phase, "pose": p,
            "host_monotonic_ns": p["response_ns"], "robot_t_ns": p["response_ns"],
            "state_received_ns": p["response_ns"],
            "requested": [0., 0., .2], "applied": [0., 0., .2],
            "limited_by": [], "policy": "walk",
            "robotd_state": {"policy": "walk"},
            "robotd_health": {"healthy": True},
            "last_command_ack": {"accepted": True},
            "previous_pose_sample_index": previous})
    initial = raw(base, "PRE", None)
    journal.append("derived", {"pose_sample_index": initial["sample_index"],
        "displacement_from_reset_start_m": 0.,
        "displacement_from_command_start_m": 0., "wrapped_heading_delta_rad": 0.})
    journal.append("command_request", {"tick": 0, "vyaw_radps": .2})
    trigger_row = raw(crossing, "COMMAND", initial["sample_index"])
    measured = math.hypot(crossing["x_m"] - base["x_m"],
                          crossing["y_m"] - base["y_m"])
    journal.append("derived", {"pose_sample_index": trigger_row["sample_index"],
        "displacement_from_reset_start_m": measured,
        "displacement_from_command_start_m": measured,
        "wrapped_heading_delta_rad": 0.})
    trigger = {"reason": "displacement_from_command_start_m_bound_exceeded",
        "trigger_sample_index": trigger_row["sample_index"],
        "previous_sample_index": initial["sample_index"],
        "trigger_pose": crossing, "previous_pose": base,
        "measured": measured, "threshold": .01}
    stop = {"result": "PASS", "ack": {"accepted": True}}
    journal.append("violation", {"trigger": trigger})
    journal.append("safety_stop_ack", stop)
    journal.append("stop_ack", stop)
    probe = {"result": "PASS"}
    journal.append("cleanup", {"stop": stop, "down_exit": 0,
                                "final_probe": probe, "trigger": trigger})
    journal.close()
    record = dict(item, result="SAFETY_ABORT", initial_plateau=[initial],
                  pulses=[{"stop": stop}], trigger=trigger,
                  cleanup_stop=stop, down_after_exit=0, final_probe=probe)
    rows = read_journal(tmp_path / "samples.jsonl")
    assert verify_trace(record, item, rows) == (True, "SAFETY_ABORT")
    extra_pose = dict(trigger_row, sample_index=100,
                      pose=pose(1.01, now + 10_000_000, .0105))
    extra_distance = math.hypot(extra_pose["pose"]["x_m"] - base["x_m"], 0.)
    extra_derived = dict(rows[4], sample_index=101, pose_sample_index=100,
                         displacement_from_reset_start_m=extra_distance,
                         displacement_from_command_start_m=extra_distance)
    with_unscored_crossing = rows[:3] + [extra_pose, extra_derived] + rows[3:]
    assert verify_trace(record, item, with_unscored_crossing)[0] is False
    record["trigger"] = dict(trigger, measured=.009)
    assert verify_trace(record, item, rows)[0] is False
