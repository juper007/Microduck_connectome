# P8-03 R2 prearm moving precondition v3 checkpoint

Task: `P8-03-R2-PREARM-MOVING-PRECONDITION-V3`. Fetched `origin/main` base
`57161251c63be912a002d236d18e7c13cd48b1cc`; stacked on PR #92 exact
reviewed/executed head `03c71db1b38e6da1fca6b9c5eb8b110d50339889`.
The historical `TPR2A-001` failure Release
`p8-03-r2-prearm-ack-probe-v2-evidence` (archive SHA-256
`d92cac14efca4fdec5323f651c29af1613cdf0143827d11fed64f6e3f6124574`)
is immutable.

## Causal checkpoint before new IDs

**PRECONDITION_FAILURE_CLASS = UNRESOLVED. REMEDIATION_ELIGIBLE = NO.**
The first positive `robot.move` ACK was accepted at host monotonic
`259875384560760`. The first state later received by the host at
`259875385566602` reported applied `[0,0,0]` and `limited_by=["deadman"]`,
but its robotd source `t_ns=259875383416176` is 1.145 ms **before** the ACK.
The last retained pre-move transition state was received at
`259875364668757`; its source `t_ns`, requested velocity, limiter and raw
notification were not retained. The first move's call/write/flush timestamps
and request ID were also not retained. The sampler's `after(ack_ns)` only
proves host receive ordering. It cannot prove that this state reflects the
acknowledged command. Nor can source-before-ACK alone prove staleness, because
robotd could have applied the command before sending its ACK. The next state
had source `t_ns=259875403160983`, applied vx `0.014`, and no limiter; later
clean movement cannot retroactively classify or erase the first row.

The [local-reference protocol](P8-03-LOCAL-REFERENCE-PROTOCOL-V1.md) requires
a sustained, fresh, positive moving body before arm with no deadman/fault
contamination. It does not explicitly require the first acquisition readback
after the first ACK to be clean. The existing `precondition_deadman_after_motion`
helper recognizes that an initial readback may reflect pre-move state.
Nevertheless the current trial's separate `any(deadman)` check across all
75 acquisition rows rejected TPR2A-001. The archive cannot establish whether
that first state was stale pre-command, transitional post-command, or a fresh
genuine deadman state. A qualification-window clarification cannot be applied
to this historical evidence or prospectively executed on these facts alone.

No no-deadman, speed, displacement, freshness, safety, ACK, cadence, window,
or behavioral threshold changes are authorized. No `TPR2A` ID is retried; no
new labels are allocated; no v3 Thor timing probe runs at this checkpoint.
The PR #92 dedicated motion socket, durable ACK rows and next-deadline rule
remain in place.

## Independent evidence defect

The v2 trial aborted before the motion coordinator was created. Finalization
then attempted to hash the nonexistent `motion-request-journal.jsonl`, raised
`FileNotFoundError`, and omitted `summary.json`. The raw events still retain
the primary moving-body failure and safe stop. The v3 code fix records the
coordinator journal as `OPTIONAL_NOT_REACHED_ARTIFACT` when lifecycle evidence
proves the coordinator was never reached, while a missing journal after
coordinator start is `REQUIRED_BUT_MISSING_ARTIFACT`. Neither path fabricates
a journal or turns a failed trial into PASS. The primary fixture error must
remain in the durable summary and the official down/state probe remains
required by the batch scorer.

Prospective diagnostic lineage work records every parsed state notification,
source and receive timestamps, observation order, command request and ACK
spans, and a conservative `TRANSIENT` classification until command causality
can be established. A selected post-ACK readback also gets a linked diagnostic
decision. Every notification received during acquisition is checked for
deadman, fault, or safety contamination, including notifications superseded by
a later clean readback. This closes a state-selection gap while leaving the
moving-body thresholds and no-deadman rule unchanged. It does not reinterpret
`TPR2A-001`.

After exact-head review, this task stops at the unresolved causal checkpoint.
A separate architecture decision must establish a defensible causal state
rule from new, independently reviewed evidence before fresh probe labels or
execution can be authorized.
