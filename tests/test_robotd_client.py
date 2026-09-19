from __future__ import annotations

import json
import socket

import pytest

from microduck_connectome.motion_adapter import _BoundedRobotdCommand, _bounded_command
from microduck_connectome.robotd_client import (
    MAX_LINE_BYTES,
    I32_MAX,
    I32_MIN,
    U32_MAX,
    U64_MAX,
    RobotdClient,
    RobotdConnectionError,
    RobotdProtocolError,
    RobotdRemoteError,
    RobotdTimeoutError,
)


def _response(request: dict, result: object) -> bytes:
    return (
        json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result})
        + "\n"
    ).encode()


def _hello(request: dict) -> bytes:
    assert request["method"] == "hello"
    assert request["params"] == {"api_version": 31}
    return _response(
        request,
        {"api_version": 31, "daemon_version": "0.1.0", "revision": "abc123"},
    )


def _state() -> dict:
    return {
        "t": 1.25,
        "move": {
            "requested": [0.0, 0.0, 0.0],
            "applied": [0.0, 0.0, 0.0],
            "limited_by": [],
        },
        "head": [0.0, 0.0, 0.0, 0.0],
        "policy": "held",
        "safety": {"fallen": False, "limp": False, "gravity": [0.0, 0.0, -1.0]},
        "loop": {"hz": 50.0, "missed": 0},
        "joints": [0.0] * 15,
        "targets": [0.0] * 15,
        "t_ns": 1_250_000_000,
    }


class ScriptedSocket:
    def __init__(self, handler):
        self.handler = handler
        self.responses = bytearray()
        self.closed = False
        self.timeout = None

    def settimeout(self, value):
        self.timeout = value

    def sendall(self, data):
        request = json.loads(data.decode())
        produced = self.handler(request)
        if produced:
            self.responses.extend(produced)

    def recv(self, size):
        if self.closed:
            return b""
        if not self.responses:
            raise socket.timeout("scripted timeout")
        chunk = bytes(self.responses[:size])
        del self.responses[:size]
        return chunk

    def close(self):
        self.closed = True


def _client(handler, *, timeout_s=0.1):
    stream = ScriptedSocket(handler)
    client = RobotdClient("/test/robotd.sock", timeout_s=timeout_s, connector=lambda *_: stream)
    return client, stream


def test_successful_health_and_state_responses():
    def handler(request):
        if request["method"] == "hello":
            return _hello(request)
        if request["method"] == "robot.health":
            return _response(request, {"healthy": True, "degraded": False})
        assert request["method"] == "robot.subscribe"
        assert request["params"] == {"hz": 1}
        ack = _response(request, {"accepted": True})
        note = {"jsonrpc": "2.0", "method": "robot.state", "params": _state()}
        return ack + (json.dumps(note) + "\n").encode()

    client, _ = _client(handler)
    status = client.connect()
    assert status.connected
    assert status.peer_api_version == 31
    assert client.health()["healthy"] is True
    assert client.state()["t_ns"] == 1_250_000_000


def test_adapter_minted_move_is_notification_and_stop_requires_acceptance():
    seen = []

    def handler(request):
        seen.append(request)
        if request["method"] == "hello":
            return _hello(request)
        if request["method"] == "robot.stop":
            return _response(request, {"accepted": True})
        assert request["method"] == "robot.move"
        assert "id" not in request
        return None

    client, _ = _client(handler)
    client.connect()
    assert not hasattr(client, "move")
    client._send_motion(_bounded_command(vx=0.08, vy=0.0, vyaw=-0.5))
    assert client.stop() == {"accepted": True}
    assert seen[-2]["params"] == {"vx": 0.08, "vy": 0.0, "vyaw": -0.5}


