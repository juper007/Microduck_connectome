# P8-03 R2 prearm motion ACK remediation v1

Task: `P8-03-R2-PREARM-MOTION-ACK-REMEDIATION`. Base: fetched
`origin/main` `57161251c63be912a002d236d18e7c13cd48b1cc`, stacked on
reviewed/executed PR #91 head `9b2502c06afebe698a78b491644b3b3052bc64d9`.
The immutable TPR2-001 failure package is the
`p8-03-r2-timing-probe-v1-prearm-fail-evidence-v1` Release, archive SHA-256
`47bce0fed447d065025090792c7a044c98d833a9c2001a1cf2855cf12de4012b`.

## Diagnosis before new execution

TPR2-001 stopped before a durable arm marker or scored interval. Its 18
acknowledged prearm move calls took 0.122–0.723 ms. The next move's ACK crossed
its 20 ms slot boundary, but the coordinator returned before recording that
request. **ACK root cause class: L (unresolved), with K (instrumentation
missing).** The real prearm graph call held the stop arbiter lock for 10.580 ms
and overlapped the failed slot, making H (lock contention) plausible, not
proven. The existing move command has its own robotd `JsonLines` socket;
robotd state, health, and body pose use separate clients. Shared observation
socket use is not supported as this failure's cause.

The ACK-before-next-slot rule remains unchanged. It protects one outstanding
request, 20 ms command continuity, and the existing deadman/stop ordering. A
send-deadline-only pass rule would be a new safety and scientific contract and
is not used here. The trial continues to use official `robot.move` through
the stop arbiter and robotd; no direct actuator path exists.

## Causal change and measurement

For each v2 motion slot, the coordinator synchronously records and fsyncs a
request-start row before dispatch and an outcome row before deciding whether
the ACK met the deadline. Both rows and a matching `motion_attempt` timing row
survive late ACKs and ordinary exceptions. The trace includes scheduled and
next deadlines, worker wake, request ID, prior ACK, queue depths, thread ID,
command-lock and arbiter-lock wait, write, flush, response wait/first byte,
parse, ACK, timeout, and failure reason. A missing terminal or unmatched row
fails the offline score. Client-only timing cannot distinguish robotd
processing from blocked response delivery; that interval remains class L
unless further server evidence exists. No timing is fabricated for unobserved
first bytes or never-returning requests.

The prearm neural prime now waits for a *new genuine motion ACK* after its
perception work, then begins immediately. This phase alignment gives the
arbiter-held compute the maximum available time before the next 20 ms move
deadline. It does not move compute outside the arbiter lock, change the stop
latch order, relax ACK rules, or alter the graph/controller/decoder. If the
prime or RPC still exceeds the deadline, the probe fails and retains the
completed failure row. This is one measured candidate, not a feasibility
claim.

Fresh labels `TPR2A-001..003` are unique labels, not RNG seeds. They use
versioned config `p8_03_timing_probe_v2.json`, isolated state/port/output,
and the original three-ID timing scorer's 50 neural, 50 control, 50 acknowledged
motion, 20 visual, safety and 1,000 ms criteria. TPR2-001..003 are not retried.
The first failed new attempt stops the batch; if it reaches arm, the complete
scored second is collected. Publish a PASS or FAIL package, fresh-download,
verify all hashes/rows, and obtain independent evidence review. No behavioral
development matrix, final P8 IDs, or P8-04 may follow in this task.

Exact implementation head, local validation, independent pre-execution review,
Thor observations, and Release identity are recorded in the PR and evidence
package after they exist.
