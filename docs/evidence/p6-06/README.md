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
- Source exercised: `8ee0cfb62f44553ab5eb51cf4c9fbc4f63435796`
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
`/home/juper007/projects/microduck-connectome-thor/evidence/p6-06/20260919T-p606-v8`.

| Artifact | SHA256 |
|---|---|
| `fault-events.jsonl` | `8008995fa8cabe2bd2c9b4c1a3ef83d2951d512cf1c8c27ac15ed9a15d329aa5` |
| `fault-matrix.json` | `3ee24507cd2b905844e47a944a899b1c932334872dff58560a3e0cdfbba33b33` |
| `fixture.log` | `53f8a21f7565cc011efdb2ad03692c2eb68aa1ab46be47f6c94ff187d8f87cfc` |

The large fixture log duplicates the compact matrix on stdout and is retained
externally. No credentials, tokens, or machine secrets are present.

## Scope

This evidence proves Phase-6 fault convergence and fresh-state recovery in the
official simulator. It does not claim a Phase-7 behavior success rate or any
physical-hardware readiness.

