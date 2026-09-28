"""R4 matrix, durable trigger, safety stop, and raw scoring tests."""
import copy
import json
import math
import os
from pathlib import Path
import tempfile
import time
from unittest import mock

import scripts.p8_03_r4_actuator_pose as runner
from scripts.p8_03_r4_score import _pose_record_valid, classify, expected_matrix, verify_trace

PROTOCOL = json.loads((Path(__file__).parents[1] /
                       "config/p8_03_r4_actuator_pose_v1.json").read_text())


def pose(sim_time: float, response_ns: int, *, x_extra: float = 0.) -> dict:
    x = runner.REFERENCE["x_m"] + x_extra
    return {"request_ns": response_ns - 1_000_000,
            "response_ns": response_ns,
            "raw_body_packet": json.dumps({"trunk": [x, runner.REFERENCE["y_m"],
                                                       runner.REFERENCE["trunk_z_m"]],
                                           "sim_time": sim_time}),
            "sim_time_s": sim_time, "x_m": x,
            "y_m": runner.REFERENCE["y_m"],
            "trunk_z_m": runner.REFERENCE["trunk_z_m"],
            "heading_rad": runner.REFERENCE["heading_rad"],
            "roll_rad": 0., "pitch_rad": 0.,
            "imu_quat_wxyz": [1., 0., 0., 0.]}


def baseline_payload(baseline: dict) -> dict:
    return {"phase": "initial:0", "pose": baseline,
            "robot_t_ns": baseline["response_ns"],
            "state_received_ns": baseline["response_ns"],
            "requested": [0., 0., 0.], "applied": [0., 0., 0.],
            "limited_by": [], "policy": "stand",
            "safety": {"fallen": False, "limp": False},
            "robotd_health": {"healthy": True, "degraded": False},
            "robotd_health_received_ns": baseline["response_ns"],
            "last_command_ack": {"accepted": True},
            "commanded_vyaw_radps": 0., "command_active_duration_s": 0.,
            "displacement_from_reset_start_m": 0.,
            "wrapped_heading_delta_rad": 0.,
            "previous_pose_sample_index": None}


def telemetry(now: int):
    stream = mock.Mock()
    stream.latest = {
        "t_ns": now, "move": {"requested": [0., 0., .2],
                              "applied": [0., 0., .1], "limited_by": []},
        "policy": "stand", "safety": {"fallen": False, "limp": False}}
    stream.received_ns = now
    health = mock.Mock()
    health.health.return_value = {"healthy": True, "degraded": False}
    return stream, health, {"value": {"healthy": True, "degraded": False},
                            "received_ns": now}


def test_frozen_unused_symmetric_matrix():
    rows = runner.matrix(PROTOCOL)
    assert rows == expected_matrix(PROTOCOL)
    assert len(rows) == 30
    assert [row["seed"] for row in rows] == list(range(888100, 888130))
    assert [sum(row["condition"] == condition for row in rows)
            for condition in ("sham", "positive_low", "negative_low",
                              "positive_high", "negative_high")] == [6] * 5
    assert all(row["seed"] not in range(887200, 887750) for row in rows)
    assert all(row["ticks"] in (5, 8) for row in rows)
    assert .2 * .3 < PROTOCOL["dose"]["max_command_integral_rad"]


def test_threshold_pose_fsynced_before_bound_evaluation():
    with tempfile.TemporaryDirectory() as directory:
        journal = runner.SampleJournal(Path(directory) / "samples.jsonl")
        now = time.monotonic_ns()
        base = pose(1., now - 50_000_000)
        journal.append("pose", baseline_payload(base))
        crossing = pose(1.02, now, x_extra=.011)
        reader = mock.Mock()
        reader.read.return_value = crossing
        stream, health, health_cache = telemetry(now)
        events = []
        real_fsync = os.fsync
        real_validate = runner.validate_pose
        def fsync_spy(fd):
            events.append("fsync")
            return real_fsync(fd)
        def validate_spy(*args, **kwargs):
            events.append("evaluate")
            assert "fsync" in events
            return real_validate(*args, **kwargs)
        with (mock.patch.object(runner.os, "fsync", side_effect=fsync_spy),
              mock.patch.object(runner, "validate_pose", side_effect=validate_spy)):
            try:
                runner.sampled(reader, stream, journal, health, base,
                               health_cache, {"vyaw_radps": .2, "ack": {"accepted": True},
                                              "active_duration_s": .08},
                               phase="post_stop:2", moving=True)
            except runner.SafetyAbort as error:
                trigger = error.trigger
            else:
                raise AssertionError("crossing pose did not abort")
        journal.close()
        raw = [json.loads(line) for line in (Path(directory) / "samples.jsonl").read_text().splitlines()]
        assert events.index("fsync") < events.index("evaluate")
        assert raw[-1]["pose"] == crossing
        assert trigger["trigger_sample_index"] == raw[-1]["sample_index"]
        assert trigger["previous_sample_index"] == raw[0]["sample_index"]
        assert trigger["threshold"] == .01
        assert math.isclose(trigger["measured"], .011)


