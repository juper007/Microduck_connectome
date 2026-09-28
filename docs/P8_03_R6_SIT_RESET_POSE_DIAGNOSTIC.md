# P8-03-R6: passive official SIT reset pose diagnostic

## Scope and frozen relationship

R6 is a separate **development-only** experiment after terminal R1–R5 FAIL evidence. It does not revise those PRs or Releases, pass P8-03, permit final P8 IDs, qualify resets, or begin P8-04. The frozen P8 reference and 0.03 m x/y, 0.025 m z, and 0.08 rad heading inclusion tolerances are read-only. `OUTSIDE_FINAL_ENVELOPE` is an observation and never a matrix-stopping condition. No command-based correction or reference change is eligible from R6 alone.

The 48 preregistered reset labels are `888300`–`888347`, ordered `S00`–`S47` in six blocks of eight. `RESET_ID_SEMANTICS = UNIQUE_LABEL_ONLY`; `SIMULATOR_RNG_SEEDED = NO`. The pinned official duck-sim / MuJoCo body server has no RNG seed input. These labels provide identity, order, one-attempt accounting, collision avoidance, and evidence indexing. Each label receives exactly one independent official SIT `duck-sim down` / `duck-sim up`; there is no retry or replacement.

The runner sends no `robot.move`, no yaw request, no correction command, and no `robot.enable`. Its sole robot command is an authentic, acknowledged `robot.stop` at E and for safety/cleanup. Existing robotd and policy stacks retain motor ownership.

## Checkpoints and chronology

For each reset, the runner records: A, official simulator up complete; B, official body server reachable; C, robotd reachable; D, policy loaded and read back; E, initial `robot.stop` acknowledged; F, 0.25 s settle; G, 21 samples at 0.05 s spacing and a settled median of the final five. The body and robotd servers may become reachable before `duck-sim up` exits, so chronological capture is **B, C, A, D, E, F, G**. Every checkpoint includes host monotonic and UTC timestamps; each body packet supplies simulator time, trunk x/y/z, quaternion and derived heading/roll/pitch. C–G include full robotd state, robotd time, requested/applied motion, `limited_by`, policy, safety, and health. B is body-only. The run also records command ACKs, lifecycle logs, official down probes, and pin verification. The exact event times determine interpretation; stage names alone cannot prove causality.

The append-only `samples.jsonl` is flushed and fsynced on every row before classification. Trace summaries are derived from it. The scorer reopens raw rows, checks continuity, checkpoint coverage/order, simulator clock progression, state age, lifecycle ACKs, and derived metric agreement. Each complete observed reset is classified `IN_ENVELOPE` or with one or more `OUTSIDE_X`, `OUTSIDE_Y`, `OUTSIDE_Z`, and `OUTSIDE_HEADING` flags, retaining all simultaneous flags. The primary label uses X/Y/Z/heading precedence. Failures use `DATA_INTEGRITY_FAIL`, `INFRA_FAIL`, or `SAFETY_FAIL`; the batch stops at the first genuine failure, with no result-driven retry. An out-of-envelope complete reset remains valid and the next reset proceeds.

Safety gates retain the existing stop/down response for fallen or limp robotd state, unhealthy robotd, excessive body attitude, unexpected applied motion, stale/incoherent telemetry, failed ACK, and lifecycle failure. The final inclusion envelope is **not** a safety abort. A failed or interrupted run is still published with all attempted raw evidence and a FAIL gate.

## Analysis and gate

For A–G, report min/max/mean/median/sample std of x/y/z/heading, all per-stage drifts, B-to-G evolution, consecutive reset deltas, and fraction inside the unchanged final envelope. Compare the first reachable body pose with later stages to classify simulator spawn/reset variability, robotd startup movement, policy-load movement, stop/settle movement, stale/measurement artifact, or unresolved. Stage attribution is observational; the lifecycle timing and raw requested/applied motion must be considered before claiming a cause. Record order and time trends and multimodality descriptively; R6 has no inferential authorization to alter P8 bounds.

R6 PASS means only that all 48 one-attempt resets and A–G checkpoints are present, valid, and independently scored, characterizing SIT reset variability well enough to design the next remediation. It is **not** P8-03 PASS. An incomplete or integrity-failed matrix is R6 FAIL; valid out-of-envelope resets alone do not fail the diagnostic.

## Execution and evidence

Run focused contract tests and obtain independent PASS of the exact Git head before Thor execution. On Thor use a clean checkout at that reviewed head, the pinned official MicroDuck `344925c9f8fa031f85428a305b1e8ec2eaae29c1`, pinned microduck_rl `cb70b792312d559a4da09064d92009079671815f`, Python 3.12.3, exact walking policy SHA-256 `98c3ea73fa6bb196bcf16586cf38b9fffb782787447d638fa1c1028df9082c1a`, and graph SHA-256 `c4160c42941163079b6b569d117bf67afcf8b45eaa128c444f7c96c2567593cc`. Preflight requires the official simulator down and listeners absent. The evidence root is single-use. Retain protocol, runner, standalone scorer, every attempted trace/journal/log, run status, inventory hashes, and gate. Publish a versioned GitHub Release on PASS **or** FAIL, then fresh-download and independently re-score it. Stop after R6.
