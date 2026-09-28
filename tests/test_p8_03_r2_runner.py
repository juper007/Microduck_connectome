"""Safety-failure evidence remains attached to a failed preparation."""
from pathlib import Path
from unittest.mock import patch

from scripts import p8_03_r2_reset_development as dev


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
