from __future__ import annotations

import json
import socket

import pytest

from microduck_connectome.robotd_client import (
    RobotdClient,
    RobotdConnectionError,
    RobotdProtocolError,
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
        "move": {"requested": [0.0, 0.0, 0.0]},
        "head": [0.0, 0.0, 0.0, 0.0],
        "policy": "held",
        "safety": {},
        "loop": {},
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
