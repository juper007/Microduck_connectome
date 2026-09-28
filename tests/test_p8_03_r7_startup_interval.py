"""Focused passive R7 raw-timeline contract tests, without simulator access."""
import ast
import json
import math
from pathlib import Path

from scripts import p8_03_r7_score as score
from scripts import p8_03_r7_startup_interval as runner

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = json.loads((ROOT / "config/p8_03_r7_startup_interval_v3.json").read_text())
BASE = 100_000_000_000
TICK = 20_000_000


def synthetic_trial():
    rows = []
    state_ref = health_ref = None

    def add(kind, t, **fields):
        row = {"kind": kind, "sample_index": len(rows),
               "host_monotonic_ns": t, "host_utc_ns": t + 1_000_000_000,
               **fields}
        rows.append(row)
        return row

    add("reset_start", BASE)
    add("official_down", BASE+1_000_000, exit=0)
    add("official_up_started", BASE+2_000_000, pid=123)
    add("body_reachable", BASE+4_000_000, body_port=7900,
        reached_ns=BASE+3_900_000)
    for i in range(121):
        t = BASE + i*TICK
        if i == 1:
            add("robotd_reachable", t, socket_path="/tmp/duck-a.sock",
                connected_ns=t-100_000)
        if i == 5:
            add("process_log", t, line="standing up", stream="official_up_combined",
                received_ns=t-100_000)
        if i:
            state = {"t_ns": i*TICK, "policy": "held" if i < 5 else "stand",
                     "move": {"requested": [0., 0., 0.], "applied": [0., 0., 0.],
                              "limited_by": []},
                     "safety": {"fallen": False, "limp": False},
                     "joints": [0.01*i]*15, "targets": [0.01*i]*15}
            raw = json.dumps({"jsonrpc": "2.0", "method": "robot.state",
                              "params": state}, sort_keys=True)
            raw_ref = add("robotd_raw_notification", t+900_000,
                          raw_line=raw, received_ns=t+900_000)
            state_ref = add("robotd_state", t+1_000_000, state_index=i-1,
                            raw_notification_index=raw_ref["sample_index"],
                            raw_state_line=raw, state=state,
                            received_ns=t+900_000, robotd_t_ns=i*TICK)
            if i == 1 or i % 10 == 0:
                health = ({"healthy": False,
                           "reason": "control loop has not completed a cycle yet",
                           "control_loop": {"ticks": 0}, "imu": {"ready": False}}
                          if i == 1 else
                          {"healthy": True, "degraded": False,
                           "control_loop": {"ticks": i},
                           "imu": {"ready": i >= 30}})
                health_ref = add("robotd_health", t+2_000_000,
                                 health=health,
                                 received_ns=t+2_000_000)
        fraction = min(1., max(0., (i-6)/14))
        x = .03458*fraction
        z = .07 + .04588*fraction
        heading = .11693*fraction
        quat = [math.cos(heading/2), 0., 0., math.sin(heading/2)]
        packet = {"trunk": [x, .00109*fraction, z],
                  "imu": {"quat": quat}, "sim_time": .02+i*.02,
                  "positions": [0.01*i]*15,
                  "velocities": [0. if i > 20 else .01]*15,
                  "currents_ma": [0.]*15}
        pose = {"request_ns": t+3_000_000, "response_ns": t+4_000_000,
                "raw_body_packet": json.dumps(packet, sort_keys=True),
                **score.body_pose_from_packet(json.dumps(packet))}
        state = state_ref["state"] if state_ref else None
        add("body_sample", t+5_000_000, body_index=i, pose=pose,
            socket_probe_start_ns=t+2_500_000,
            socket_probe_end_ns=t+2_700_000,
            robotd_socket_available=i > 0,
            snapshot_state_index=state_ref["sample_index"] if state_ref else None,
            snapshot_state_age_s=(pose["response_ns"]-state_ref["received_ns"])/1e9
            if state_ref else None,
            snapshot_health_index=health_ref["sample_index"] if health_ref else None,
            policy=state.get("policy") if state else None,
            requested=state["move"]["requested"] if state else None,
            applied=state["move"]["applied"] if state else None,
            limited_by=state["move"]["limited_by"] if state else None,
            safety=state["safety"] if state else None,
            health=health_ref["health"] if health_ref else None)
        if i == 50:
            add("up_exit", t+10_000_000, exit=0, pid=123,
                last_alive_poll_ns=t-10_000_000,
                observed_exit_ns=t+9_900_000)
    add("capture_end", BASE+121*TICK, reason="STAND_SETTLED")
    timeline = score.derive_timeline(rows, PROTOCOL)
    for i, name in enumerate(score.EVENTS):
        add("timeline_event", BASE+121*TICK+1_000_000+i,
            name=name, event=timeline[name])
    add("daemon_log_snapshot", BASE+121*TICK+2_000_000,
        source="body.log", available=False,
        captured_ns=BASE+121*TICK+1_900_000)
    add("daemon_log_snapshot", BASE+121*TICK+3_000_000,
        source="duck-a.log", available=False,
        captured_ns=BASE+121*TICK+2_900_000)
    add("cleanup", BASE+122*TICK, stop={"result": "PASS"},
        down_exit=0, final_probe={"result": "PASS"})
    plan = score.matrix(PROTOCOL)[0]
    trace = {**plan, "result": "OBSERVED", "move_count": 0,
             "down_before_exit": 0, "up_exit": 0,
             "capture_end_reason": "STAND_SETTLED",
             "cleanup_stop": {"result": "PASS"}, "down_after_exit": 0,
             "final_probe": {"result": "PASS"},
             "metrics": score.trial_metrics(rows, PROTOCOL)}
    return trace, rows


