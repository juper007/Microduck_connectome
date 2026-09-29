import json
import threading
import time

import pytest

from microduck_connectome.robotd_client import RobotdClient, RobotdProtocolError
from microduck_connectome.robotd_diagnostic import RobotdDiagnosticRecorder


class BlockingStream:
    def __init__(self, *, gap=False, malformed=False, deadman_then_motion=False):
        self.buffer = bytearray()
        self.closed = threading.Event()
        self.gap = gap
        self.malformed = malformed
        self.deadman_then_motion = deadman_then_motion
        self.sent = []

    def settimeout(self, _value):
        pass

    def sendall(self, data):
        request = json.loads(data)
        self.sent.append(request)
        result = ({"api_version": 32, "daemon_version": "0.1.0", "revision": "test"}
                  if request["method"] == "hello" else {"accepted": True})
        self.buffer.extend((json.dumps({"jsonrpc": "2.0", "id": request["id"],
                                        "result": result}) + "\n").encode())
        if request["method"] == "robot.subscribe":
            assert request["params"] == {}
            for sequence in (1, 3 if self.gap else 2):
                state = {"t": 1.0,
                         "move": {"requested": [0.0]*3, "applied": [0.0]*3},
                         "head": [0.0]*4, "policy": "held",
                         "safety": {"fallen": False, "limp": False},
                         "loop": {"hz": 50.0, "missed": 0},
                         "joints": [], "targets": [],
                         "t_ns": 1_250_000_000 + (sequence-1)*20_000_000,
                         "control_tick_sequence": sequence,
                         "consumed_move_generation": 4}
                if self.malformed and sequence == 2:
                    state["move"] = {}
                if self.deadman_then_motion:
                    state["policy"] = "walk"
                    state["consumed_move_generation"] = sequence
                    state["move"] = {
                        "requested": [0.1, 0.0, 0.0],
                        "applied": [0.0 if sequence == 1 else 0.08, 0.0, 0.0],
                        "limited_by": ["deadman"] if sequence == 1 else [],
                    }
                self.buffer.extend((json.dumps({"jsonrpc": "2.0", "method": "robot.state",
                                                "params": state}) + "\n").encode())

    def recv(self, size):
        while not self.buffer and not self.closed.is_set():
            self.closed.wait(0.01)
        if not self.buffer:
            return b""
        data = bytes(self.buffer[:size])
        del self.buffer[:size]
        return data

    def close(self):
        self.closed.set()


def test_diagnostic_recorder_persists_every_frame_and_move_wire(tmp_path, monkeypatch):
    import microduck_connectome.robotd_client as client_module

    monkeypatch.setattr(client_module.time, "CLOCK_MONOTONIC", 1, raising=False)
    monkeypatch.setattr(client_module.time, "clock_gettime_ns", lambda _: 1_300_000_000,
                        raising=False)
    stream = BlockingStream()
    client = RobotdClient("/test", timeout_s=0.5, connector=lambda *_: stream)
    ledger = tmp_path / "diagnostic.jsonl"
    with RobotdDiagnosticRecorder(client, ledger) as recorder:
        recorder.assert_healthy()
        request = b'{"jsonrpc":"2.0","id":7,"method":"robot.move","params":{"vx":0.1}}\n'
        ack = b'{"jsonrpc":"2.0","id":7,"result":{"accepted":true,"accepted_move_generation":5}}\n'
        recorder.record_move_request(request, sent_at_ns=1_280_000_000)
        recorder.record_move_ack(ack, received_at_ns=1_290_000_000)
    rows = [json.loads(line) for line in ledger.read_text().splitlines()]
    states = [row for row in rows if row["kind"] == "robot.state"]
    wires = [row for row in rows if row["kind"] == "robotd.wire"]
    assert len(wires) == 2
    assert [row["state"]["control_tick_sequence"] for row in states] == [1, 2]
    kinds = [row["kind"] for row in rows]
    assert kinds.index("robot.move.request") < kinds.index("robot.move.ack")
    assert next(row for row in rows if row["kind"] == "robot.move.ack")["wire"] == ack.decode()