def test_pulse_abort_stops_without_second_command_and_scorer_requires_trigger():
    with tempfile.TemporaryDirectory() as directory:
        journal = runner.SampleJournal(Path(directory) / "samples.jsonl")
        now = time.monotonic_ns()
        base = pose(1., now - 50_000_000)
        journal.append("pose", baseline_payload(base))
        reader = mock.Mock()
        reader.read.return_value = pose(1.02, now + 20_000_000, x_extra=.011)
        stream, health, health_cache = telemetry(now + 20_000_000)
        item = expected_matrix(PROTOCOL)[1]  # positive_low
        trace = {}
        stop = {"result": "PASS", "ack": {"accepted": True},
                "started_ns": now + 21_000_000, "completed_ns": now + 22_000_000,
                "latency_s": .001}
        order = []
        def stop_spy(_sock):
            rows = runner.json.loads((Path(directory) / "samples.jsonl").read_text().splitlines()[-1])
            assert rows["kind"] == "pose" and rows["pose"]["x_m"] == reader.read.return_value["x_m"]
            order.append("stop")
            return stop
        ack = {"accepted": True}
        with (mock.patch.object(runner, "acknowledged_precondition_move",
                                return_value=(ack, now, now + 1000, now + 2000)) as move,
              mock.patch.object(runner, "bounded_stop", side_effect=stop_spy)):
            try:
                runner.pulse(reader, stream, journal, health, health_cache,
                             object(), base, item, trace)
            except runner.SafetyAbort:
                pass
            else:
                raise AssertionError("pulse did not abort")
            assert move.call_count == 1
        assert order == ["stop"]
        assert trace["stop"]["result"] == "PASS"
        assert trace["trigger"]["threshold"] == .01
        final_probe = {"result": "PASS"}
        record = dict(item, result="SAFETY_ABORT", pulses=[trace],
                      trigger=trace["trigger"], cleanup_stop=stop,
                      down_after_exit=0, final_probe=final_probe)
        journal.append("cleanup", {"stop": stop, "down_exit": 0,
                                    "final_probe": final_probe, "trigger": trace["trigger"]})
        journal.close()
        raw = [json.loads(line) for line in (Path(directory) / "samples.jsonl").read_text().splitlines()]
        assert verify_trace(record, item, raw) == (True, "SAFETY_ABORT")
        missing = [line for line in raw if line["sample_index"] != trace["trigger"]["trigger_sample_index"]]
        assert verify_trace(record, item, missing)[0] is False
        record_without_probe = copy.deepcopy(record)
        record_without_probe["final_probe"] = {"result": "FAIL"}
        assert verify_trace(record_without_probe, item, raw)[0] is False


def test_fsync_failure_prevents_pose_evaluation():
    with tempfile.TemporaryDirectory() as directory:
        journal = runner.SampleJournal(Path(directory) / "samples.jsonl")
        now = time.monotonic_ns()
        base = pose(1., now - 50_000_000)
        journal.append("pose", baseline_payload(base))
        reader = mock.Mock()
        reader.read.return_value = pose(1.02, now, x_extra=.011)
        stream, health, health_cache = telemetry(now)
        with (mock.patch.object(runner.os, "fsync", side_effect=OSError("disk failed")),
              mock.patch.object(runner, "validate_pose") as evaluate):
            try:
                runner.sampled(reader, stream, journal, health, base,
                               health_cache, {}, phase="pulse:0", moving=True)
            except OSError:
                pass
            else:
                raise AssertionError("fsync failure was ignored")
            evaluate.assert_not_called()
        journal.close()


def test_new_directory_parent_is_fsynced_before_any_child_write():
    if os.name == "nt":
        return  # Directory-fsync semantics are exercised on Thor/Linux.
    with tempfile.TemporaryDirectory() as directory:
        parent = Path(directory)
        child = parent / "A00"
        events = []
        real_fsync = os.fsync
        def fsync_spy(fd):
            events.append(os.readlink(f"/proc/self/fd/{fd}") if os.name != "nt" else "fsync")
            return real_fsync(fd)
        with mock.patch.object(runner.os, "fsync", side_effect=fsync_spy):
            runner.durable_mkdir(child)
            journal = runner.SampleJournal(child / "samples.jsonl")
            journal.close()
        assert child.is_dir()
        assert len(events) >= 2
        if os.name != "nt":
            assert events[0] == str(parent)
            assert events[1] == str(child)


def test_frozen_robotd_clock_aborts_after_fsynced_pose():
    with tempfile.TemporaryDirectory() as directory:
        journal = runner.SampleJournal(Path(directory) / "samples.jsonl")
        now = time.monotonic_ns()
        base = pose(1., now - 150_000_000)
        journal.append("pose", baseline_payload(base))
        journal.last_robot_t_ns = 123
        journal.last_robot_advance_ns = now - 150_000_000
        reader = mock.Mock()
        reader.read.return_value = pose(1.15, now)
        stream, health, health_cache = telemetry(now)
        stream.latest["t_ns"] = 123
        try:
            runner.sampled(reader, stream, journal, health, base, health_cache,
                           {}, phase="pulse:0", moving=True)
        except runner.SafetyAbort as error:
            assert error.trigger["reason"] == "robotd_clock_frozen"
            assert error.trigger["trigger_sample_index"] == 1
        else:
            raise AssertionError("frozen robotd clock was accepted")
        journal.close()
        raw = [json.loads(line) for line in
               (Path(directory) / "samples.jsonl").read_text().splitlines()]
        assert raw[-1]["pose"] == reader.read.return_value


def test_response_classes_keep_safety_separate():
    assert classify("positive_low", .001, .005, "VALID") == "INCONCLUSIVE"
    assert classify("positive_low", -.006, .005, "VALID") == "WRONG_SIGN"
    assert classify("negative_high", -.006, .005, "VALID") == "EXPECTED"
    assert classify("negative_high", None, .005, "SAFETY_ABORT") == "SAFETY_ABORT"
    assert classify("sham", 0., .005, "VALID") == "SHAM"


def test_official_unlimited_robotd_state_is_valid_raw_telemetry():
    now = time.monotonic_ns()
    row = baseline_payload(pose(1., now))
    row["limited_by"] = None
    row["sample_index"] = 0
    assert _pose_record_valid(row)
