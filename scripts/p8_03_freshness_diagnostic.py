"""Development-only, no-motion measurement of robotd diagnostic freshness."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import time

from microduck_connectome.robotd_client import RobotdClient
from microduck_connectome.robotd_diagnostic import RobotdDiagnosticRecorder


def summary(values: list[float]) -> dict:
    if not values:
        return {"count": 0, "p50": None, "p95": None, "p99": None, "max": None}
    ordered = sorted(values)
    def percentile(p: float) -> float:
        return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * p))]
    return {"count": len(values), "p50": percentile(.50), "p95": percentile(.95),
            "p99": percentile(.99), "max": ordered[-1]}


def run(socket: str, output: Path, mode: str, duration_s: float) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    ledger = output / "diagnostic.jsonl"
    ages, arrivals, callback, locks, serial, writes, flushes, fsyncs = (
        [] for _ in range(8)
    )
    ticks: list[int] = []
    generations: list[int] = []
    error = None
    max_depth = 0
    wall_start = time.monotonic()
    if mode == "async":
        recorder = RobotdDiagnosticRecorder(RobotdClient(socket, timeout_s=2), ledger)
        try:
            recorder.start()
            deadline = time.monotonic() + duration_s
            while time.monotonic() < deadline:
                recorder.assert_healthy()
                time.sleep(.005)
        except BaseException as exc:
            error = f"{type(exc).__name__}: {exc}"
        finally:
            recorder.close()
        if recorder._error is not None and error is None:
            error = f"{type(recorder._error).__name__}: {recorder._error}"
        rows = [json.loads(line) for line in ledger.read_text().splitlines()]
        states = [r for r in rows if r["kind"] == "robot.state"]
        ticks = [r["state"]["control_tick_sequence"] for r in states]
        generations = [r["state"]["consumed_move_generation"] for r in states]
        ages = [(r["reader_observed_ns"] - r["state"]["t_ns"]) / 1e6 for r in states]
        arrivals = [r["reader_observed_ns"] for r in states]
        callback = [v / 1e6 for v in recorder.callback_durations_ns]
        serial = [r["serialize_ns"] / 1e6 for r in recorder.writer_timings_ns]
        writes = [r["write_ns"] / 1e6 for r in recorder.writer_timings_ns]
        flushes = [r["flush_ns"] / 1e6 for r in recorder.writer_timings_ns if r["flush_ns"]]
        fsyncs = [r["fsync_ns"] / 1e6 for r in recorder.writer_timings_ns if r["fsync_ns"]]
        max_depth = recorder.max_queue_depth
        dropped = recorder.enqueued_records - recorder.written_records
        durable = recorder.written_records == recorder.synced_records
    else:
        client = RobotdClient(socket, timeout_s=2)
        file = ledger.open("xb", buffering=0) if mode == "sync" else None
        lock = __import__("threading").Lock()
        def append(record: dict) -> None:
            started = time.monotonic_ns()
            with lock:
                acquired = time.monotonic_ns()
                encoded = (json.dumps(record, separators=(",", ":"), allow_nan=False)
                           + "\n").encode()
                encoded_at = time.monotonic_ns()
                assert file is not None
                file.write(encoded)
                written_at = time.monotonic_ns()
                file.flush()
                flushed_at = time.monotonic_ns()
                os.fsync(file.fileno())
                synced_at = time.monotonic_ns()
            locks.append((acquired - started) / 1e6)
            serial.append((encoded_at - acquired) / 1e6)
            writes.append((written_at - encoded_at) / 1e6)
            flushes.append((flushed_at - written_at) / 1e6)
            fsyncs.append((synced_at - flushed_at) / 1e6)
            callback.append((synced_at - started) / 1e6)
        def raw(line: bytes) -> None:
            if mode == "sync":
                append({"kind": "robotd.wire", "received_at_ns":
                        client._last_message_observed_ns, "wire_hex": line.hex()})
        def frame(state: dict) -> None:
            observed = client._last_message_observed_ns
            if mode == "sync":
                append({"kind": "robot.state", "received_at_ns": observed,
                        "state": state})
            ticks.append(state["control_tick_sequence"])
            generations.append(state["consumed_move_generation"])
            ages.append((observed - state["t_ns"]) / 1e6)
            arrivals.append(observed)
        try:
            client.connect()
            deadline = time.monotonic() + duration_s
            while time.monotonic() < deadline:
                client.diagnostic_state(on_raw=raw, on_frame=frame)
        except BaseException as exc:
            error = f"{type(exc).__name__}: {exc}"
        finally:
            client.disconnect()
            if file is not None:
                file.close()
        dropped = 0
        durable = mode == "sync"
    elapsed = time.monotonic() - wall_start
    tick_gaps = sum(b != a + 1 for a, b in zip(ticks, ticks[1:]))
    generation_regressions = sum(b < a for a, b in zip(generations, generations[1:]))
    result = {
        "schema": "p8-03-freshness-development-v1", "mode": mode, "duration_s": elapsed,
        "requested_duration_s": duration_s, "result": "PASS" if (
            error is None and elapsed >= duration_s and tick_gaps == 0
            and generation_regressions == 0 and dropped == 0
            and (durable or mode == "none")
            and all(0 <= age <= 100 for age in ages)
        ) else "FAIL",
        "error": error, "states": len(ticks), "tick_gaps": tick_gaps,
        "generation_regressions": generation_regressions, "dropped_states": dropped,
        "max_queue_depth": max_depth, "fully_fsynced": durable,
        "source_age_ms": summary(ages),
        "reader_interarrival_ms": summary([(b-a)/1e6 for a,b in zip(arrivals,arrivals[1:])]),
        "callback_ms": summary(callback), "lock_wait_ms": summary(locks),
        "json_serialization_ms": summary(serial), "write_ms": summary(writes),
        "flush_ms": summary(flushes), "fsync_ms": summary(fsyncs),
    }
    if ledger.exists():
        result["ledger_sha256"] = hashlib.sha256(ledger.read_bytes()).hexdigest()
    report = output / "result.json"
    report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    result["result_sha256"] = hashlib.sha256(report.read_bytes()).hexdigest()
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("none", "sync", "async"), required=True)
    parser.add_argument("--duration-s", type=float, default=10)
    args = parser.parse_args()
    print(json.dumps(run(args.socket, args.output, args.mode, args.duration_s),
                     sort_keys=True))
