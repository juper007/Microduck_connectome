"""R6 contract tests; no simulator or robotd connection is made."""
import ast
import json
from pathlib import Path
import statistics

from scripts import p8_03_r6_score as score
from scripts import p8_03_r6_sit_reset_pose as runner


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = json.loads((ROOT / "config/p8_03_r6_sit_reset_pose_v1.json").read_text())


def test_frozen_labels_and_final_envelope():
    matrix = score.expected_matrix(PROTOCOL)
    assert len(matrix) == 48
    assert [r["development_reset_id"] for r in matrix] == list(range(888300, 888348))
    assert PROTOCOL["reset_id_semantics"] == "unique_label_only"
    assert PROTOCOL["simulator_rng_seeded"] is False
    assert PROTOCOL["unchanged_final_envelope"] == {
        "x_m": .03, "y_m": .03, "trunk_z_m": .025, "heading_rad": .08}
    assert not set(range(888200, 888230)).intersection(
        r["development_reset_id"] for r in matrix)


def test_runner_has_no_motion_command_path():
    tree = ast.parse((ROOT / "scripts/p8_03_r6_sit_reset_pose.py").read_text())
    method_calls = {node.func.attr for node in ast.walk(tree)
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    string_constants = {node.value for node in ast.walk(tree)
                        if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    assert "move" not in method_calls
    assert "notify" not in method_calls
    assert "robot.move" not in string_constants
    assert "enable" not in method_calls
    assert "stop" in method_calls


def test_journal_fsyncs_every_checkpoint(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(runner.os, "fsync", lambda fd: calls.append(fd))
    journal = runner.Journal(tmp_path / "samples.jsonl")
    for stage in score.STAGES:
        journal.add("pose", checkpoint=stage)
    journal.close()
    assert len(calls) == len(score.STAGES)
    rows = score.read_journal(tmp_path / "samples.jsonl")
    assert [row["checkpoint"] for row in rows] == list(score.STAGES)


def test_observed_outside_pose_retained_and_scored(tmp_path):
    matrix = score.expected_matrix(PROTOCOL)
    record = {**matrix[0], "result": "OBSERVED", "move_count": 0,
              "down_before_exit": 0, "up_exit": 0, "policy_load_exit": 0,
              "policy_readback_exit": 0, "initial_stop": {"result": "PASS"},
              "cleanup_stop": {"result": "PASS"}, "down_after_exit": 0,
              "final_probe": {"result": "PASS"}}
    pose = {"request_ns": 1, "response_ns": 2, "sim_time_s": 1.,
            "x_m": PROTOCOL["final_reference"]["x_m"] + .031,
            "y_m": PROTOCOL["final_reference"]["y_m"],
            "trunk_z_m": PROTOCOL["final_reference"]["trunk_z_m"],
            "heading_rad": PROTOCOL["final_reference"]["heading_rad"],
            "roll_rad": 0., "pitch_rad": 0., "imu_quat_wxyz": [1., 0., 0., 0.],
            "raw_body_packet": "raw"}
    folder = tmp_path / "S00"
    folder.mkdir()
    rows = []
    for i, stage in enumerate(("B_BODY_REACHABLE", "C_ROBOTD_REACHABLE",
                               "A_UP_COMPLETE", "D_POLICY_LOADED", "E_STOP_ACK",
                               "F_SHORT_SETTLE") + ("G_FINAL_PLATEAU",)*21):
        sample = pose | {"request_ns": i*100_000_000+1,
                         "response_ns": i*100_000_000+2,
                         "sim_time_s": 1+i*.1}
        rows.append({"sample_index": len(rows), "kind": "pose", "checkpoint": stage,
                     "checkpoint_index": sum(r.get("checkpoint") == stage for r in rows),
                     "host_monotonic_ns": sample["response_ns"], "pose": sample,
                     "robotd_state": None if stage == "B_BODY_REACHABLE" else {},
                     "robotd_t_ns": None if stage == "B_BODY_REACHABLE" else i,
                     "state_received_ns": None if stage == "B_BODY_REACHABLE" else sample["response_ns"],
                     "health": None if stage == "B_BODY_REACHABLE" else {}})
    # Insert actual lifecycle acknowledgments and reindex the durable journal.
    rows.extend([{"kind": "up_complete"}, {"kind": "stop_ack", "result": "PASS"},
                 {"kind": "cleanup"}])
    for i, row in enumerate(rows):
        row["sample_index"] = i
    (folder / "samples.jsonl").write_text("".join(json.dumps(r)+"\n" for r in rows))
    record["checkpoint_metrics"] = score.checkpoint_metrics(score.stage_views(rows, PROTOCOL), PROTOCOL)
    report = score.score(PROTOCOL, [record], tmp_path)
    assert report["valid_resets"] == 1
    assert report["outside_envelope_count"] == 1
    assert report["in_envelope_count"] == 0
    assert report["per_reset"]["S00"]["final_classification"] == "OUTSIDE_X"
    assert report["result"] == "FAIL"  # incomplete 48-reset matrix, not an envelope abort


def test_observed_pose_only_and_raw_integrity(tmp_path):
    pose = {"x_m": PROTOCOL["final_reference"]["x_m"] + .031,
            "y_m": PROTOCOL["final_reference"]["y_m"],
            "trunk_z_m": PROTOCOL["final_reference"]["trunk_z_m"],
            "heading_rad": PROTOCOL["final_reference"]["heading_rad"]}
    assert score.flags(pose, PROTOCOL) == ["OUTSIDE_X"]
    assert score.flags(pose | {"x_m": PROTOCOL["final_reference"]["x_m"]}, PROTOCOL) == []
    path = tmp_path / "raw.jsonl"
    path.write_text('{"sample_index":0,"kind":"pose"}\n')
    assert len(score.read_journal(path)) == 1
    path.write_text('{"sample_index":0,"kind":"pose"}')
    try:
        score.read_journal(path)
    except ValueError as error:
        assert "torn" in str(error)
    else:
        assert False, "torn journal accepted"


def test_outside_final_envelope_is_not_a_runner_abort():
    pose = {"request_ns": 1, "response_ns": 2, "sim_time_s": 1.,
            "x_m": 1.0, "y_m": 1.0, "trunk_z_m": 1.0,
            "heading_rad": 2.0, "roll_rad": 0., "pitch_rad": 0.,
            "imu_quat_wxyz": [1., 0., 0., 0.]}
    row = {"checkpoint": "B_BODY_REACHABLE", "pose": pose}
    assert runner.check_sample(row, None, PROTOCOL) is None
    assert score.flags(pose, PROTOCOL) == [
        "OUTSIDE_X", "OUTSIDE_Y", "OUTSIDE_Z", "OUTSIDE_HEADING"]
    row["pose"] = pose | {"roll_rad": .6}
    assert runner.check_sample(row, None, PROTOCOL) == (
        "SAFETY_FAIL", "body_attitude_exceeded")
