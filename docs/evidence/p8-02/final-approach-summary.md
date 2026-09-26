# P8-02 official final approach evidence

Status: **P8-02 protocol gate FAIL**, despite the later batch and raw scorer reporting 20/20 PASS. Independent post-execution review found that earlier ID-assigned A00–A06 attempts used an operator-selected wrong upstream checkout, outside the frozen protocol's permitted exogenous pre-arm retry categories; the aborted batch also lacks its required journal and JSON manifest. This is the preregistered P8-V2 final approach matrix on Thor official duck-sim, robotd and MuJoCo, using Python 3.12.3. Execution source was clean, independently preflight-reviewed commit `f24e3a4a3a24ac83b4c044376e9ac747ee4e32dd`; its task base was `1279e67aa17c21cf24884207fc6550a2240e2de8`. The exact protocol is `config/p8_v2_final_protocol_v1.json` (PR #70). No controller, graph, decoder, boundary or safety threshold was changed after the preflight review.

## Fixed-denominator result

| Measure | Result |
| --- | ---: |
| Planned A00–A19, seeds 880000–880019 | 20/20 completed |
| Healthy causal neural stops with first request before 0.25 m | **20/20 (100%)**; gate ≥19/20 |
| Wilson 95% interval for approach success | 0.8389–1.0000 |
| Safety-limit violations | **0** across all 20 |
| Raw files accounted and per-ID raw/summary agreement | 20/20 |
| Pose-confirmed stop before evaluator boundary, secondary | **11/20** |
| Minimum decoder-stop / first stop-request boundary margin | +0.06644 m / +0.06502 m |
| Minimum pose-confirmed-stop boundary margin | **−0.08156 m** |
| Maximum final stop-ACK-to-pose-confirmation tail | 22.56 ms; limit 100 ms |

The 0.25 m center-distance threshold is an evaluator boundary around a synthetic RGB sphere, not a MuJoCo contact or physical collision observation. Nine trials crossed it during deceleration after a healthy preboundary neural trigger and stop request. This result supports the frozen primary trigger/request gate; it does **not** show that every body stopped before the boundary. The 20-trial interval is wide and does not establish topology superiority.

| Latency, ms | Median | Nearest-rank p95 | Maximum |
| --- | ---: | ---: | ---: |
| First positive looming → healthy neural stop | 80.164 | 80.183 | 80.195 |
| Neural stop → first stop request | 6.153 | 6.664 | 6.689 |
| Neural stop → first stop ACK | 6.354 | 6.884 | 7.036 |
| First stop ACK → pose-confirmed stop | 730.108 | 742.550 | 743.899 |
| First positive looming → pose-confirmed stop | 813.604 | 826.456 | 827.099 |

## Raw evidence and attempt accounting

The immutable Thor raw directory is `/home/juper007/projects/microduck-connectome-thor/evidence/p8-v2-final/p8-02-approach-v1/`. Its [batch summary](final-approach-batch-summary.json), [raw-derived score](final-approach-score.json), [205-file manifest](final-approach-raw-manifest.json), and [final port/socket probe](final-approach-state-probe.json) are copied here byte-for-byte. The manifest covers 4,798,923 bytes and 38,461 newline records. SHA256 respectively: `82895ba8e95a19408d53e912d8f146f7070c4fa482a5468d4dcb050e029089a4`, `8c109f60519affd5b7a8448d2e0affa882e4c42dd2f8dd37f208123ad8001688`, `f4beea2bb399dbdbdec3258b5fbf8320e405c394fc26d6b6f3111e0474ef2c23`, `e6b24855b191366309950f7698bfa44ce183578dcabe4a80357c5120bfd82993`. The final simulator down and state probe report success, no connectable robotd socket and no body-port listener.

One initial command failed on Python import before output creation or simulator startup. A subsequent batch used the wrong `microduck_rl` path and attempted A00–A07 **before neural arm**; A00–A06 trial logs identify an upstream commit mismatch, and A07 was interrupted during setup. None produced a trial summary or armed neural sequence. Their complete files remain at `/home/juper007/projects/microduck-connectome-thor/evidence/p8-v2-final/p8-02-approach-v1-prearm-abort-1/` with [SHA256 list](prearm-abort-1-sha256.txt), hash `4447069db1d15ce1d2a280bf3354a122ef15c115fd8b673a1df30ec13f39d57e`. The pinned upstream checkout `microduck_rl` at `cb70b792312d559a4da09064d92009079671815f` was then used. A00–A07 each had one same-seed retry; A08–A19 had one attempt. All 20 armed attempts remain in the mechanical denominator, with no replacement seed. **These retries do not satisfy the frozen validity rule**: wrong upstream path is an operator configuration error, not an exogenous simulator/IPC/fixture acquisition failure. The aborted folder has no contemporaneous `batch-summary.json` or JSON raw manifest; the SHA256 list verifies bytes but cannot repair that missing accounting.

## Validation and next gate

Thor Python 3.12 ran 26 relevant tests before final seeds. The official batch, raw scorer, per-ID agreement and final shutdown probe all report PASS. Independent post-execution review rehashed all 205 healthy-batch files and 39 aborted-attempt files, reran the scorer on the clean Thor source, and found no mechanical causal or safety failure in the healthy batch. It nevertheless gave **FAIL** on the prospective retry/accounting rules at execution source `f24e3a4a3a24ac83b4c044376e9ac747ee4e32dd`. This evidence remains negative; P8-03 and P8-04 have not run. A separately preregistered P8-02 remediation needs unused final seeds without lowering thresholds or erasing these attempts.
