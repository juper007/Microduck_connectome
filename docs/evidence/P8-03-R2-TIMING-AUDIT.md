# P8-03 R2 timing and motion audit

Status: **R1 timing failure confirmed; 50 Hz feasibility after remediation unresolved.** This audit does not change the 20 Hz visual, 50 Hz neural/control, 1,000 ms window, motion, or safety requirements. No R2 trials, final P8 IDs, or P8-04 work were run.

## Provenance

- Source: [PR #89](https://github.com/juper007/Microduck_connectome/pull/89), reviewed R1 head `4a916a5c156203dd6ee60012d1ebdec6fbbcfc12`, fetched `origin/main` base `57161251c63be912a002d236d18e7c13cd48b1cc`.
- Raw: [R1 failure Release](https://github.com/juper007/Microduck_connectome/releases/tag/p8-03-local-reference-v1-r1-development-fail-evidence-v1), archive `p8-03-local-v1-r1.tar.gz`, 2,087,668 bytes, SHA256 `d60f8dae271fe024923d5a1323bbbbba8e98a99f3f76091ac39a73aecdff6112`. Fresh download matched the hash. R1's 128-entry manifest SHA256 is `690bcf3d3bd4ef1ef7ba77a5c486dd04303504b9257efa61b65c862fe099399e` and was independently verified during R1 review.
- Inspected each `development/D88940*/attempt-01/{events.jsonl,neural-ledger.jsonl,visual-frames.jsonl,summary.json}`, `development/score.json`, `scripts/p8_03_trial.py`, `scripts/p8_03_score.py`, and `microduck_connectome/scheduler.py`. Counts and intervals were independently recalculated from raw `time.monotonic_ns` timestamps. Reset IDs are labels, not RNG seeds; each has one armed attempt.
- On Windows, a portable raw-file pass matched SHA256 and byte size for all 128 manifest entries and reproduced the manifest hash. The frozen scorer and manifest CLI expect Thor's absolute source/package paths and Linux config bytes, so their complete CLIs were not rerun locally. The R1 evidence reviewer reran the scorer on Thor; this audit independently recounts the timing rows without changing its rules.

## Scored-window reconstruction

The scorer's interval is inclusive `[arm, arm + 1,000,000,000 ns]`. Each stream cell is `count:first–last` in ms from arm. V=visual, N=neural, C=control publish, M=motion refresh ACK, S=state observation retained by the motion worker. The final gap column is maximum in-window N/C/M inter-event gap in ms. Each scored end is the arm value plus 1,000,000,000 ns. No raw event lies exactly on the end boundary, so inclusive and half-open recounts agree here.

| ID | Arm ns | V | N | C | M | S | Max N/C/M gap | Missed N |
|---|---:|---|---|---|---|---|---|---:|
| D889400 | 250693337649661 | 20:0–963.8 | 37:0–966.8 | 48:56.0–996.0 | 34:43.0–991.9 | 33:55.1–989.5 | 44.3/33.8/53.8 | 12 |
| D889401 | 250709736188410 | 20:0–959.0 | 44:0–999.2 | 44:64.1–991.4 | 39:38.3–999.3 | 38:55.1–991.9 | 40.1/46.3/47.0 | 6 |
| D889402 | 250726140208178 | 20:0–958.3 | 39:0–998.8 | 47:57.6–998.4 | 34:37.8–998.7 | 33:44.1–969.6 | 40.0/40.9/60.7 | 11 |
| D889403 | 250742543995426 | 20:0–956.8 | 38:0–997.2 | 48:58.6–993.9 | 37:36.5–995.8 | 36:47.9–985.3 | 41.7/34.0/47.7 | 12 |
| D889404 | 250758974398760 | 20:0–957.5 | 34:0–996.9 | 47:56.3–989.8 | 32:36.4–989.7 | 32:56.8–996.2 | 41.8/41.3/56.0 | 17 |
| D889405 | 250775459300222 | 20:0–956.2 | 40:0–996.5 | 46:56.2–996.2 | 35:35.4–983.3 | 34:46.9–974.6 | 41.9/40.1/60.4 | 10 |
| D889406 | 250792012075835 | 20:0–955.8 | 43:0–996.1 | 47:58.3–986.5 | 41:35.1–981.8 | 41:52.1–985.4 | 47.2/41.6/50.1 | 7 |
| D889407 | 250808771593142 | 20:0–969.5 | 38:0–990.6 | 44:37.1–991.1 | 35:29.3–966.3 | 35:42.4–990.3 | 41.1/43.8/48.8 | 12 |
| D889408 | 250825420680483 | 20:0–967.7 | 46:0–988.1 | 49:39.2–998.4 | 41:27.8–987.8 | 40:43.8–986.2 | 42.0/39.7/37.4 | 4 |
| D889409 | 250842055054061 | 20:0–955.8 | 46:0–996.1 | 47:58.9–987.6 | 43:35.7–995.5 | 42:41.6–985.0 | 40.1/41.8/36.1 | 4 |

Additional per-stream timing from the same raw rows (gap in ms; `P/C` are scheduler-reported missed perception/watchdog deadlines):

| ID | Max visual gap | Max retained-state gap | Missed P/C |
|---|---:|---:|---:|
| D889400 | 63.8 | 60.1 | 14/0 |
| D889401 | 60.8 | 40.9 | 4/4 |
| D889402 | 61.1 | 64.6 | 8/1 |
| D889403 | 61.9 | 64.8 | 4/0 |
| D889404 | 63.1 | 46.9 | 10/1 |
| D889405 | 62.2 | 70.7 | 10/2 |
| D889406 | 60.0 | 53.7 | 7/1 |
| D889407 | 69.5 | 51.6 | 14/4 |
| D889408 | 67.8 | 42.4 | 6/0 |
| D889409 | 60.0 | 46.6 | 0/1 |

The neural event at offset zero is a synchronous prime. `p8_03_trial.py` records arm and starts the frozen deadline **before** synchronous perception/neural priming and worker startup. The prime returns 25.7–41.8 ms after arm; the second neural call begins 28.0–44.3 ms after arm; first control publication follows 37.1–64.1 ms after arm. The scheduler's measured lifetime is only 0.957–0.980 s, even though every `window_complete` is later than arm + 1 s. This is a real startup/accounting implementation defect, but the scorer uses the intended arm timestamp and does not miscount raw steps.

## Timing budget and classification

The 405 in-window neural calls took p50/p95/p99 **13.3/24.1/28.5 ms**, maximum **30.2 ms**; 85 exceeded the frozen 20 ms period. The 200 visual processing spans took **4.9/11.6/18.2 ms**, maximum **22.8 ms**. The 371 move RPC call-to-ACK spans took **0.2/6.2/8.0 ms**, maximum **9.5 ms**. Healthy control publishes were locally suppressed neutral outputs, so their near-zero call-to-ACK does not measure `robot.stop` latency. The scheduler summary reports **4–17 missed neural deadlines**, zero neural-step returns dropped, and zero to four missed watchdog deadlines per ID. Its neural rate is **34.0–46.4 Hz** over the shortened scheduler lifetime. Raw neural inter-step p95/max are **40.0/47.2 ms**, motion ACK inter-gap p95/max **43.6/60.7 ms**. The robotd motor loop reports approximately 50 Hz and zero missed ticks; that separate motor cadence does not establish neural cadence.

`ClosedLoopScheduler._periodic` advances absolute deadlines and explicitly skips a cycle after an overrun. Thus real late/missed cycles, plus the pre-scheduler priming interval inside the scored second, explain the missing steps. The R1 archive does not time neural-computation subspans, GIL wait, scheduler wake latency, body-read latency, queue depth, or logging duration. Maximum measured full-neural-call overrun beyond one period is 10.2 ms. Cumulative missed deadlines are 4–17 per ID; exact wake jitter and cumulative drift are not recoverable. Per-trial JSONL file writes occur after the scored window, and durable arm/progress writes before workers start. Broader system I/O contention remains unmeasured.

| Candidate | Finding | Evidence or limit |
|---|---|---|
| A scheduler below 50 Hz | SUPPORTED | 34–46 scored neural steps and 4–17 missed deadlines. |
| B blocking neural/control operation | SUPPORTED for full neural call; control cause UNRESOLVED | 85/405 neural calls >20 ms, no neural subspans. |
| C Python/GIL contention | UNRESOLVED | Concurrent Python workers, no profiler/wake trace. |
| D body/state reads block control | NOT_SUPPORTED directly; motion impact SUPPORTED | Reads are in motion/perception workers, while motion waits for post-ACK state. |
| E visual blocks neural | UNRESOLVED | Visual spans reach 22.8 ms; causal contention not measured. |
| F neural runtime computation | UNRESOLVED separately | Full neural call p95 24.1 ms includes computation, locks and bookkeeping. |
| G logging/fsync | NOT_SUPPORTED as direct scored-worker write; broader contention UNRESOLVED | Writes surround worker window; durations unrecorded. |
| H robotd RPC/ACK | NOT_SUPPORTED as dominant move-ACK cause; stop RPC UNRESOLVED | Move ACK max 9.5 ms; no healthy stop RPC. |
| I late start/window mismatch | SUPPORTED late start; mismatch NOT_SUPPORTED | Prime and startup consume 28–64 ms after arm; scorer interval matches raw arm. |
| J queue/backpressure drop | NOT_SUPPORTED for neural returns; queue depth UNRESOLVED | `dropped_neural=0`; queue counters not retained. |
| K timestamp/scorer bug | NOT_SUPPORTED | Independent raw counts match `score.json`. |
| L other implementation issue | SUPPORTED | Motion worker serially waits for state then reads body. |

The scorer currently requires at least 40 control publications despite the stated 50 Hz control target; this pre-existing contract/implementation discrepancy requires architecture clarification. It was not changed or used to make R1 pass. No scorer bug is established for the observed missing neural or motion samples.

## Motion continuity

All ten IDs have 75 precondition motion rows before arm. Within the scored second, every retained requested and applied vx is **0.070 m/s**; all 371 motion refresh ACKs are positive, and no retained state is deadman-limited. Adjacent retained poses yield median planar speed **0.083–0.119 m/s** per ID. Body movement is observed at retained samples; pauses between them and TTL expiry cannot be excluded. Seven IDs (D889400–D889405, D889407) have fewer than the frozen 40 motion-refresh samples, and the same seven have fewer than 40 retained state observations. D889406/D889408/D889409 meet those counts. No motion inter-ACK gap reaches the scorer's 100 ms maximum.

The motion worker executes `robot.move` → blocking `RobotStateSampler.after(ack)` → blocking body pose read → period wait in one thread. Its first refresh occurs 27–43 ms after arm and its observed rate is 32–43 ACKs per scored second. This supports **COMMAND_CONTINUITY_FAILURE plus STATE_OBSERVATION_GAP**, caused at least in part by the serial path. The raw events omit the full 50 Hz robotd state stream, scored `limited_by`, policy/lifecycle, TTL expiry, and body-read timing; these cannot be reconstructed for each ID. The ACK payload says `accepted: true`, and deadman is false in every retained state. **BODY_NOT_MOVING** and **SCORER_ACCOUNTING_ERROR** are not supported.

## Gate

The current implementation did not deliver the frozen 50 healthy neural/control updates in any observed Thor scored second. Physical achievability after permitted scheduling and I/O changes remains **UNRESOLVED**: moving startup before arm alone cannot remove 4–17 missed neural deadlines, and the full neural call often exceeds 20 ms. A design review should select instrumentation and a candidate causal remediation, then measure its 20 ms neural budget under concurrent visual and motion load without changing the requirements. The task's conditional architecture hard stop applies if an instrumented probe establishes that 50 Hz is infeasible; R1 alone does not establish that condition. `TIMING_PROBE=BLOCKED`; `SECOND_DEVELOPMENT_GATE=BLOCKED`; no fresh R2 development IDs were allocated. A separately versioned fresh-ID timing probe must pass before any second behavioral matrix. Final IDs and P8-04 remain untouched.
