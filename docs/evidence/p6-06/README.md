# P6-06 Thor fault, restart, and observed-stop evidence

## Result and scope

The official Thor `robotd` and headless MuJoCo instance completed all 23
canonical cases in `fault-matrix-v1.json`: camera/ToF and perception faults,
neural and decoder faults, delayed command, maximal looming input, separate
connectome-process crash/freeze, IPC faults, real `robotd` restart, and full
`duck-sim down/up`. The matrix records injection, detection, first safe command,
observed rest, recovery, and replay outcome for each case. Its runtime result
is PASS; the P6-06 task still requires independent final-head review.

The test ran on `jetsonthor01` with source commit
`41e6d592ac9230f1502e3df7760a16349c0bcdac` and fixture SHA256
`ab3312b19e3bccb7cfe44369bff0bf07e32a670d5c20cbc9e10c4915c50de1b2`.
Pinned upstream identities were MicroDuck
`344925c9f8fa031f85428a305b1e8ec2eaae29c1` and microduck_rl
`cb70b792312d559a4da09064d92009079671815f`. The graph cache key was
`340f6a3180026f6c61f19ebc016ae8610ec9f4a07af2af589e4d6d89e5b31f70`.
The frozen steering sign was `-1`, stop transport was `robot_stop`, and
perception/neural/behavior TTLs were 100 ms.

The pinned 570-node graph generated no nonzero robot-facing motion in the
P6-05 natural-input trace. For this **safety fault test only**, the fixture
injects a labeled 1.0 current into DNa02 body `523769` inside the MaleCNS
runtime before sensor loss and in the separate process-failure worker. Runtime
stepping, DN aggregation, decoder, SafetyClamp, watchdog, sealed adapter,
official `robotd`, and MuJoCo remain in the command path. This is an
engineering test input, not evidence of biological sensory steering or a
Phase-7 behavior result.

## Observed safety behavior

- All 23 cases reached five consecutive official `robot.state` and 100 ms
  MuJoCo heading windows at rest. Requested and applied twist were within
  `1e-6` for ordinary stops; body angular rate was at most `0.01 rad/s`.
- Camera, ToF, stale-frame, and compositor faults produced zero sensory
  channels and external stimulation, then continued through the MaleCNS
  runtime, DN readout, decoder, clamp, watchdog, and official robot-facing
  neutral `move` command. No later motion command appeared in those fault
  windows. The matrix records `first_safe_transport: neutral_move` for these
  cases and `stop_transport: robot_stop` for the later shutdown stop.
- Separate process crash and freeze left a stale requested twist of about
  `0.060 rad/s`; official `robotd` reported `limited_by: ["deadman"]` and
  applied twist below `1e-6` for five windows. The matrix's detection time
  is the observed `robotd` deadman state; the earlier harness confirmation of
  the process fault is recorded separately in the raw artifact. The first
  safe mechanism is labeled `robotd_deadman`; the fixture sent a new
  `robot_stop` before resuming.
- Seven reconnect/restart paths explicitly rejected a **new** motion output
  before a fresh watchdog safe stop with `reconnect requires a fresh watchdog
  safe-stop output`. Previously used output replay was also rejected.
- Worst detection, safe-command, and observed-rest times were respectively
  6185.236 ms, 13462.354 ms, and 14080.369 ms. The largest values belong to
  full simulator shutdown/startup and are **not** watchdog response times.

## Validation and retained artifacts

Thor Python 3.12 ran focused P4/P5/P6 perception, sensory, decoder, safety,
watchdog, adapter, IPC, scheduler, telemetry, and new fault tests:
`209 passed, 26 subtests passed in 2.71s`.

Raw files remain under
`/home/juper007/projects/microduck-connectome-thor/evidence/p6-06/20260924T-p606-final-v7`.
The matrix copied into this repository is byte-identical to the Thor file.

| Artifact | Bytes | SHA256 |
|---|---:|---|
| `fault-events.jsonl` | 267942 | `7d800e2d053c132ea83d371051f1c54448ecfae78fe4bd7cd8689b7782e4037d` |
| `fault-matrix.json` | 75411 | `47329846a93c41f05e97f0e20e5adc5fd706253b7312e23c4573bdb9b8787a24` |
| `fixture.log` | 42657 | `e93728e0a297a4d85c8371ac864a58c97b00216f9cc4c595c710079878313fd6` |
| `python312-tests.log` | 334 | `d9d260e78ca22c83296a20b18b1acb7e574ca1eb95bf1bde6907fc9c4829924f` |

The two separate worker stderr logs were empty (SHA256
`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`).
No credentials or SSH material are included. The official simulator launcher
printed optional `policy.fetch`/permission diagnostics during startup, while
the real `robotd` health query reported a healthy 50 Hz loop and bus.
