---
task_id: P8-V2-FAULT-STOP-PROBE
owner_skill: robot-safety-engineer
support_skills: [perception-sensory-encoder, microduck-integration-engineer, behavior-control-engineer, neural-runtime-engineer, reproducibility-devops-engineer, experiment-evaluation-scientist]
base_origin_main: 34b48af891c508f83bf50eb9f8accd1f0a57bd22
branch: test/p8-v2-fault-stop-probe
worktree: C:\projects\Microduck_connectome\.worktrees\p8-v2-fault-stop-probe
phase: Phase 8 development probe before P8-v2 preregistration
---

# P8-v2 moving-body fault-stop development probe

P8-v2 must freeze sensor-loss and degraded-input safe-state deadlines before
the final P8-04 matrix. Current invalid/stale fused frames produce empty neural
stimulation but do not necessarily stop an already moving robot. A thrown
neural or perception worker exception currently ends the scheduler and may
attempt only one shutdown stop. This task tests and, if needed, remediates
that fault path without counting development runs as final P8-04 evidence.

## Inputs and constraints

- Base and isolated worktree above; canonical graph-v2 SHA256
  `c4160c42941163079b6b569d117bf67afcf8b45eaa128c444f7c96c2567593cc`.
- Preserve frozen graph/population identities, decoder, SafetyClamp limits,
  Watchdog TTL 100 ms, control 50 Hz, `robot.stop` transport, and 500 ms robotd
  deadman. MaleCNS selects intent; robotd retains motor ownership.
- Inspect only relevant compositor/mapper, sparse runtime, scheduler,
  SafetyClamp, Watchdog, RobotMotionAdapter, and G8-R5d evidence first.
- Use development-only seeds outside P8-v2 final ranges 880000–883020.
  Every attempt and raw artifact must be retained, including negative probes.
- Coordinate official Thor simulator use with P8-V2-EARLY-TRIGGER-PROBE; keep
  source work in this separate worktree and run official instances serially
  unless isolation/resource safety is proven.

## Required development evidence

1. Define an explicit, irreversible per-trial source-health or watchdog fault
   latch with reason, detection time, last healthy sensor/neural times, and
   priority over a later fresh neural intent. Planned injected malformed,
   duplicate/stale, NaN/Inf and dropout faults must be contained and
   attributed; unexpected scheduler exceptions retain traceback and count.
2. Route fault stops through authentic SafetyClamp/Watchdog/RobotMotionAdapter
   high-level interfaces. Do not fabricate a WatchdogOutput or call direct
   servo commands. A stop is `robot.stop`; no post-stop `robot.move`.
3. Prove repeated acknowledged stop requests with gap ≤100 ms until official
   pose speed ≤0.008 m/s sustained 200 ms. Log applied vx decline, deadman
   attribution, limiter events, bounds, scheduler exceptions and cleanup.
4. Start with moving-body camera loss, ToF-only loss, both loss, malformed
   frame, nonfinite feature, stale/frozen neural update, and unexpected worker
   error. IPC outage/restart cannot promise ACK during disconnection; classify
   no-move/deadman/reconnect-fresh-safe-stop separately and never call it a
   healthy neural stop.
5. Use deterministic unit/component race/fault tests before official Thor
   probes. Record observed fault→stop request/ACK/pose deadlines for the P8-v2
   scientist to freeze. If continuous safe refresh is infeasible, retain FAIL
   evidence and identify separate remediation; do not lower acceptance.

## Completion and handoff

This probe is not P8-04 final evidence. Versioned source/config, all raw paths,
bytes/records/SHA256, exact input SHA, commands, tests, negative attempts,
simulator cleanup, safety violations, source attribution, limitations and
recommended preregistered fault deadlines are required. Any PASS code/evidence
PR needs an independent exact-head review, a fresh-main check, and merge before
the final P8-v2 protocol can use its implementation as authority.
