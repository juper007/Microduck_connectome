# P8-03-R4 actuator/pose diagnostic protocol v1

This is a separately versioned **development-only** diagnostic. It starts
from freshly fetched `origin/main`
`57161251c63be912a002d236d18e7c13cd48b1cc` on branch
`codex/p8-03-r4-actuator-pose`. PRs #80, #81, and #82 and the R1/R3 evidence
Releases remain terminal FAIL and unchanged. No P8-03 final static/receding
seed, 60-reset qualification, controller/graph/decoder change, correction
strategy, or Phase 9 work is eligible in R4. The P8 scientific criteria,
0.08 rad final reset tolerance, R2 0.06 rad guard, 0.01 m command-induced
planar bound, and yaw detection floor are frozen.

## Frozen development matrix and hypotheses

The single-use IDs A00–A29 carry unused development labels/seeds
888100–888129. Six five-reset blocks use:

| Block parity | Frozen order |
| --- | --- |
| Even | sham, positive_low, negative_low, positive_high, negative_high |
| Odd | sham, negative_low, positive_low, negative_high, positive_high |

Sham uses five 20-ms zero-yaw ticks in even blocks and eight in odd blocks.
Active low uses five ticks (0.10 s); active high uses eight ticks (0.16 s).
Both use `vx=vy=0` and `|vyaw|=0.2 rad/s` via official high-level
`robot.move`, refreshed at 50 Hz, followed immediately by an acknowledged
`robot.stop`. The end-to-end stop ACK deadline is 0.20 s and the accepted
command-through-stop window at most 0.30 s; even that worst accepted window
requests at most 0.06 rad of yaw, below the frozen 0.08 rad integral bound.
The robotd deadman TTL is 100 ms. No response-dependent command, dose,
duration, retry, or seed replacement is permitted.

The primary response is wrapped final post-stop plateau heading median minus
initial plateau median. The fixed detection floor is
`F=max(0.005 rad, max(abs(sham settled response)) + 0.002 rad)`.
No final sign inference is made until all six sham resets are valid.
For diagnosis, each of the four active cells requires 6/6 valid responses
with signed response strictly above F. This is a short-pulse diagnostic
criterion, not evidence of correction reliability or P8 efficacy.
`INCONCLUSIVE` means the signed magnitude is within ±F;
`WRONG_SIGN` means it is below −F; `SAFETY_ABORT` is separate from both.
Valid weak or wrong-sign results remain in the matrix. Any safety, timing,
storage, stale-state, ACK, cleanup, or raw-integrity breach stops the entire
matrix after the current reset's stop/down/probe; all later IDs stay PENDING.
There is no early PASS.

Separate preregistered phase metrics are during-pulse heading delta,
first-100-ms post-stop delta, post-stop heading extrema/rebound, signed
integral of applied `vyaw`, x/y trajectory and peak planar displacement,
final signed lateral displacement, `limited_by`, and policy transition
timing. These distinguish a weak dose from wrong sign, a pulse response from
a stop transient, transport/clamp from body response, and translation
coupling by sign/dose. Dose order favors lower exposure before higher
exposure within each block; dose comparisons are descriptive because this
order is not randomized.

## Write-before-evaluate safety path

Every official body read yields a raw `samples.jsonl` pose record with its
raw packet text, request/response monotonic timestamps, simulator time,
x/y/z, quaternion, yaw, roll/pitch, global sample index, phase, displacement
from reset start, wrapped heading delta, latest requested/applied robotd
velocities, `limited_by`, policy state, robotd safety state and timestamp,
latest bounded `robot.health` snapshot and timestamp, and last command ACK.
The runner appends and **fsyncs** that record before evaluating freshness,
attitude, reference pose, or the 0.01 m planar bound. A repeated simulator
packet is also logged before a bounded fresh-read retry. If the bound is
crossed, the retained record is the exact trigger. No further yaw command is
issued. The runner calls `robot.stop` immediately; the fault verdict then
names the trigger and previous sample IDs, measured value, threshold, and
active command duration. It retains stop ACK/latency, official down, and final
socket/port probe. A torn raw line or failed fsync makes evidence FAIL.

The same pinned official MicroDuck, microduck_rl, model-1250 walk policy, and
graph hashes as R3 are required. Fresh SIT down/up, walk-policy readback,
advancing simulator and robotd clocks, nondegraded health, ≤100-ms pose/state
and health age, initial x/y within ±0.03 m, z within ±0.025 m, heading within
0.35 rad of the frozen reference, roll/pitch within ±0.5 rad, x/y motion
within 0.01 m of the reset start, stopped applied velocity ≤0.005, and
21×50-ms plateau heading drift ≤0.005 rad remain enforced. The 0.35-rad
diagnostic inclusion is not a final reset qualification.

## Thor and release handoff

Use exact reviewed clean source at
`/home/juper007/projects/microduck-connectome-thor/p8-03-r4-diagnostic-source`.
Before launch verify pinned upstream/material hashes, Python 3.12, idle
`/tmp/p8-03-r4-diagnostic-state`, port 7900, no residual simulator/robotd,
and unused output
`/home/juper007/projects/microduck-connectome-thor/evidence/p8-v2-final/p8-03-r4-diagnostic-v1`.
The only executable matrix command is:

```bash
PYTHONDONTWRITEBYTECODE=1 python3.12 -m scripts.p8_03_r4_actuator_pose --output /home/juper007/projects/microduck-connectome-thor/evidence/p8-v2-final/p8-03-r4-diagnostic-v1 --reviewed-head <exact-reviewed-sha>
```

Publish one versioned GitHub Release
`p8-03-r4-actuator-pose-evidence-v1` even on FAIL. Stage the complete
manifested asset as a draft, enable repository release immutability before
publishing, publish once, and verify `immutable=true`. Fresh-download the
asset, compare SHA256/bytes and full raw inventory, rerun the scorer on the
download, reconstruct every threshold trigger from raw pose rows, and obtain
independent exact-head/evidence review. If GitHub cannot enforce
immutability, report that limitation and do not call the Release immutable.
