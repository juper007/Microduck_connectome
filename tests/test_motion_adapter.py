from pathlib import Path
from types import SimpleNamespace

import pytest

from microduck_connectome.control_contracts import make_behavior_intent
from microduck_connectome.motion_adapter import (
    MotionAdapterError,
    PostWatchdogIntent,
    RobotMotionAdapter,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "motion_adapter_v1.json"


class FakeClient:
    def __init__(self):
        self.calls = []
        self.status = SimpleNamespace(connected=True, generation=1)

    def move(self, **values):
        self.calls.append(("move", values))

    def stop(self):
        self.calls.append(("stop", {}))
        return {"accepted": True}


def watched(*, vx=0.0, vy=0.0, vyaw=0.0, stop=False, state="healthy", reason=None):
    return {
        "intent": make_behavior_intent(
            timestamp_ns=1, sequence=1, vx=vx, vy=vy, vyaw=vyaw, stop=stop
        ),
        "watchdog_state": state,
        "stale_reason": reason,
        "decoder_alive": state == "healthy",
    }


@pytest.mark.parametrize(
    ("vx", "vyaw"),
    [(0.0, 0.0), (0.08, 0.5), (-0.08, -0.5), (0.0, 0.2), (0.0, -0.2)],
)
def test_zero_signed_yaw_and_max_bounds_are_sent(vx, vyaw):
    client = FakeClient()
    adapter = RobotMotionAdapter(client, CONFIG)
    result = adapter.send(PostWatchdogIntent.from_watchdog_result(watched(vx=vx, vyaw=vyaw)))
    assert result == "move"
    assert client.calls == [("move", {"vx": vx, "vy": 0.0, "vyaw": vyaw})]


@pytest.mark.parametrize(
    "values", [{"vx": 0.0800001}, {"vy": 0.001}, {"vyaw": 0.500001}]
)
def test_out_of_envelope_is_rejected(values):
    adapter = RobotMotionAdapter(FakeClient(), CONFIG)
    command = PostWatchdogIntent.from_watchdog_result(watched(**values))
    with pytest.raises(MotionAdapterError):
        adapter.send(command)


def test_invalid_nonfinite_and_pre_safety_inputs_are_rejected():
    adapter = RobotMotionAdapter(FakeClient(), CONFIG)
    with pytest.raises(TypeError, match="PostWatchdogIntent"):
        adapter.send(make_behavior_intent(timestamp_ns=1, sequence=1, vx=0.01))
    bad = watched()
    bad["intent"]["vyaw"] = float("nan")
    with pytest.raises(MotionAdapterError, match="invalid watchdog intent"):
        PostWatchdogIntent.from_watchdog_result(bad)
    with pytest.raises(TypeError, match="from_watchdog_result"):
        PostWatchdogIntent(_seal=None, intent=watched()["intent"], watchdog_state="healthy")


def test_robot_stop_is_one_shot_until_motion_resumes():
    client = FakeClient()
    adapter = RobotMotionAdapter(client, CONFIG)
    stopped = PostWatchdogIntent.from_watchdog_result(
        watched(stop=True, state="safe_stop", reason="stale_behavior")
    )
    assert adapter.send(stopped) == "robot_stop"
    assert adapter.send(stopped) == "robot_stop_latched"
    assert client.calls == [("stop", {})]
    adapter.send(PostWatchdogIntent.from_watchdog_result(watched(vx=0.01)))
    assert adapter.send(stopped) == "robot_stop"
    assert [name for name, _ in client.calls] == ["stop", "move", "stop"]
    client.status.generation = 2
    assert adapter.send(stopped) == "robot_stop"
    assert [name for name, _ in client.calls] == ["stop", "move", "stop", "stop"]


def test_watchdog_safe_stop_shape_is_enforced():
    bad = watched(stop=False, state="safe_stop", reason="decoder_crash")
    with pytest.raises(MotionAdapterError, match="stop-zero"):
        PostWatchdogIntent.from_watchdog_result(bad)


def test_healthy_watchdog_shape_requires_live_decoder():
    bad = watched()
    bad["decoder_alive"] = False
    with pytest.raises(MotionAdapterError, match="live decoder"):
        PostWatchdogIntent.from_watchdog_result(bad)


def test_zero_twist_transport_publishes_every_stop_tick():
    client = FakeClient()
    import json
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    config["stop_transport"] = "zero_twist"
    adapter = RobotMotionAdapter(client, config)
    stopped = PostWatchdogIntent.from_watchdog_result(
        watched(stop=True, state="safe_stop", reason="decoder_crash")
    )
    assert adapter.send(stopped) == "zero_twist"
    assert adapter.send(stopped) == "zero_twist"
    assert len(client.calls) == 2
