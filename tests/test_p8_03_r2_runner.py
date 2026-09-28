"""Safety-failure evidence remains attached to a failed preparation."""
from pathlib import Path
from unittest.mock import patch

from scripts import p8_03_r2_reset_development as dev
from microduck_connectome.p8_03_r2_reset import REFERENCE


class UnhealthyClient:
    def __init__(self, *args, **kwargs):
        pass

    def connect(self):
        pass

    def health(self):
        return {"healthy": False}

    def close(self):
        raise OSError("close failure")


class CommandConnection:
    def __init__(self, *args, **kwargs):
        self.socket = self

    def settimeout(self, value):
        pass

    def close(self):
        raise OSError("close failure")


def test_stop_attempt_and_trace_survive_preparation_and_close_failures():
    stops = [{"result": "PASS", "ack": {"accepted": True}},
             {"result": "FAIL", "error": "stop unavailable"}]
    with patch.object(dev, "RobotdClient", UnhealthyClient), \
            patch.object(dev, "JsonLines", CommandConnection), \
            patch.object(dev, "emergency_stop", side_effect=stops) as stop:
        try:
            dev.prepare(None, Path("/tmp/isolated.sock"))
        except dev.PreparationFailure as error:
            trace = error.trace
        else:
            raise AssertionError("preparation should fail")
    assert stop.call_count == 2
    assert trace["final_stop"]["result"] == "FAIL"
    assert trace["initial_stop"]["result"] == "PASS"
    assert len(trace["close_errors"]) == 2
    assert "unhealthy" in trace["error"]


def test_perturbation_never_reuses_qualification_seed():
    protocol = {"development_reset_seeds": [887400, 887401]}
    assert dev.development_seed("pilot", 0, protocol) is None
    assert dev.development_seed("perturbation", 0, protocol) is None
    assert dev.development_seed("qualification", 0, protocol) == 887400


def test_perturbation_target_at_deadline_is_failure():
    assert dev.perturbation_target_reached(.09, 1, 1.999, 2.0)
    assert not dev.perturbation_target_reached(.089, 1, 1.999, 2.0)
    try:
        dev.perturbation_target_reached(.2, 1, 2.0, 2.0)
    except TimeoutError:
        pass
    else:
        raise AssertionError("late target was accepted")


def test_perturbation_stop_ack_must_precede_two_second_deadline():
    trace = {"active_phase_s": 1.8, "duration_s": 1.99,
             "stop": {"result": "PASS"}}
    assert dev.perturbation_pass(trace)
    assert not dev.perturbation_pass(dict(trace, duration_s=2.0))
    assert not dev.perturbation_pass(dict(trace, stop={"result": "FAIL"}))


def test_perturbation_settle_requires_stable_offset_outside_guard():
    first = {"pose": dict(REFERENCE, heading_rad=REFERENCE["heading_rad"] + .09)}
    second = {"pose": dict(REFERENCE, heading_rad=REFERENCE["heading_rad"] + .091)}
    assert dev.perturbation_settled(first, second)[0]
    second["pose"]["heading_rad"] = REFERENCE["heading_rad"] + .05
    assert not dev.perturbation_settled(first, second)[0]
    second["pose"]["heading_rad"] = REFERENCE["heading_rad"] + .097
    assert not dev.perturbation_settled(first, second)[0]


class FixedReader:
    def __init__(self, port):
        self.sock = self

    def settimeout(self, value):
        pass

    def read(self):
        return {"request_ns": 1, "response_ns": 2, "sim_time_s": 1.0,
                "roll_rad": 0.0, "pitch_rad": 0.0, "pose": dict(REFERENCE)}

    def close(self):
        pass


class HealthyClient(UnhealthyClient):
    def health(self):
        return {"healthy": True, "degraded": False}

    def close(self):
        pass


class QuietCommand(CommandConnection):
    def close(self):
        pass


def test_perturbation_health_delay_cannot_send_after_deadline():
    clock = iter([0.0, 0.0, 2.01, 2.02])
    with patch.object(dev, "TimedPoseReader", FixedReader), \
            patch.object(dev, "RobotdClient", HealthyClient), \
            patch.object(dev, "JsonLines", QuietCommand), \
            patch.object(dev.time, "monotonic", side_effect=lambda: next(clock)), \
            patch.object(dev, "acknowledged_precondition_move") as move, \
            patch.object(dev, "emergency_stop", return_value={"result": "PASS"}):
        trace = dev.perturb_heading(7898, Path("/tmp/isolated.sock"), 1)
    assert trace["result"] == "FAIL"
    assert "deadline elapsed during health read" in trace["error"]
    move.assert_not_called()
    assert trace["stop"]["result"] == "PASS"
