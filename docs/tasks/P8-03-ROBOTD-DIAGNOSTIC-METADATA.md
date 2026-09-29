# Task packet: P8-03 robotd diagnostic metadata

```yaml
task_id: P8-03-ROBOTD-DIAGNOSTIC-METADATA
phase: 8
title: Add command-generation and tick lineage to pinned robotd diagnostic output
owner_skill: microduck-integration-engineer
reviewer_skill: independent-phase-reviewer
base:
  connectome_origin_main: 57161251c63be912a002d236d18e7c13cd48b1cc
  microduck_pinned_commit: 344925c9f8fa031f85428a305b1e8ec2eaae29c1
  decision: docs/decisions/P8-03-PRECONDITION-CAUSAL-STATE-DECISION.md
goal: >-
  Make each acknowledged robot.move identifiable in the control tick and
  robot.state frame that consumed it, without changing motor-control behavior.
read_first:
  - docs/decisions/P8-03-PRECONDITION-CAUSAL-STATE-DECISION.md
  - config/versions.json
  - pinned microduck robotd/src/main.rs handler, dispatch, control loop and frame assembly
  - pinned microduck robotd/src/intents.rs twist storage and snapshot
  - pinned microduck duck-ipc-proto/src/lib.rs intent result and state schema
  - microduck_connectome/robotd_client.py state subscription path
do_not_preload:
  - MaleCNS datasets or literature
  - unrelated P8 behavioral ledgers
  - full repository docs tree
outputs:
  - minimal versioned upstream MicroDuck diagnostic patch or proposed upstream PR
  - corresponding pinned-version and protocol/client change proposal
  - concurrency, stream-continuity, safety, and compatibility tests
  - exact-source and protocol schema hashes in a handoff record
context_budget: '<25K input tokens target; expand only for relevant upstream dependencies'
reasoning_effort: medium
```

## Contract and acceptance

Implement the exact additive metadata contract in the decision record: a linearizable, process-wide move generation for every twist mutation; the generation in accepted request-form `robot.move` ACKs; and coherent `consumed_move_generation` plus `control_tick_sequence` in each `robot.state`. Keep `t_ns` as the sensor-read `CLOCK_MONOTONIC` timestamp. Every published frame must carry the generation actually loaded by that tick, including deadman-limited and coasted ticks. Never infer generation from velocity equality or the client-local JSON-RPC ID.

The diagnostic subscriber must start before acquisition, receive an un-decimated stream, retain every delivered frame, and fail closed on missing tick sequence, lag, reconnect, malformed state, source timestamp regression, or unproven clock/freshness. Update the client so it does not replace its subscription on every read. A separate prospective precondition implementation will decide how to use the metadata; this task must not change the moving-body gate.

Tests must cover concurrent writers and generation publication order; request ACK before and after a control tick; a frame created before a move but delivered after ACK; a tick consuming the accepted generation; identical-velocity supersession; a genuine post-command deadman/fault frame followed by clean motion; stale/coasted `t_ns`; dropped/decimated notifications; and old-client additive protocol compatibility. Verify that robotd retains motor authority, the 50 Hz loop and safety gate are unchanged, and high-level motion is the only project control interface. Record the pinned upstream commit and new candidate commit; independently review the exact final diff and protocol evidence.

**Stop boundary:** no Thor P8 timing probe, new probe IDs, behavioral development, final P8 IDs, or P8-04. After this metadata is independently validated, create a separate reviewed prospective moving-precondition task that preserves at least 1.5 s of 20 ms commands from the first proven consumed positive move, plus the frozen speed, displacement, freshness, no-deadman, and safety requirements. Historical `TPR2A-001` remains unresolved FAIL evidence.
