import json
import pickle
from pathlib import Path
from types import SimpleNamespace
from types import MappingProxyType

import pytest

from microduck_connectome.control_contracts import make_behavior_intent
from microduck_connectome.motion_adapter import MotionAdapterError, RobotMotionAdapter
from microduck_connectome.robotd_client import RobotdConnectionError
from microduck_connectome.watchdog import ControllerWatchdog, WatchdogOutput


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "motion_adapter_v1.json"
WATCHDOG_CONFIG = ROOT / "config" / "watchdog_v1.json"


class FakeClient:
    def __init__(self):
        self.calls = []
        self.status = SimpleNamespace(connected=True, generation=1)
        self.fail_stop = False

    def _send_watchdog(self, output, stop_transport):
        intent = output["intent"]
        if intent["stop"]:
            if stop_transport == "robot_stop":
                self.calls.append(("stop", ()))
                if self.fail_stop:
                    self.status.connected = False
                    raise RobotdConnectionError("silent peer loss")
                return "robot_stop_refreshed"
            self.calls.extend([
                ("move", (0.0, 0.0, 0.0)), ("health", ())
            ])
            return "zero_twist_refreshed"
        self.calls.append(("move", (intent["vx"], intent["vy"], intent["vyaw"])))
        return "move"


def watchdog_output(*, timestamp=1, sequence=1, vx=0.0, vy=0.0, vyaw=0.0, stop=False):
    watchdog = ControllerWatchdog(WATCHDOG_CONFIG)
    neural = {
        "timestamp_ns": timestamp,
        "sequence": sequence,
        "steering_left": 0.0,
        "steering_right": 0.0,
        "escape": 0.0,
        "runtime_healthy": True,
    }
    behavior = make_behavior_intent(
        timestamp_ns=timestamp, sequence=sequence, vx=vx, vy=vy, vyaw=vyaw, stop=stop
    )
    assert watchdog.observe_neural(neural)
    assert watchdog.observe_behavior(behavior)
    return watchdog.tick(now_ns=timestamp + 1, output_sequence=sequence + 1)


def safe_output(*, timestamp=1, sequence=1):
    return ControllerWatchdog(WATCHDOG_CONFIG).tick(
        now_ns=timestamp, output_sequence=sequence
    )


@pytest.mark.parametrize(
    ("vx", "vyaw"),
    [(0.0, 0.0), (0.08, 0.5), (-0.08, -0.5), (0.0, 0.2), (0.0, -0.2)],
)
def test_zero_signed_yaw_and_max_bounds_are_sent(vx, vyaw):
    client = FakeClient()
    adapter = RobotMotionAdapter(client, CONFIG)
    result = adapter.send(watchdog_output(vx=vx, vyaw=vyaw))
    assert result == "move"
    assert client.calls == [("move", (vx, 0.0, vyaw))]


@pytest.mark.parametrize(
    "values", [{"vx": 0.0800001}, {"vy": 0.001}, {"vyaw": 0.500001}]
)
def test_out_of_envelope_typed_watchdog_output_is_rejected(values):
    adapter = RobotMotionAdapter(FakeClient(), CONFIG)
    with pytest.raises(MotionAdapterError):
        adapter.send(watchdog_output(**values))


def test_forged_pre_safety_mapping_and_direct_type_construction_are_rejected():
    adapter = RobotMotionAdapter(FakeClient(), CONFIG)
    forged = {
        "intent": make_behavior_intent(timestamp_ns=1, sequence=1, vx=0.01),
        "watchdog_state": "healthy",
        "stale_reason": None,
        "decoder_alive": True,
    }
    with pytest.raises(TypeError, match="ControllerWatchdog.tick"):
        adapter.send(forged)
    with pytest.raises(TypeError, match="ControllerWatchdog"):
        WatchdogOutput()
    forged_output = object.__new__(WatchdogOutput)
    object.__setattr__(forged_output, "_WatchdogOutput__values", MappingProxyType(forged))
    with pytest.raises(TypeError, match="ControllerWatchdog.tick"):
        adapter.send(forged_output)
    genuine = safe_output()
    with pytest.raises(AttributeError, match="immutable"):
        genuine._WatchdogOutput__values = forged
    with pytest.raises(TypeError):
        genuine["intent"]["vx"] = 999
    with pytest.raises(TypeError):
        pickle.dumps(genuine)
    subclass = type("WatchdogOutputSubclass", (WatchdogOutput,), {})
    forged_subclass = object.__new__(subclass)
    object.__setattr__(
        forged_subclass, "_WatchdogOutput__values", MappingProxyType(forged)
    )
    with pytest.raises(TypeError, match="ControllerWatchdog.tick"):
        adapter.send(forged_subclass)


def test_replaced_contents_of_genuine_output_are_rejected():
    adapter = RobotMotionAdapter(FakeClient(), CONFIG)
    genuine = safe_output(timestamp=10, sequence=10)
    replacement = {
        "intent": make_behavior_intent(
            timestamp_ns=20, sequence=20, vx=0.01, vyaw=0.1
        ),
        "watchdog_state": "healthy",
        "stale_reason": None,
        "decoder_alive": True,
    }
    object.__setattr__(
        genuine, "_WatchdogOutput__values", MappingProxyType(replacement)
    )
    with pytest.raises(TypeError, match="ControllerWatchdog.tick"):
        adapter.send(genuine)


def test_robot_stop_is_refreshed_each_tick_and_safe_stop_is_typed():
    client = FakeClient()
    adapter = RobotMotionAdapter(client, CONFIG)
    first = safe_output(timestamp=10, sequence=10)
    second = safe_output(timestamp=11, sequence=11)
    assert adapter.send(first) == "robot_stop_refreshed"
    assert adapter.send(second) == "robot_stop_refreshed"
    assert client.calls == [("stop", ()), ("stop", ())]


def test_silent_disconnect_requires_fresh_safe_stop_and_rejects_stale_replay():
    client = FakeClient()
    adapter = RobotMotionAdapter(client, CONFIG)
    adapter.send(safe_output(timestamp=10, sequence=10))
    client.fail_stop = True
    with pytest.raises(RobotdConnectionError, match="silent peer loss"):
        adapter.send(safe_output(timestamp=20, sequence=20))

    client.fail_stop = False
    client.status.connected = True
    client.status.generation = 2
    pre_reconnect_move = watchdog_output(
        timestamp=30, sequence=30, vx=0.02, vyaw=0.1
    )
    with pytest.raises(MotionAdapterError, match="fresh watchdog safe-stop"):
        adapter.send(pre_reconnect_move)
    adapter.send(safe_output(timestamp=40, sequence=40))
    with pytest.raises(MotionAdapterError, match="stale replay"):
        adapter.send(pre_reconnect_move)
    assert adapter.send(watchdog_output(
        timestamp=50, sequence=50, vx=0.02, vyaw=0.1
    )) == "move"
    assert client.calls[-2:] == [("stop", ()), ("move", (0.02, 0.0, 0.1))]


def test_zero_twist_transport_refreshes_command_and_liveness_each_tick():
    client = FakeClient()
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    config["stop_transport"] = "zero_twist"
    adapter = RobotMotionAdapter(client, config)
    assert adapter.send(safe_output(timestamp=10, sequence=10)) == "zero_twist_refreshed"
    assert adapter.send(safe_output(timestamp=20, sequence=20)) == "zero_twist_refreshed"
    assert client.calls == [
        ("move", (0.0, 0.0, 0.0)), ("health", ()),
        ("move", (0.0, 0.0, 0.0)), ("health", ()),
    ]