def test_raw_or_unbounded_motion_cannot_reach_transport():
    client, stream = _client(_hello)
    client.connect()
    before = len(stream.responses)
    with pytest.raises(TypeError, match="adapter-minted"):
        client._send_motion({"vx": 0.01, "vy": 0.0, "vyaw": 0.0})
    with pytest.raises(TypeError, match="adapter-minted"):
        client._notify("robot.move", {"vx": 999, "vy": 123, "vyaw": 456})
    with pytest.raises(ValueError, match="P6-03 envelope"):
        client._send_motion(_bounded_command(vx=999, vy=123, vyaw=456))
    with pytest.raises(TypeError, match="adapter-minted"):
        _BoundedRobotdCommand(_seal=None, vx=0.0, vy=0.0, vyaw=0.0)
    assert len(stream.responses) == before


def test_stop_rejection_is_an_error():
    def handler(request):
        if request["method"] == "hello":
            return _hello(request)
        return _response(request, {"accepted": False, "reason": "no"})

    client, _ = _client(handler)
    client.connect()
    with pytest.raises(RobotdRemoteError, match="robotd error -1: no"):
        client.stop()


def test_connection_refused_is_reported():
    def refused(*_):
        raise ConnectionRefusedError("refused")

    client = RobotdClient("/missing.sock", connector=refused)
    with pytest.raises(RobotdConnectionError, match="refused"):
        client.connect()
    assert not client.status.connected


def test_timeout_disconnects_client():
    client, stream = _client(lambda _request: None)
    with pytest.raises(RobotdTimeoutError):
        client.connect()
    assert stream.closed
    assert not client.status.connected


def test_malformed_payload_is_rejected():
    client, _ = _client(lambda _request: b"not-json\n")
    with pytest.raises(RobotdProtocolError, match="malformed JSON"):
        client.connect()


def test_wrong_response_type_is_rejected():
    def handler(request):
        if request["method"] == "hello":
            return _hello(request)
        return _response(request, {"healthy": "yes"})

    client, _ = _client(handler)
    client.connect()
    with pytest.raises(RobotdProtocolError, match="boolean healthy"):
        client.health()


def test_disconnect_is_detected_and_clears_status():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return _hello(request)
        return None

    client, stream = _client(handler)
    client.connect()
    stream.closed = True
    with pytest.raises(RobotdConnectionError, match="closed"):
        client.health()
    assert not client.status.connected


def test_reconnect_uses_new_generation_and_does_not_reset_ids():
    streams = []

    def connector(*_):
        stream = ScriptedSocket(_hello)
        streams.append(stream)
        return stream

    client = RobotdClient("/test.sock", connector=connector)
    first = client.connect()
    second = client.reconnect()
    assert first.generation == 1
    assert second.generation == 2
    assert streams[0].closed


def test_stale_response_is_ignored_until_current_id_arrives():
    def handler(request):
        if request["method"] == "hello":
            return _hello(request)
        stale = {
            "jsonrpc": "2.0",
            "id": request["id"] - 1,
            "result": {"healthy": False, "reason": "stale"},
        }
        return (json.dumps(stale) + "\n").encode() + _response(
            request, {"healthy": True}
        )

    client, _ = _client(handler)
    client.connect()
    assert client.health() == {"healthy": True}


def test_state_rejects_unexpected_schema():
    def handler(request):
        if request["method"] == "hello":
            return _hello(request)
        ack = _response(request, {"accepted": True})
        note = {"jsonrpc": "2.0", "method": "robot.state", "params": {"t": 1.0}}
        return ack + (json.dumps(note) + "\n").encode()

    client, _ = _client(handler)
    client.connect()
    with pytest.raises(RobotdProtocolError, match="robot.state move"):
        client.state()


def test_health_rejects_invalid_nested_control_loop_schema():
    def handler(request):
        if request["method"] == "hello":
            return _hello(request)
        return _response(request, {"healthy": True, "control_loop": "not-an-object"})

    client, _ = _client(handler)
    client.connect()
    with pytest.raises(RobotdProtocolError, match="control_loop must be an object"):
        client.health()