def test_diagnostic_recorder_fails_closed_on_gap(tmp_path, monkeypatch):
    import microduck_connectome.robotd_client as client_module

    monkeypatch.setattr(client_module.time, "CLOCK_MONOTONIC", 1, raising=False)
    monkeypatch.setattr(client_module.time, "clock_gettime_ns", lambda _: 1_300_000_000,
                        raising=False)
    stream = BlockingStream(gap=True)
    client = RobotdClient("/test", timeout_s=0.5, connector=lambda *_: stream)
    recorder = RobotdDiagnosticRecorder(client, tmp_path / "gap.jsonl")
    try:
        try:
            recorder.start()
        except RobotdProtocolError:
            pass
        recorder._thread.join(timeout=0.5)
        with pytest.raises(RobotdProtocolError, match="diagnostic stream"):
            recorder.assert_healthy()
    finally:
        recorder.close()
    rows = [json.loads(line) for line in (tmp_path / "gap.jsonl").read_text().splitlines()]
    assert [row["state"]["control_tick_sequence"] for row in rows
            if row["kind"] == "robot.state"] == [1, 3]
    assert rows[-1]["kind"] == "diagnostic.failure"


def test_malformed_delivered_state_keeps_raw_evidence(tmp_path, monkeypatch):
    import microduck_connectome.robotd_client as client_module

    monkeypatch.setattr(client_module.time, "CLOCK_MONOTONIC", 1, raising=False)
    monkeypatch.setattr(client_module.time, "clock_gettime_ns", lambda _: 1_300_000_000,
                        raising=False)
    stream = BlockingStream(malformed=True)
    client = RobotdClient("/test", timeout_s=0.5, connector=lambda *_: stream)
    recorder = RobotdDiagnosticRecorder(client, tmp_path / "malformed.jsonl")
    try:
        try:
            recorder.start()
        except RobotdProtocolError:
            pass
        recorder._thread.join(timeout=0.5)
        with pytest.raises(RobotdProtocolError, match="diagnostic stream"):
            recorder.assert_healthy()
    finally:
        recorder.close()
    rows = [json.loads(line) for line in (tmp_path / "malformed.jsonl").read_text().splitlines()]
    assert len([row for row in rows if row["kind"] == "robotd.wire"]) == 2
    assert len([row for row in rows if row["kind"] == "robot.state"]) == 1
    assert rows[-1]["kind"] == "diagnostic.failure"


def test_recorder_retains_deadman_tick_followed_by_clean_applied_motion(tmp_path, monkeypatch):
    import microduck_connectome.robotd_client as client_module

    monkeypatch.setattr(client_module.time, "CLOCK_MONOTONIC", 1, raising=False)
    monkeypatch.setattr(client_module.time, "clock_gettime_ns", lambda _: 1_300_000_000,
                        raising=False)
    stream = BlockingStream(deadman_then_motion=True)
    client = RobotdClient("/test", timeout_s=0.5, connector=lambda *_: stream)
    path = tmp_path / "retained.jsonl"
    with RobotdDiagnosticRecorder(client, path) as recorder:
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            recorder.assert_healthy()
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            if sum(row["kind"] == "robot.state" for row in rows) == 2:
                break
            time.sleep(0.001)
    states = [row["state"] for row in map(json.loads, path.read_text().splitlines())
              if row["kind"] == "robot.state"]
    assert [state["consumed_move_generation"] for state in states] == [1, 2]
    assert states[0]["move"]["limited_by"] == ["deadman"]
    assert states[0]["move"]["applied"][0] == 0.0
    assert states[1]["policy"] == "walk"
    assert states[1]["move"]["limited_by"] == []
    assert states[1]["move"]["applied"][0] > 0.0
