# P8-V2-FAULT-STOP-PROBE — development evidence

Task: `docs/tasks/P8-V2-FAULT-STOP-PROBE.md`. Primary skill: `$robot-safety-engineer`. Base `origin/main`: `34b48af891c508f83bf50eb9f8accd1f0a57bd22`. Branch: `test/p8-v2-fault-stop-probe`. This is development evidence; it is **not** the preregistered P8-04 final sensor-loss suite.

The reusable `FaultStopLatch`, `FaultAwareInputs`, and `FaultStopRefreshScheduler` distinguish planned invalid camera/ToF/neural input from an unexpected perception/neural worker exception. Once latched, the production Watchdog issues authentic high-level stop intent through `RobotMotionAdapter` to `robot.stop` at the 50 Hz cadence until pose-derived cessation. The watchdog's existing TTL, P6 safety limits, adapter transport, and robotd motor authority remain unchanged. A transport/IPC outage cannot guarantee stop ACK; that condition requires separate final testing.

## Retained official Thor runs

All raw paths are under `/home/juper007/projects/microduck-connectome-thor/evidence/p8-v2-fault-stop/`. The [machine-readable index](probe-index-v1.json) verifies each retained file's path, size, record count where applicable, and SHA256. Its own SHA256 is `5b8a83d58a6661b8549c3a9c2a1ab43c217fb859944c94c4eca065c88fa99998`.

| Raw directory | Source head | Started / planned | Result |
| --- | --- | --- | --- |
| `probe-8d2bee9-camera-1` | `8d2bee9ed0a44e7ee56ddefa3b1c8839f3e25d7f` | 1 / 1 | Preliminary unseeded camera-loss PASS |
| `probe-49c0c71-matrix-1` | `49c0c71d13fbe9ec8ec4bc2f0779dbe1c026271e` | 7 / 8 | Six PASS, neural-freeze FAIL, unexpected-worker row NOT_STARTED |
| `probe-4107426-freeze-exception-1` | `4107426585724e29268cf4c6730f2507002a6500` | 2 / 2 | Neural-freeze PASS; unexpected worker physically safe with one attributed scheduler exception |

Development seeds were `884000`–`884006` and `884100`–`884101`; the first camera trial was unseeded. The first matrix's failed neural-freeze assertion required the wrapper's `fault_stale_neural` to be the first stop source. Raw events show that the unmodified production Watchdog issued the earlier, authentic `stale_neural` stop. The later source version explicitly accepts this earlier safety action; the failed run and unstarted row remain in the index and original raw directory.

Across the nine development PASS/physically-safe trials, the first stop ACK followed fault detection/injection by 2.46–86.02 ms; ACK gaps were 20.06–20.91 ms, and first ACK to pose-derived stop was 688.89–732.23 ms. The retained failed-assertion neural-freeze trial also stopped physically, with 39 stop ACKs and 20.94 ms maximum ACK gap. Every started trial performed final `duck-sim down`, had no post-stop `robot.move`, and showed no deadman-caused stop before pose cessation. Planned invalid sensor/neural trials recorded zero scheduler exceptions. The deliberately unexpected worker case retained one scheduler exception and is **not** a clean zero-exception final-gate PASS. No safety-limit violation was observed.

Thor Python 3.12.3 targeted regression: `python3.12 -m pytest -q tests/test_fault_stop.py tests/test_watchdog.py tests/test_scheduler.py tests/test_motion_adapter.py` → **39 passed**. Windows Python 3.12.14 fault/watchdog tests passed; an existing scheduler equal-timestamp race is intermittently reproducible on Windows baseline, so Thor is the authoritative scheduler result. The development simulator used its isolated checkout, state `/tmp/p8-fault-probe-state`, and port `7898`; final down completed and the port was released.

## Protocol freeze recommendations and remaining work

- Predefine fault injection to first authentic stop ACK at no more than 200 ms for sensor loss and frozen neural update, subsequent ACK gaps at no more than 100 ms, and pose-derived stop at no more than 900 ms after first ACK. These are recommendations for independent preregistration review, not retrospectively applied final criteria.
- Preserve source attribution. A `stale_neural` watchdog stop during neural freeze is a valid safety stop and must never count as healthy neural looming. Planned invalid-input faults should remain scheduler-exception-free. Unexpected worker exceptions must be reported separately.
- Final P8-04 still needs frozen seeds, intermittent frames, IPC outage/restart, maximum stimulus, repeat statistics, and its own official Thor evidence. For IPC outage, record the failed ACK and physical outcome without claiming that a stop was acknowledged.