def test_state_rejects_empty_move_schema():
    def handler(request):
        if request["method"] == "hello":
            return _hello(request)
        bad_state = _state()
        bad_state["move"] = {}
        ack = _response(request, {"accepted": True})
        note = {"jsonrpc": "2.0", "method": "robot.state", "params": bad_state}
        return ack + (json.dumps(note) + "\n").encode()

    client, _ = _client(handler)
    client.connect()
    with pytest.raises(RobotdProtocolError, match="move.requested"):
        client.state()


def test_oversized_single_line_is_rejected():
    oversized = b'"' + (b"x" * MAX_LINE_BYTES) + b'"\n'
    client, _ = _client(lambda _request: oversized)
    with pytest.raises(RobotdProtocolError, match="64 KiB"):
        client.connect()


def test_line_at_64_kib_boundary_is_accepted():
    def handler(request):
        response = _hello(request).rstrip(b"\n")
        return response + (b" " * (MAX_LINE_BYTES - len(response))) + b"\n"

    client, _ = _client(handler)
    assert client.connect().peer_api_version == 31


@pytest.mark.parametrize("api_version", [-1, U32_MAX + 1, True])
def test_hello_rejects_values_outside_upstream_u32(api_version):
    def handler(request):
        return _response(
            request,
            {"api_version": api_version, "daemon_version": "0.1.0", "revision": None},
        )

    client, _ = _client(handler)
    with pytest.raises(RobotdProtocolError, match="hello api_version"):
        client.connect()


def test_hello_accepts_upstream_u32_boundaries():
    versions = iter((0, U32_MAX))

    def connector(*_):
        version = next(versions)
        return ScriptedSocket(
            lambda request: _response(
                request,
                {"api_version": version, "daemon_version": None, "revision": None},
            )
        )

    client = RobotdClient("/test.sock", connector=connector)
    assert client.connect().peer_api_version == 0
    assert client.reconnect().peer_api_version == U32_MAX


def test_health_rejects_null_nonoptional_bus():
    def handler(request):
        if request["method"] == "hello":
            return _hello(request)
        return _response(request, {"healthy": True, "bus": None})

    client, _ = _client(handler)
    client.connect()
    with pytest.raises(RobotdProtocolError, match="bus must be an object"):
        client.health()


def test_health_enforces_upstream_unsigned_ranges():
    def handler(request):
        if request["method"] == "hello":
            return _hello(request)
        return _response(
            request,
            {
                "healthy": True,
                "bus": {"consecutive_errors": U32_MAX, "startup_failures": U32_MAX + 1},
            },
        )

    client, _ = _client(handler)
    client.connect()
    with pytest.raises(RobotdProtocolError, match="startup_failures"):
        client.health()


@pytest.mark.parametrize("imu", ["not-an-object", [], 1])
def test_state_rejects_non_object_imu(imu):
    def handler(request):
        if request["method"] == "hello":
            return _hello(request)
        bad_state = _state()
        bad_state["imu"] = imu
        ack = _response(request, {"accepted": True})
        note = {"jsonrpc": "2.0", "method": "robot.state", "params": bad_state}
        return ack + (json.dumps(note) + "\n").encode()

    client, _ = _client(handler)
    client.connect()
    with pytest.raises(RobotdProtocolError, match="imu must be an object or null"):
        client.state()


def test_state_accepts_null_imu_and_u64_timestamp_boundary():
    def handler(request):
        if request["method"] == "hello":
            return _hello(request)
        state = _state()
        state["imu"] = None
        state["t_ns"] = U64_MAX
        ack = _response(request, {"accepted": True})
        note = {"jsonrpc": "2.0", "method": "robot.state", "params": state}
        return ack + (json.dumps(note) + "\n").encode()

    client, _ = _client(handler)
    client.connect()
    assert client.state()["t_ns"] == U64_MAX


def test_nonfinite_number_is_rejected_even_in_unknown_field():
    def handler(request):
        if request["method"] == "hello":
            return _hello(request)
        return _response(request, {"healthy": True, "future_field": float("nan")})

    client, _ = _client(handler)
    client.connect()
    with pytest.raises(RobotdProtocolError, match="malformed JSON"):
        client.health()


