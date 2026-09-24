import copy
import json
from pathlib import Path

import pytest

from microduck_connectome.fault_evidence import (
    FaultEvidenceError, REQUIRED_FAULTS, build_fault_matrix, make_fault_record,
)
from microduck_connectome.perception_compositor import PerceptionPipeline


def record(name):
    deadman = name in ("connectome_process_crash", "connectome_process_freeze")
    neutral = name in ("camera_dropout", "tof_dropout", "stale_perception", "compositor_invalid")
    requested = [0.0, 0.0, 0.2] if deadman else [0.0, 0.0, 0.0]
    limited_by = ["deadman"] if deadman else []
    return make_fault_record(
        fault=name, injected_at_ns=10, detected_at_ns=20,
        safe_command_at_ns=30, motion_stopped_at_ns=40, recovery_at_ns=50,
        first_safe_transport="robotd_deadman" if deadman else "neutral_move" if neutral else "robot_stop",
        state_evidence={
            "requested": requested, "applied": [0.0, 0.0, 0.0], "limited_by": limited_by,
            "heading_before_rad": 0.1, "heading_after_rad": 0.1001,
            "heading_delta_rad": 0.0001,
            "settled_windows": 5,
            "heading_samples": [0.1, 0.10002, 0.10004, 0.10006, 0.10008, 0.1001],
            "angular_rate_samples_radps": [0.0002] * 5,
            "max_abs_angular_rate_radps": 0.0002,
            "command_samples": [
                {"timestamp_ns": 100 + i, "requested": requested, "applied": [0.0, 0.0, 0.0], "limited_by": limited_by}
                for i in range(5)
            ],
        },
    )


def test_complete_matrix_is_canonical_and_finite(tmp_path: Path):
    matrix = build_fault_matrix(
        execution_target="Thor", source_head="a" * 40,
        identities={"stop_transport": "robot_stop", "ttl_ms": 100},
        records=[record(name) for name in REQUIRED_FAULTS],
        artifact={"path": "fault-events.jsonl", "sha256": "b" * 64},
    )
    encoded = json.dumps(matrix, sort_keys=True, allow_nan=False)
    assert matrix["fault_count"] == len(REQUIRED_FAULTS)
    assert '"result": "PASS"' in encoded


def test_missing_or_reordered_fault_is_rejected():
    records = [record(name) for name in REQUIRED_FAULTS]
    records[0], records[1] = records[1], records[0]
    with pytest.raises(FaultEvidenceError, match="canonical order"):
        build_fault_matrix(
            execution_target="Thor", source_head="a" * 40, identities={},
            records=records, artifact={},
        )


def test_process_loss_requires_observed_robotd_deadman():
    value = record("connectome_process_crash")
    value["state_evidence"]["limited_by"] = []
    with pytest.raises(FaultEvidenceError, match="does not prove rest|deadman"):
        from microduck_connectome.fault_evidence import validate_fault_record
        validate_fault_record(value)


@pytest.mark.parametrize("mutation", ["replay", "moving", "time", "transport", "first_transport", "rate", "short_window"])
def test_unsafe_or_inconsistent_record_is_rejected(mutation):
    value = record(REQUIRED_FAULTS[0])
    if mutation == "replay":
        value["old_command_replayed"] = True
    elif mutation == "moving":
        value["state_evidence"]["applied"][2] = 0.1
    elif mutation == "time":
        value["motion_stopped_at_ns"] = 15
    elif mutation == "transport":
        value["stop_transport"] = "zero_twist"
    elif mutation == "first_transport":
        value["first_safe_transport"] = "robot_stop"
    elif mutation == "rate":
        value["state_evidence"]["angular_rate_samples_radps"][2] = 0.02
    else:
        value["state_evidence"]["command_samples"] = value["state_evidence"]["command_samples"][:2]
    from microduck_connectome.fault_evidence import validate_fault_record
    with pytest.raises(FaultEvidenceError):
        validate_fault_record(value)


def _pipeline_frame(*, camera_valid=True, tof_valid=True, tof_age_ns=0):
    pipeline = PerceptionPipeline()
    now = 200_000_000
    frame = pipeline.process(
        (((255, 0, 0), (255, 0, 0), (0, 0, 0)),),
        camera_timestamp_ns=now, camera_frame_id=1,
        tof_left_mm=500, tof_center_mm=500, tof_right_mm=500,
        tof_timestamp_ns=now - tof_age_ns, tof_frame_id=1, now_ns=now,
        camera_source_valid=camera_valid, tof_source_valid=tof_valid,
    )
    return frame, pipeline.compositor.last_reasons


def test_camera_tof_and_compositor_faults_have_distinct_observed_reasons():
    camera, camera_reasons = _pipeline_frame(camera_valid=False)
    tof, tof_reasons = _pipeline_frame(tof_valid=False)
    compositor, compositor_reasons = _pipeline_frame(tof_age_ns=100_000_001)
    assert not camera["valid"] and "invalid_camera" in camera_reasons
    assert not tof["valid"] and tof_reasons == ("invalid_tof",)
    assert not compositor["valid"] and "stale_tof" in compositor_reasons and "source_skew" in compositor_reasons
    assert camera_reasons != tof_reasons != compositor_reasons


def test_invalid_perception_injection_is_not_a_camera_dropout():
    frame, reasons = _pipeline_frame()
    assert frame["valid"] and reasons == ()
    malformed = dict(frame)
    malformed["target_x"] = 2.0
    # The injected compositor output is invalid while its source remained healthy.
    from microduck_connectome.perception_frame import make_perception_frame
    with pytest.raises(ValueError):
        make_perception_frame(**malformed)
