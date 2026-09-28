"""Prospective reset gate rejects stale, moving, and displaced initial states."""
from microduck_connectome.p8_03_r2_reset import (
    REFERENCE, alignment_eligible, qualification,
)


def rows(offset=0.0):
    return [{"request_ns": 2_000_000_000 + i * 50_000_000,
             "response_ns": 2_001_000_000 + i * 50_000_000,
             "sim_time_s": 8.0 + i * .05,
             "roll_rad": .1, "pitch_rad": .1,
             "pose": dict(REFERENCE, heading_rad=REFERENCE["heading_rad"] + offset)}
            for i in range(21)]


def gate(data):
    return qualification(data, stop_ack_ns=1_900_000_000,
                         health={"healthy": True, "degraded": False},
                         applied_velocity=[0, 0, 0])


def test_fixed_reference_and_guard_boundaries():
    assert gate(rows(.06))["result"] == "PASS"
    assert gate(rows(.060001))["reasons"] == ["heading_guard"]
    assert gate(rows(.080001))["reasons"] == ["heading_guard", "pose_tolerance"]
    assert gate(rows(-.06))["result"] == "PASS"


def test_stale_clock_and_delayed_reply_rejected():
    data = rows()
    data[4]["sim_time_s"] = data[3]["sim_time_s"]
    assert "stale_pose" in gate(data)["reasons"]
    data = rows()
    data[5]["response_ns"] += 110_000_000
    assert "stale_pose" in gate(data)["reasons"]


def test_stable_displaced_and_moving_pose_rejected():
    data = rows()
    for row in data:
        row["pose"]["x_m"] += .030001
    assert "pose_tolerance" in gate(data)["reasons"]
    data = rows()
    data[-1]["pose"]["heading_rad"] += .006
    assert "heading_drift" in gate(data)["reasons"]


def test_stop_health_and_applied_motion_required():
    data = rows()
    assert "before_stop_ack" in qualification(
        data, stop_ack_ns=data[0]["request_ns"], health={"healthy": True},
        applied_velocity=[0, 0, 0])["reasons"]
    assert "health" in qualification(
        data, stop_ack_ns=0, health={"healthy": False},
        applied_velocity=[0, 0, 0])["reasons"]
    assert "applied_motion" in qualification(
        data, stop_ack_ns=0, health={"healthy": True},
        applied_velocity=[0, .01, 0])["reasons"]


def test_alignment_precheck_depends_only_on_fresh_pose():
    data = rows(.061)
    assert alignment_eligible(data[1], data[0])
    bad = rows(.061)
    bad[1]["sim_time_s"] = bad[0]["sim_time_s"]
    assert not alignment_eligible(bad[1], bad[0])
    bad = rows(.351)
    assert not alignment_eligible(bad[1], bad[0])
    bad = rows(.061)
    bad[1]["roll_rad"] = .51
    assert not alignment_eligible(bad[1], bad[0])