@pytest.mark.parametrize("response_id", [-1, U64_MAX + 1, True, 1.5])
def test_invalid_upstream_response_id_is_rejected_immediately(response_id):
    def handler(request):
        return (
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": response_id,
                    "result": {
                        "api_version": 31,
                        "daemon_version": None,
                        "revision": None,
                    },
                }
            )
            + "\n"
        ).encode()

    client, _ = _client(handler)
    with pytest.raises(RobotdProtocolError, match="response id"):
        client.connect()


@pytest.mark.parametrize(
    "daemon_version",
    [
        "not-semver",
        "1.2",
        "01.2.3",
        "1.02.3",
        "1.2.03",
        f"{U64_MAX + 1}.0.0",
        123,
    ],
)
def test_hello_rejects_invalid_semver_or_type(daemon_version):
    def handler(request):
        return _response(
            request,
            {"api_version": 31, "daemon_version": daemon_version, "revision": None},
        )

    client, _ = _client(handler)
    with pytest.raises(RobotdProtocolError, match="daemon_version"):
        client.connect()


@pytest.mark.parametrize(
    "daemon_version", [None, "0.0.0", "1.2.3-alpha.1+build.5", "999.0.1"]
)
def test_hello_accepts_pinned_semver_shapes(daemon_version):
    def handler(request):
        return _response(
            request,
            {"api_version": 31, "daemon_version": daemon_version, "revision": None},
        )

    client, _ = _client(handler)
    assert client.connect().peer_api_version == 31


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("accepted", "yes"),
        ("walk", 1),
        ("stand", []),
        ("unavailable", False),
        ("sitstand", {}),
        ("ground_pick", 0.5),
        ("skills", ["valid", 3]),
    ],
)
def test_subscribe_rejects_each_known_field_with_wrong_type(field, bad_value):
    def handler(request):
        if request["method"] == "hello":
            return _hello(request)
        result = {"accepted": True, "skills": []}
        result[field] = bad_value
        return _response(request, result)

    client, _ = _client(handler)
    client.connect()
    with pytest.raises(RobotdProtocolError, match=f"robot.subscribe {field}"):
        client.state()


@pytest.mark.parametrize(
    ("block", "field", "bad_value", "match"),
    [
        ("theremin", "hand_range_m", "near", "theremin.hand_range_m"),
        ("theremin", "note_hz", [], "theremin.note_hz"),
        ("theremin", "mouth", "bad", "theremin.mouth"),
        ("theremin", "zones", -1, "theremin.zones"),
        ("theremin", "zones", U32_MAX + 1, "theremin.zones"),
        ("theremin", "held", 1, "theremin.held"),
        ("theremin", "sensor", 1, "theremin.sensor"),
        ("chorale", "listening", 1, "chorale.listening"),
        ("chorale", "part", 1, "chorale.part"),
        ("chorale", "joining", "yes", "chorale.joining"),
        ("chorale", "beats", "one", "chorale.beats"),
        ("chorale", "voices", -1, "chorale.voices"),
        ("chorale", "voices", U32_MAX + 1, "chorale.voices"),
    ],
)
def test_state_rejects_known_optional_nested_field_type(block, field, bad_value, match):
    def handler(request):
        if request["method"] == "hello":
            return _hello(request)
        state = _state()
        state[block] = {field: bad_value}
        ack = _response(request, {"accepted": True})
        note = {"jsonrpc": "2.0", "method": "robot.state", "params": state}
        return ack + (json.dumps(note) + "\n").encode()

    client, _ = _client(handler)
    client.connect()
    with pytest.raises(RobotdProtocolError, match=match):
        client.state()