def test_frozen_ids_bounds_and_unique_label_semantics():
    planned = score.matrix(PROTOCOL)
    assert len(planned) == 96
    assert [p["development_reset_id"] for p in planned] == list(range(888600, 888696))
    assert PROTOCOL["reset_id_semantics"] == "unique_label_only"
    assert PROTOCOL["simulator_rng_seeded"] is False
    assert PROTOCOL["unchanged_final_envelope_read_only"] == {
        "x_m": .03, "y_m": .03, "trunk_z_m": .025, "heading_rad": .08}
    assert not set(range(888200, 888348)).intersection(
        p["development_reset_id"] for p in planned)
    def seeds(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "seed" and type(item) is int:
                    yield item
                yield from seeds(item)
        elif isinstance(value, list):
            for item in value:
                yield from seeds(item)
    frozen = set()
    for path in (ROOT / "config").glob("p8_*.json"):
        if path.name != "p8_03_r7_startup_interval_v3.json":
            frozen.update(seeds(json.loads(path.read_text())))
    assert set(range(888600, 888696)).isdisjoint(frozen)


def test_no_motion_or_correction_call_path():
    tree = ast.parse((ROOT / "scripts/p8_03_r7_startup_interval.py").read_text())
    methods = {node.func.attr for node in ast.walk(tree)
               if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert "move" not in methods
    assert "notify" not in methods
    assert "enable" not in methods
    assert "load" not in methods
    assert "stop" in methods


def test_every_raw_row_is_fsynced_before_classification(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(runner.os, "fsync", lambda fd: calls.append(fd))
    journal = runner.Journal(tmp_path / "raw.jsonl")
    for i in range(12):
        journal.add("body_sample", body_index=i)
    journal.add("timeline_event", name="FIRST_POSE_DEVIATION")
    journal.close()
    assert len(calls) == 13
    rows = score.read_journal(tmp_path / "raw.jsonl")
    assert rows[-1]["kind"] == "timeline_event"
    assert all(r["sample_index"] < rows[-1]["sample_index"] for r in rows[:-1])


def test_raw_first_events_and_complete_timeline():
    trace, rows = synthetic_trial()
    good, reason = score.verify_trial(trace, score.matrix(PROTOCOL)[0], rows, PROTOCOL)
    assert good, reason
    timeline = score.derive_timeline(rows, PROTOCOL)
    assert timeline["FIRST_POSE_DEVIATION"]["status"] == "OBSERVED"
    assert timeline["FIRST_NONZERO_APPLIED"]["status"] == "NOT_OBSERVED"
    assert timeline["POLICY_STAND"]["host_monotonic_ns"] < timeline[
        "FIRST_POSE_DEVIATION"]["interval_start_ns"]
    assert timeline == trace["metrics"]["timeline"]


def test_nonzero_applied_is_recomputed_from_raw():
    _, rows = synthetic_trial()
    state_rows = [r for r in rows if r["kind"] == "robotd_state"]
    for row in state_rows[2:4]:
        row["state"]["move"]["applied"] = [.001, 0., 0.]
    timeline = score.derive_timeline(rows, PROTOCOL)
    assert timeline["FIRST_NONZERO_APPLIED"]["status"] == "OBSERVED"
    assert timeline["FIRST_NONZERO_APPLIED"]["source_sample_index"] == state_rows[2]["sample_index"]
    relations = score.trial_metrics(rows, PROTOCOL)["event_order"]
    assert relations["FIRST_NONZERO_APPLIED_vs_POLICY_STAND"] == "BEFORE"
    assert relations["FIRST_NONZERO_APPLIED_vs_FIRST_POSE_DEVIATION"] == "BEFORE"


def test_startup_unready_is_narrow_and_one_way():
    trace, rows = synthetic_trial()
    good, reason = score.verify_trial(trace, score.matrix(PROTOCOL)[0], rows, PROTOCOL)
    assert good, reason
    timeline = score.derive_timeline(rows, PROTOCOL)
    assert timeline["STARTUP_UNREADY"]["status"] == "OBSERVED"
    assert timeline["FIRST_HEALTHY"]["status"] == "OBSERVED"
    assert timeline["FIRST_CONTROL_TICK"]["status"] == "OBSERVED"
    assert timeline["IMU_READY"]["status"] == "OBSERVED"
    health_rows = [r for r in rows if r["kind"] == "robotd_health"]
    capture_end = next(r for r in rows if r["kind"] == "capture_end")
    assert score.health_event_before_capture_end(
        rows, capture_end, lambda h: score.health_phase(h) == "HEALTHY")
    early_end = {**capture_end,
                 "host_monotonic_ns": health_rows[1]["received_ns"]-1}
    assert not score.health_event_before_capture_end(
        rows, early_end, lambda h: score.health_phase(h) == "HEALTHY")
    valid = health_rows[0]["health"]
    assert score.health_phase(valid) == "STARTUP_UNREADY"
    assert runner.health_transition(valid, BASE, BASE+1_000_000_000,
                                    False, PROTOCOL) == (False, None)
    assert runner.health_transition(valid, BASE, BASE+6_000_000_000,
                                    False, PROTOCOL) == (
        False, ("INFRA_FAIL", "startup_unready_timeout"))
    healthy = health_rows[1]["health"]
    assert healthy["imu"]["ready"] is False
    assert score.health_phase(healthy) == "HEALTHY"
    assert runner.health_transition(healthy, BASE, BASE+2_000_000_000,
                                    False, PROTOCOL) == (True, None)
    before_tick = {**healthy, "control_loop": {"ticks": 0}}
    assert runner.health_transition(before_tick, BASE, BASE+2_000_000_000,
                                    False, PROTOCOL) == (True, None)
    assert runner.health_transition(valid, BASE, BASE+3_000_000_000,
                                    True, PROTOCOL) == (
        True, ("SAFETY_FAIL", "robotd_unhealthy_after_cycle"))
    for change in ({"healthy": True}, {"reason": "imu stale"},
                   {"control_loop": {"ticks": 1}},
                   {"imu": {"ready": True}}, {"degraded": False}):
        altered = {**valid, **change}
        assert score.health_phase(altered) != "STARTUP_UNREADY"
        assert runner.health_transition(altered, BASE, BASE+1_000_000_000,
                                        False, PROTOCOL)[1] is not None
    broken = json.loads(json.dumps(rows))
    first_healthy = next(r for r in broken if r["kind"] == "robotd_health" and
                         r["health"]["healthy"])
    first_healthy["health"] = valid
    assert score.verify_trial(trace, score.matrix(PROTOCOL)[0], broken, PROTOCOL)[0] is False
    broken = json.loads(json.dumps(rows))
    later = [r for r in broken if r["kind"] == "robotd_health"][-1]
    later["health"] = valid
    assert score.verify_trial(trace, score.matrix(PROTOCOL)[0], broken, PROTOCOL)[0] is False
    broken = json.loads(json.dumps(rows))
    unready = next(r for r in broken if r["kind"] == "robotd_health")
    unready["received_ns"] += 6_000_000_000
    assert score.verify_trial(trace, score.matrix(PROTOCOL)[0], broken, PROTOCOL)[0] is False
    no_imu_ready = json.loads(json.dumps(rows))
    for row in no_imu_ready:
        if row["kind"] == "robotd_health":
            row["health"]["imu"]["ready"] = False
    assert score.derive_timeline(no_imu_ready, PROTOCOL)["IMU_READY"]["status"] == "NOT_OBSERVED"
    assert score.derive_timeline(no_imu_ready, PROTOCOL)["FIRST_HEALTHY"]["status"] == "OBSERVED"


def test_source_receipt_times_control_order_not_journal_delay():
    _, rows = synthetic_trial()
    original = score.derive_timeline(rows, PROTOCOL)
    delayed = json.loads(json.dumps(rows))
    first = original["FIRST_POSE_DEVIATION"]["source_sample_index"]
    delayed[first]["host_monotonic_ns"] += 500_000_000
    up_exit = original["UP_EXIT"]["source_sample_index"]
    delayed[up_exit]["host_monotonic_ns"] += 500_000_000
    assert score.derive_timeline(delayed, PROTOCOL) == original
    assert score.event_relation(original["POLICY_STAND"],
                                original["FIRST_POSE_DEVIATION"]) == "BEFORE"


def test_malformed_robotd_wire_is_durable_before_failure(tmp_path):
    journal = runner.Journal(tmp_path / "wire.jsonl")
    faults = runner.FaultBox()
    message, raw_row, _ = runner.persist_notification(b'{broken-json\n', journal, faults)
    journal.close()
    rows = score.read_journal(tmp_path / "wire.jsonl")
    assert message is None
    assert rows[0]["kind"] == "robotd_raw_notification"
    assert rows[0]["raw_line"] == "{broken-json"
    assert rows[1]["kind"] == "robotd_malformed_notification"
    assert rows[1]["raw_source_sample_index"] == raw_row["sample_index"]
    assert faults.value["category"] == "DATA_INTEGRITY_FAIL"


def test_body_gap_and_missing_timeline_cannot_pass():
    trace, rows = synthetic_trial()
    broken = json.loads(json.dumps(rows))
    sample = next(r for r in broken if r.get("body_index") == 25)
    sample["pose"]["request_ns"] += 150_000_000
    sample["pose"]["response_ns"] += 150_000_000
    sample["host_monotonic_ns"] += 150_000_000
    assert score.verify_trial(trace, score.matrix(PROTOCOL)[0], broken, PROTOCOL)[0] is False
    broken = [r for r in rows if not (r["kind"] == "timeline_event" and
              r["name"] == "POLICY_STAND")]
    assert score.verify_trial(trace, score.matrix(PROTOCOL)[0], broken, PROTOCOL)[0] is False


def test_raw_body_packet_controls_pose_and_final_classification():
    trace, rows = synthetic_trial()
    broken = json.loads(json.dumps(rows))
    sample = next(r for r in broken if r.get("body_index") == 90)
    sample["pose"]["x_m"] = 1.0
    assert score.verify_trial(trace, score.matrix(PROTOCOL)[0], broken, PROTOCOL)[0] is False
    assert score.final_flags(trace["metrics"]["settled_pose"], PROTOCOL) == []


def test_final_envelope_observation_does_not_trigger_runner_fault():
    pose = {"request_ns": 1, "response_ns": 2, "sim_time_s": 1.,
            "x_m": 1., "y_m": 1., "trunk_z_m": 1.,
            "heading_rad": 2., "roll_rad": 0., "pitch_rad": 0.}
    row = {"pose": pose, "host_monotonic_ns": 3}
    assert runner.body_fault(row, None, 3, PROTOCOL) is None
    assert score.final_flags(pose, PROTOCOL) == [
        "OUTSIDE_X", "OUTSIDE_Y", "OUTSIDE_Z", "OUTSIDE_HEADING"]
