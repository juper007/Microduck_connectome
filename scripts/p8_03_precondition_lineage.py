"""Diagnostic robotd lineage for prospective P8-03 prearm acquisition.

These records do not revise or rescore the immutable TPR2A-001 evidence.
Receiving a notification after an ACK is not proof that its source state was
sampled after the command. Classification is conservative and diagnostic only;
the moving-body pose and duration gates remain independent.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import threading


class DurableStateLineage:
    """Persist every parsed robot.state notification before it is observable."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._file = self.path.open("x", encoding="utf-8", newline="\n")
        self._lock = threading.Lock()

    def append(self, observation: dict) -> None:
        row = {"kind": "state_observation", **copy.deepcopy(observation)}
        line = json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False)
        with self._lock:
            self._file.write(line + "\n")
            self._file.flush()
            os.fsync(self._file.fileno())

    def close(self) -> None:
        with self._lock:
            self._file.close()

    def __enter__(self) -> "DurableStateLineage":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def observation_journal_row(observation: dict) -> dict:
    """Retain an unproven state as transient with its safety fields visible."""
    state = observation["state"]
    move = state["move"]
    limited_by = list(move.get("limited_by", []))
    return {**copy.deepcopy(observation),
            "kind": "state_observation",
            "command_request_id": None,
            "requested_velocity": list(move["requested"]),
            "applied_velocity": list(move["applied"]),
            "limited_by": limited_by,
            "policy": state.get("policy"),
            "deadman": "deadman" in limited_by,
            "freshness": None,
            "causal_post_command": False,
            "qualification_state": "TRANSIENT",
            "reason": "command_causality_not_yet_proven"}


def acquisition_contaminated(observations: list[dict]) -> bool:
    """A skipped notification must not be erased by a later clean readback."""
    for observation in observations:
        state = observation["state"]
        limited_by = state["move"].get("limited_by", [])
        if (any(reason in ("deadman", "fault", "safety") for reason in limited_by)
                or state.get("safety", {}).get("fallen") is True
                or state.get("safety", {}).get("limp") is True):
            return True
    return False


def classify_observation(
    observation: dict,
    *,
    pre_move_observation: dict,
    command_write_ns: int | None,
    command_ack_ns: int | None,
    command_accepted: bool,
    source_clock_comparable: bool = False,
    maximum_state_age_ns: int,
    minimum_applied_vx_mps: float,
    allowed_policies: frozenset[str],
) -> dict:
    """Classify one retained state without inferring effect from receive order.

    ``source_clock_comparable`` must be established by the pinned robotd clock
    contract. Until then, even advancing source timestamps cannot prove ordering
    against the host command write timestamp.
    """
    index = observation.get("state_index")
    pre_index = pre_move_observation.get("state_index")
    if type(index) is not int or type(pre_index) is not int:
        raise ValueError("state lineage indices required")
    if index < pre_index:
        raise ValueError("state index regressed")
    source_ns = observation.get("source_timestamp_ns")
    pre_source_ns = pre_move_observation.get("source_timestamp_ns")
    received_ns = observation.get("received_ns")
    raw = observation.get("state")
    if not isinstance(raw, dict):
        raise ValueError("parsed raw robot.state required")
    move = raw.get("move")
    if not isinstance(move, dict):
        raise ValueError("robot.state move object required")
    requested = move.get("requested")
    applied = move.get("applied")
    limited_by = move.get("limited_by")
    if (not isinstance(requested, list) or len(requested) != 3
            or not isinstance(applied, list) or len(applied) != 3
            or not isinstance(limited_by, list)):
        raise ValueError("robot.state motion fields required")
    deadman = "deadman" in limited_by
    freshness = (type(source_ns) is int and type(received_ns) is int
                 and 0 <= received_ns - source_ns <= maximum_state_age_ns)
    causal_post_command = (
        source_clock_comparable and command_accepted
        and type(pre_source_ns) is int and type(source_ns) is int
        and type(command_write_ns) is int and type(command_ack_ns) is int
        and type(received_ns) is int and index > pre_index
        and source_ns > pre_source_ns and source_ns > command_write_ns
        and received_ns >= command_ack_ns and freshness
    )
    if not causal_post_command:
        qualification_state = "TRANSIENT"
        reason = "causal_post_command_not_proven"
    elif (deadman or any(value in ("fault", "safety") for value in limited_by)
          or raw.get("safety", {}).get("fallen") is True
          or raw.get("safety", {}).get("limp") is True):
        qualification_state = "INVALID"
        reason = "fresh_safety_or_deadman_state"
    elif (raw.get("policy") not in allowed_policies
          or requested[0] <= 0 or applied[0] < minimum_applied_vx_mps):
        qualification_state = "INVALID"
        reason = "fresh_state_not_positive_moving"
    else:
        qualification_state = "QUALIFYING"
        reason = "fresh_positive_state_candidate"
    return {
        "state_index": index,
        "previous_state_index": observation.get("previous_state_index"),
        "source_timestamp_ns": source_ns,
        "previous_source_timestamp_ns": observation.get("previous_source_timestamp_ns"),
        "received_ns": received_ns,
        "pre_move_state_index": pre_index,
        "pre_move_source_timestamp_ns": pre_source_ns,
        "command_write_ns": command_write_ns,
        "command_ack_ns": command_ack_ns,
        "command_accepted": command_accepted,
        "source_clock_comparable": source_clock_comparable,
        "requested_velocity": requested,
        "applied_velocity": applied,
        "limited_by": limited_by,
        "policy": raw.get("policy"),
        "deadman": deadman,
        "freshness": freshness,
        "causal_post_command": causal_post_command,
        "qualification_state": qualification_state,
        "reason": reason,
    }