def test_known_optional_nested_boundaries_and_unknown_fields_are_accepted():
    def handler(request):
        if request["method"] == "hello":
            return _hello(request)
        state = _state()
        state["theremin"] = {
            "hand_range_m": None,
            "note_hz": 440.0,
            "mouth": 1.0,
            "zones": U32_MAX,
            "held": False,
            "sensor": None,
            "future_field": "preserved",
        }
        state["chorale"] = {
            "listening": True,
            "part": None,
            "joining": False,
            "beats": None,
            "voices": U32_MAX,
            "future_field": {},
        }
        state["future_top_level"] = {"finite": 1.0}
        ack = _response(
            request,
            {
                "accepted": True,
                "walk": None,
                "stand": "stand.onnx",
                "unavailable": None,
                "sitstand": None,
                "ground_pick": None,
                "skills": ["wave"],
                "future_field": 1,
            },
        )
        note = {"jsonrpc": "2.0", "method": "robot.state", "params": state}
        return ack + (json.dumps(note) + "\n").encode()

    client, _ = _client(handler)
    client.connect()
    assert client.state()["chorale"]["voices"] == U32_MAX


@pytest.mark.parametrize(
    ("field", "bad_value", "match"),
    [
        ("healthy", 1, "boolean healthy"),
        ("degraded", 0, "degraded must be boolean"),
        ("reason", 1, "reason must be a string"),
        ("battery", {}, "battery lacks"),
        ("motors", {}, "motors lacks"),
        ("cpu_temp_c", "hot", "cpu_temp_c"),
        ("control_loop", {}, "control_loop lacks"),
        ("bus", [], "bus must be an object"),
        ("imu", [], "imu must be an object"),
    ],
)
def test_health_rejects_each_known_field_with_wrong_shape(field, bad_value, match):
    def handler(request):
        if request["method"] == "hello":
            return _hello(request)
        health = {"healthy": True}
        health[field] = bad_value
        return _response(request, health)

    client, _ = _client(handler)
    client.connect()
    with pytest.raises(RobotdProtocolError, match=match):
        client.health()


@pytest.mark.parametrize(
    ("field", "bad_value", "match"),
    [
        ("odom", None, "odom must be dict"),
        ("frames", [], "frames must be dict"),
        ("skeleton", {}, "skeleton must be an object array"),
    ],
)
def test_state_rejects_remaining_optional_top_level_shapes(field, bad_value, match):
    def handler(request):
        if request["method"] == "hello":
            return _hello(request)
        state = _state()
        state[field] = bad_value
        ack = _response(request, {"accepted": True})
        note = {"jsonrpc": "2.0", "method": "robot.state", "params": state}
        return ack + (json.dumps(note) + "\n").encode()

    client, _ = _client(handler)
    client.connect()
    with pytest.raises(RobotdProtocolError, match=match):
        client.state()


@pytest.mark.parametrize(
    "daemon_version", ["1.2.3٢", "1٢.0.0", "1.2.3-1٢", "١.2.3"]
)
def test_hello_rejects_non_ascii_semver_digits(daemon_version):
    def handler(request):
        return _response(
            request,
            {"api_version": 31, "daemon_version": daemon_version, "revision": None},
        )

    client, _ = _client(handler)
    with pytest.raises(RobotdProtocolError, match="semantic version"):
        client.connect()


@pytest.mark.parametrize("code", [I32_MIN - 1, I32_MAX + 1])
def test_jsonrpc_error_code_rejects_values_outside_i32(code):
    def handler(request):
        return (
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": request["id"],
                    "error": {"code": code, "message": "boundary"},
                }
            )
            + "\n"
        ).encode()

    client, _ = _client(handler)
    with pytest.raises(RobotdProtocolError, match="invalid error object"):
        client.connect()


@pytest.mark.parametrize("code", [I32_MIN, I32_MAX, 0])
def test_jsonrpc_error_code_accepts_i32_boundaries(code):
    def handler(request):
        return (
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": request["id"],
                    "error": {"code": code, "message": "boundary"},
                }
            )
            + "\n"
        ).encode()

    client, _ = _client(handler)
    with pytest.raises(RobotdRemoteError) as caught:
        client.connect()
    assert caught.value.code == code
