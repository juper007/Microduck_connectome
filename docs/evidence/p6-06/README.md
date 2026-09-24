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
`2891cb952a5bf9168de418056c5c850d0b9ffb33` and fixture SHA256
`cea10f9eade3c5bcec891afa78c4feaf05181eff3123a8ea9d532f7cd0f2bd8d`.
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
- Separate process crash and freeze left a stale requested twist of about
  `0.060 rad/s`; official `robotd` reported `limited_by: ["deadman"]` and
  applied twist below `1e-6` for five windows. The fixture sent a new safe
  stop before resuming.
- Seven reconnect/restart paths explicitly rejected a **new** motion output
  before a fresh watchdog safe stop with `reconnect requires a fresh watchdog
  safe-stop output`. Previously used output replay was also rejected.
- Worst detection, safe-command, and observed-rest times were respectively
  6194.567 ms, 13490.996 ms, and 14094.554 ms. The largest values belong to
  full simulator shutdown/startup and are **not** watchdog response times.

## Validation and retained artifacts

Thor Python 3.12 ran focused P4/P5/P6 perception, sensory, decoder, safety,
watchdog, adapter, IPC, scheduler, telemetry, and new fault tests:
`213 passed, 38 subtests passed in 2.73s`.

Raw files remain under
`/home/juper007/projects/microduck-connectome-thor/evidence/p6-06/20260924T-p606-final-v4`.
The matrix copied into this repository is byte-identical to the Thor file.

| Artifact | Bytes | SHA256 |
|---|---:|---|
| `fault-events.jsonl` | 219684 | `1584c299ac3c64e9d95a4d34b55764da7ee3be21eacc5570d0216674e69d2226` |
| `fault-matrix.json` | 74452 | `230b3e5fb53eba5864aeac4bccd50057dcb89c62047f1b3fd45a2c47003ad301` |
| `fixture.log` | 41836 | `b544ce5d84c434f133dbfbf171dc1845ab343e1afd6c7783097cbbe274d902bc` |
| `python312-tests.log` | 314 | `ea526238c94d443fe9a03c74b5c32068104de90557ba187cb791aa6a5324dba9` |

The two separate worker stderr logs were empty (SHA256
`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`).
No credentials or SSH material are included. The official simulator launcher
printed optional `policy.fetch`/permission diagnostics during startup, while
the real `robotd` health query reported a healthy 50 Hz loop and bus.
