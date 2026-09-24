# P6-07 Thor closed-loop soak evidence

## Result and scope

The official Thor `robotd` and headless MuJoCo ran the Phase-6 controller for
**605.178641459 monotonic wall-clock seconds**, from
`2026-09-24T18:45:00Z` to `2026-09-24T18:55:05Z`. The runtime summary reports
PASS. Its source commit was `d05d58ea80591f0bdc7a58454658ee7bef4bc34d`
and the soak fixture SHA256 was
`90368b73c6ec073142f52b5e6745a4af069f252cee963c90a04a23bb1747bf1c`.
Pinned upstream commits were MicroDuck
`344925c9f8fa031f85428a305b1e8ec2eaae29c1` and microduck_rl
`cb70b792312d559a4da09064d92009079671815f`. The graph cache key was
`340f6a3180026f6c61f19ebc016ae8610ec9f4a07af2af589e4d6d89e5b31f70`.

The run used deterministic camera/ToF frames through PerceptionPipeline,
PerceptionCompositor, SensoryMapper, MaleCNS runtime, DN aggregation,
SteeringDecoder, EscapeDecoder, SafetyClamp, ControllerWatchdog, the 50 Hz
scheduler, sealed motion adapter, official high-level `robotd` IPC, and MuJoCo.
The six repeated states were neutral, left, right, center, stop, and sensor
loss. The stop state is an explicitly labeled engineering stop intent inserted
before SafetyClamp; sensor loss makes the camera source invalid and passes
zero sensory stimulation through the runtime. The frozen transport remained
`robot_stop`, and steering sign remained `-1`.

## Measured outcome

| Metric | Thor observation |
|---|---:|
| Wall-clock duration | 605.178641459 s |
| Perception / neural updates | 15,126 / 30,251 |
| Watchdog ticks / robot commands | 30,251 / 30,252 |
| Watchdog rate | 50.00145 Hz |
| Stale events / faults / reconnects | 0 / 0 / 0 |
| Stop commands | 5,001 |
| Max absolute vx / vy / vyaw | 0 / 0 / 0 |
| NaN / Inf | 0 / 0 |
| Safety interventions / violations | 5,000 / 0 |
| Watchdog stalls / scheduler exceptions / IPC errors | 0 / 0 / 0 |
| Telemetry records / sequence gaps | 30,252 / 0 |
| Watchdog period p50 / p95 / p99 | 19.999 / 20.043 / 20.117 ms |
| Jitter p95 / processing latency p95 | 0.022 / 0.163 ms |

All 30,252 records carry the sensor/perception, stimulus, runtime, DN,
decoder, safety, watchdog, official command, post-command `robot.state`, and
MuJoCo heading stages. They are strictly ordered and have no missing command
sequence. The final official `robotd` health query was healthy at approximately
50 Hz, with zero missed control-loop ticks. An independent streaming verifier
at `scripts/verify_p6_soak.py` checks the raw trace against the summary,
including post-command state, requested twist, sensor-loss neutrality, stop
transport, bounds, sequence continuity, wall-clock duration, size and hash. It
reported PASS with zero mismatches across all 30,252 records.

The pinned graph produces zero robot-facing motion under natural perception
inputs, as already reported in P6-05. This soak therefore verifies sustained
integration and safety while stationary. It does **not** demonstrate natural
target steering, looming behavior, or physical-hardware readiness. P6-06
separately exercised moving pre-fault robot state using a labeled synthetic
DNa02 runtime current.

## Retained Thor artifacts

Raw artifacts remain under
`/home/juper007/projects/microduck-connectome-thor/evidence/p6-07/20260924T-p607-soak-v1`.
The summary in this repository is byte-identical to the Thor file.

| Artifact | Bytes | SHA256 |
|---|---:|---|
| `telemetry.jsonl` | 90,057,517 | `eb851e4e53d750900ebfbed7da956bd8ac91916a14903815b914d4e60a9ff549` |
| `soak-summary.json` | 6,351 | `8f20b0d5f5555e183cc81543ddabf2730e7a452b23df93e0ecd8c1e0c2acc5fe` |
| `fixture.log` | 314 | `a8e491d1ad2a362875d288411b2d81ef1d7f4ac43e8a8c4b4484b43ba1a62bf7` |
| `python312-tests.log` | 334 | `b0f8e0c6a361934cfaddd1e27ad45b127ec265cbe74ef13c2bc33c08817dc297` |
| `verification.log` | 384 | `6d7723a33bc3372834c28c1d873228b777d4e17085012c761a11360d41ef9db3` |

Thor Python 3.12 relevant P4/P5/P6 safety, integration, telemetry, and soak
regressions: **209 passed, 26 subtests passed in 3.74 s**.

Independent final-head P6-07 review is pending.
