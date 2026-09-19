import copy
import json
from pathlib import Path

import pytest

from microduck_connectome.fault_evidence import (
    FaultEvidenceError, REQUIRED_FAULTS, build_fault_matrix, make_fault_record,
)


def record(name):
    return make_fault_record(
        fault=name, injected_at_ns=10, detected_at_ns=20,
        safe_command_at_ns=30, motion_stopped_at_ns=40, recovery_at_ns=50,
        state_evidence={
            "requested": [0.0, 0.0, 0.0], "applied": [0.0, 0.0, 0.0],
            "heading_before_rad": 0.1, "heading_after_rad": 0.1001,
            "heading_delta_rad": 0.0001,
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


@pytest.mark.parametrize("mutation", ["replay", "moving", "time", "transport"])
def test_unsafe_or_inconsistent_record_is_rejected(mutation):
    value = record(REQUIRED_FAULTS[0])
    if mutation == "replay":
        value["old_command_replayed"] = True
    elif mutation == "moving":
        value["state_evidence"]["applied"][2] = 0.1
    elif mutation == "time":
        value["motion_stopped_at_ns"] = 15
    else:
        value["stop_transport"] = "zero_twist"
    from microduck_connectome.fault_evidence import validate_fault_record
    with pytest.raises(FaultEvidenceError):
        validate_fault_record(value)

