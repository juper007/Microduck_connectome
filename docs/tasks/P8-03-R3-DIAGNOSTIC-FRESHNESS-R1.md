# P8-03 R3 diagnostic freshness R1

Development-only remediation. Parent PR #97 exact executed head
`7e537b84e021877111e89b6b59a12cc34a18ad54`; fetched
`origin/main` base `57161251c63be912a002d236d18e7c13cd48b1cc`.
The pinned MicroDuck source remains `344925c9f8fa031f85428a305b1e8ec2eaae29c1`
plus reviewed patch SHA-256
`828ff2619ee378d4fe49fe358944dcc9b5aa9b6583e7aef1afe43a353411655a`,
reproduced on Thor as `d6553c7364bd50af2a24ee96d8bf9f70cadd076a`.
No robotd code, command behavior, or control thresholds change here.

## Immutable CTP3-001

The historical evidence archive SHA-256 is
`c0da531975af99444090d33560a0836b05829e88f6326259e5ba7e17fb13f72d`.
All 20 package-manifest member hashes matched. CTP3-001 remains terminal
prearm FAIL. Its release/archive were not changed. CTP3-002/003 are unused.

The ledger contains six raw wires, six parsed states, and one failure record.
Ticks 483–488 are contiguous; consumed generation is zero. The sixth parsed
state was recorded before the validator threw "diagnostic state source
timestamp is not fresh." The failing check's timestamp and any seventh
state are not in the ledger. The source `t_ns` increments on these six ticks;
coasting does not explain this failure.

| Tick | Source to raw callback (ms) | Raw callback to state callback (ms) | Source to state callback (ms) |
| --- | ---: | ---: | ---: |
| 483 | 1.717 | 1.212 | 2.928 |
| 484 | 22.882 | 11.887 | 34.769 |
| 485 | 37.951 | 16.906 | 54.856 |
| 486 | 55.636 | 11.602 | 67.237 |
| 487 | 68.937 | 11.299 | 80.236 |
| 488 | 82.921 | 11.201 | 94.122 |

`received_at_ns` in the old wire row is sampled inside `on_raw` after a
complete line is removed from the reader buffer. The old state row timestamp
is sampled in `on_frame` after raw-row JSON serialization, write, flush,
and fsync. Neither timestamp is the socket `recv` timestamp. Thus the
requested decompositions are:

| Interval | CTP3-001 availability |
| --- | --- |
| SOURCE_TO_SOCKET_MS | unavailable: socket receive timestamp absent |
| SOCKET_TO_READ_MS | unavailable: socket receive and line-available timestamps absent |
| READ_TO_PARSE_MS | unavailable separately: raw-to-state callback includes raw recorder work and parsing |
| PARSE_TO_RECORD_MS | unavailable: parser end and recorder start absent |
| RECORD_TO_VALIDATE_MS | unavailable: write/fsync and validator timestamps absent |
| TOTAL_SOURCE_AGE_MS at validation | unavailable; state callback ages above are lower bounds |

The line-observation age rose by roughly one tick each delivery. This proves
consumer-side accumulation by the raw-callback boundary, but the archive does
not identify how much occurred at robotd, in the kernel socket buffer, or in
Python scheduling. The old client then performed a second fsync before
checking freshness. The code path proves this work could move a valid
observation past 100 ms, but the archive does not timestamp that fsync.

## Root-cause classification

| Candidate | Classification | Basis |
| --- | --- | --- |
| A robotd state old when delivered | UNRESOLVED | source to socket unavailable |
| B socket receive backlog | UNRESOLVED | socket receive unavailable |
| C Python reader scheduling | UNRESOLVED | reader wake unavailable |
| D JSON parsing | UNRESOLVED | parse start/end unavailable |
| E recorder lock contention | UNRESOLVED | no historical lock timing |
| F synchronous file write | SUPPORTED | old `on_raw` and `on_frame` append synchronously |
| G per-state flush/fsync | SUPPORTED | old code fsynced twice per state |
| H callback blocking reader | SUPPORTED | old callback ran inline before next read |
| I competing P8 worker/GIL | UNRESOLVED | not measured in CTP3-001 |
| J incorrect freshness-check timestamp | SUPPORTED | old check sampled after both durable appends |
| K coasted source `t_ns` | NOT_SUPPORTED | all six recorded source timestamps advance |
| L another cause | UNRESOLVED | no additional timing evidence |

## Development-only Thor comparison

The patched robotd remained at commit `d6553c7` in an isolated simulator
state at 50 Hz. No movement or P8 trial ran. A 10 s comparison used the
same diagnostic socket protocol in three modes:

| Mode | States | Tick gaps | Source age p95/max (ms) | Callback p95/max (ms) | fsync p95/max (ms) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Reader + validation, no recorder | 501 | 0 | 2.548 / 4.418 | unavailable | unavailable |
| Reader + old synchronous recorder | 501 | 0 | 2.183 / 4.262 | 0.789 / 2.989 | 0.661 / 2.920 |
| Reader + candidate async recorder | 501 | 0 | 2.163 / 3.584 | 0.297 / 0.472 | 0.784 / 1.189 |

The old recorder used 1002 fsync calls in 10 s; the candidate used 269.
Idle comparison does not reproduce the historical >100 ms fault. It
establishes the actual recorder cost at cadence and the reader's isolation
from fsync. The failure under concurrent P8 work remains an unresolved
component of root cause.

## Freshness boundary and evidence contract

`t_ns` is the sensor-read `CLOCK_MONOTONIC` source timestamp. Freshness
means source age when the diagnostic consumer first has a complete line to
inspect. The reader samples `CLOCK_MONOTONIC` immediately upon removing
that line from its byte buffer, before raw callback, JSON parsing, state
callback, or disk work. It rejects future timestamps and ages over the frozen
`100_000_000` ns. This observation boundary includes upstream delay and
reader backlog; it excludes persistence latency, which is not sensor age
when consumed. The offline scorer uses the same timestamp in
`received_at_ns`. An independent review must accept this interpretation
before any new P8 label.

Every delivered wire is enqueued; every parsed frame retains
`control_tick_sequence`, `consumed_move_generation`, source `t_ns`, and
`reader_observed_ns`. A stale frame is retained and fails immediately.
Coasted equal `t_ns` is allowed only while its source age remains at most
100 ms; tick gaps, generation regressions, and source time regressions fail.
The live causal evaluator and offline scorer apply the same coast rule.
Every live gate reads a checkpointed, complete durable prefix; the reader
continues consuming states while a gate waits for that checkpoint.

The queue has 256 slots; one writer preserves enqueue order. It checkpoints
at 16 records or 20 ms. At most 272 records (256 queued plus up to 16 written)
can be uncommitted during healthy operation. Health checks fail closed if the
oldest uncommitted record is over 100 ms old. Full queue, writer exception,
and missing writer also fail closed. Move request and ACK evidence still use
durable barriers before their callers proceed. A successful probe drains and
fsyncs every row on close. Abnormal termination may lose the bounded
uncommitted suffix; only the fsynced prefix is recoverable, and incomplete
evidence is FAIL. The writer does not silently drop or coalesce frames.
Each barrier checks elapsed time while waiting and at completion, so a
quiet reader cannot hide an overdue fsync. The final ARM gate checks ACK,
state, pose, and health freshness again immediately before release.

This contract measures a queue limit and fail-closed detection boundary.
No software can guarantee a 100 ms fsync completion if storage hangs. Such
a hang fails the probe and may leave the uncommitted suffix.
