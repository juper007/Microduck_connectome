# P6-06 restart, dropout, and fault evidence

## Result

The final runtime fixture ran all 18 required fault cases on Thor against the
pinned official `robotd` and headless MuJoCo body. Sensor, neural, and decoder
faults were injected inside live scheduler workers and traversed the real
PerceptionCompositor, SensoryMapper, MaleCNS runtime, DN aggregation, decoder,
SafetyClamp, Watchdog, adapter, and robotd boundaries. Every case reached an
actual rest state: five consecutive official requested/applied samples were
below `1e-6`, and five consecutive 100 ms MuJoCo heading windows were below
`0.01 rad/s`. Every reconnect
or restart rejected the pre-fault watchdog output and required a fresh
`robot_stop` followed by a fresh current intent.

`fault-matrix-v1.json` is the compact machine-readable evidence. It records
monotonic injection, detection, safe-command, observed-motion-stop, and recovery
times for camera/ToF/perception, neural runtime, decoder, IPC, robotd, and full
simulator failures.

## Runtime identity

- Execution target: Thor (`jetsonthor01`)
- Source exercised: `30b75a0036a4485406923dc390d8a0802b9703c8`
- MicroDuck: `344925c9f8fa031f85428a305b1e8ec2eaae29c1`
- microduck_rl: `cb70b792312d559a4da09064d92009079671815f`
- Python: 3.12.3
- steering yaw sign: `-1`
- stop transport: `robot_stop`
- frozen perception/neural/behavior TTL: 100 ms each

The frozen-neural case produced a real `stale_neural` watchdog transition, and
the frozen decoder produced `nonmonotonic_behavior`; raw propagation records
identify every injected component. The bounded IPC read timeout was about
150 ms. Full simulator restart
latency includes the official scoped `duck-sim down` and complete `duck-sim`
startup/stand lifecycle; it is not a watchdog latency.

## Tests

Thor Python 3.12 ran the directly relevant P4/P5/P6 and schema regressions:
`419 passed in 5.51s`. Four unrelated data-evidence modules requiring optional
`pyarrow` were excluded at collection; they are outside the P6 controller,
safety, IPC, scheduler, and telemetry regression scope. The new fault evidence
schema tests separately passed `8 passed in 0.02s` on final source.

## Retained raw artifacts

Artifacts remain on Thor under
`/home/juper007/projects/microduck-connectome-thor/evidence/p6-06/20260919T-p606-v12`.

| Artifact | SHA256 |
|---|---|
| `fault-events.jsonl` | `452a270f93d2059283adbf2fc38c8523cae68ef43e7f0e2fa97ee6214e23766e` |
| `fault-matrix.json` | `cb0a90aef8c3420ea6da02b0e6f38aaa70ca35214d96e381373da034e7d54a9d` |
| `fixture.log` | `bbfe3e6721d48956dd3baaff0ce2298486074d292bfd22c469cc9f191919804f` |
| `python312-tests.log` | `6b136d468dfe7f3cdc168533b0b70ddf442f49c1943892cc6634b6a2fe575613` |

The large fixture log duplicates the compact matrix on stdout and is retained
externally. No credentials, tokens, or machine secrets are present.

## Scope

This evidence proves Phase-6 fault convergence and fresh-state recovery in the
official simulator. It does not claim a Phase-7 behavior success rate or any
physical-hardware readiness.
