# P6-06 restart, dropout, and fault evidence

## Result

The final runtime fixture ran all 18 required fault cases on Thor against the
pinned official `robotd` and headless MuJoCo body. Every case reached an actual
rest state: official `robot.state.move.requested` was zero, applied motion
decayed below `1e-6`, and consecutive MuJoCo headings converged. Every reconnect
or restart rejected the pre-fault watchdog output and required a fresh
`robot_stop` followed by a fresh current intent.

`fault-matrix-v1.json` is the compact machine-readable evidence. It records
monotonic injection, detection, safe-command, observed-motion-stop, and recovery
times for camera/ToF/perception, neural runtime, decoder, IPC, robotd, and full
simulator failures.

## Runtime identity

- Execution target: Thor (`jetsonthor01`)
- Source exercised: `7a7aef15ee3ec7a91c72589c14284cd212d641a9`
- MicroDuck: `344925c9f8fa031f85428a305b1e8ec2eaae29c1`
- microduck_rl: `cb70b792312d559a4da09064d92009079671815f`
- Python: 3.12.3
- steering yaw sign: `-1`
- stop transport: `robot_stop`
- frozen perception/neural/behavior TTL: 100 ms each

The stale perception, frozen neural, and stale decoder cases measure from the
onset of the missing-update interval; watchdog detection occurred at about
101 ms. The bounded IPC read timeout was about 151 ms. Full simulator restart
latency includes the official scoped `duck-sim down` and complete `duck-sim`
startup/stand lifecycle; it is not a watchdog latency.

## Tests

Thor Python 3.12 ran the directly relevant P4/P5/P6 and schema regressions:
`417 passed in 5.50s`. Four unrelated data-evidence modules requiring optional
`pyarrow` were excluded at collection; they are outside the P6 controller,
safety, IPC, scheduler, and telemetry regression scope. The new fault evidence
schema tests separately passed `6 passed in 0.01s` on final source.

## Retained raw artifacts

Artifacts remain on Thor under
`/home/juper007/projects/microduck-connectome-thor/evidence/p6-06/20260919T-p606-v9`.

| Artifact | SHA256 |
|---|---|
| `fault-events.jsonl` | `aff92fae8d7a653c8958ccb7a17fbbe8b09568a958e881126815d4137dfe0aa8` |
| `fault-matrix.json` | `6042dfa77c5ab1640acb5b73b21e2d99de7c53d8b24a0662680ca0d8605552c3` |
| `fixture.log` | `3faefea08df4f1f9ca934eb0f8bc57edab8824f8955fa6f7bc587444033fb2fa` |
| `python312-tests.log` | `d5fd1752ddbc85f3d2552b4b9ef5a03940e5dcec1c97bd75dff94aa647a394b5` |

The large fixture log duplicates the compact matrix on stdout and is retained
externally. No credentials, tokens, or machine secrets are present.

## Scope

This evidence proves Phase-6 fault convergence and fresh-state recovery in the
official simulator. It does not claim a Phase-7 behavior success rate or any
physical-hardware readiness.
