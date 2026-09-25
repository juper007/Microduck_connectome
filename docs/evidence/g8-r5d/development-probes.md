# G8-R5d development probes

Development probes are excluded from the frozen final three-trial decision.

## Draft `aa04a69` — Thor official simulator

- One fresh-reset seed: `80101`.
- Artifact directory: `/home/juper007/projects/microduck-connectome-thor/evidence/g8-r5d/probe-aa04a69-20260925-2/`.
- Batch summary SHA256: `8b93ff5020f1a7e0ec7658b0c13e735441104980f9bbf04bf077133c050f3bac`.
- Probe result: PASS, with pre-stop pose speed 0.134154 m/s, applied vx 0.07 m/s, healthy neural first stop, 34 acknowledged official `robot.stop` calls, maximum ACK gap 20.105525 ms, no deadman limiter before confirmed stop, no post-stop `robot.move`, actual deceleration and pose-stop confirmation, `COMPLETE`, zero scheduler exceptions, zero safety violations, and safe geometry.
- Python 3.12 regression on Thor: 154 passed for G8-R5d plus watchdog, motion adapter, robotd client, and scheduler suites (`PYTHONPATH=.`).
- The probe used draft source and does not count as a final independent trial. Final source adds explicit first post-ACK robot.state deadman audit and conservative exclusion of ACKs after stopped confirmation from cadence metrics; the frozen final batch must use the later protocol commit.
