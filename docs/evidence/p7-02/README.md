# P7-02 official Thor target steering result — FAIL

## Frozen experiment and execution

P7-01 was merged at `34c8857251e14f83a9dff9697f947599781ff01e`.
P7-02 used branch `experiment/p7-02-target-steering` from that fetched main.
The final experiment, including all 100 target and 40 future no-target seeds,
class order, exclusions, response rule, and config hashes, was committed as
`bc1f6f69743953b9b4d6c4e3dd772f8c7b3b` **before** the final target batch.
The exact manifest is `config/steering_experiment_v3.json`, SHA256
`9d640e8d23305548c209077dc20b72a2c33fccdff02b04d820d816aee868caff`
on Thor. The simulator was the official MicroDuck `robotd` plus MuJoCo on
`jetsonthor01`, with pinned MicroDuck
`344925c9f8fa031f85428a305b1e8ec2eaae29c1` and `microduck_rl`
`cb70b792312d559a4da09064d92009079671815f`. The graph key was
`340f6a3180026f6c61f19ebc016ae8610ec9f4a07af2af589e4d6d89e5b31f70`.

Every trial required a successful official `duck-sim down` then `up`, a new
controller/neural runtime, healthy `robotd`, and an initial pose within the
pre-registered P7-01 reference tolerance. The target was rendered into camera
pixels using read-only MuJoCo heading. Evaluation bearing was never supplied
to perception, neural stimulation, the decoder, or `robotd`. The chain retained
P6's yaw sign `-1`, safety limits, TTLs, watchdog, sealed adapter, and
`robot.stop` transport. Versioned Phase-7 engineering choices were bounded
LC10a target drive `config/target_stimulus_drive_v3.json` and bounded decoder
gain `config/steering_decoder_p7_v1.json`; these are not biological claims.

The first sustained turn required at least `0.02 rad` heading change over
`0.2 s` with at least 80% same-sign heading increments. The first actual
MuJoCo heading response was scored against the target bearing **at the heading
sample time**, including crossing targets. No response counts as a failed
evaluated trial. Robot heading samples delayed over `100 ms` after the
associated command invalidate the trial. No failed trial was replaced.

## Result

| Measure | Final v3 result | Frozen requirement |
|---|---:|---:|
| Target trials attempted | 100 | 100 |
| Valid evaluated target trials | 96 | ≥100 |
| Correct / incorrect / no response | 0 / 0 / 96 | correct rate ≥0.90 |
| Correct-direction rate | 0.000 | ≥0.90 |
| Wilson 95% interval for correct rate | [0.000, 0.0385] | reported |
| Invalid trials | 4 | none replaced |
| Safety-limit violations | 0 | 0 |

All four invalid trials (`026`, `086`, `089`, `093`) had successful simulator
down/up exits but their initial heading or trunk height was outside the
pre-registered reset tolerance. Their trial logs retain the explicit initial
pose error. There were 48 valid left and 48 valid right trials, 33 near-center,
33 medium, and 30 far; 47 static and 49 crossing; 50 clean and 46 moderate.
Every breakdown had zero correct trials. Response-latency median/p95 are null
because no sustained response was detected.

The runner rejected each invalid initial pose before writing a trial trace.
Its error log identifies the tolerance failure, but the exact out-of-tolerance
heading and height values were not retained; this limits reset diagnosis.

The raw traces contain 14,496 correlated control records: 11,703 records with
visible target area, 2,900 with nonzero DNa02 steering readout, and 5,383 with
nonzero robot-facing yaw command. Maximum absolute robot-facing yaw command
was `0.152293215 rad/s`, within the frozen `0.50 rad/s` bound. The largest
absolute trial-end heading change was `0.027968917 rad`, but none met the
pre-registered first sustained response rule. Maximum measured command-to-body
sample delay was `23.685788 ms`, within the frozen `100 ms` limit. These
observations distinguish stimulus/readout/command activity from demonstrated
target-oriented rotation; they do not establish a cause for the weak physical
response.

## Artifact integrity

The exact batch summary is `steering-summary-v3.json` (2,193 bytes; SHA256
`4acdab4c153717af178d184ded95134ab82b8ad530659f83095b834abec07dbd`).
The full Thor artifact directory is
`/home/juper007/projects/microduck-connectome-thor/evidence/p7-02/final-target-v3-bc1f6f6`.
Its `trial-results.jsonl` is 101,221 bytes, SHA256
`7ab5aa2e4947008b0a76e8d4747dffbad222386ebcfd54c1bc4217bf83d402ad`.
Each journal row names the trial spec, reset exit codes and log hashes, trial
summary hash, raw control trace hash, outcome, and invalid reason. A separate
verification after the batch recomputed every available reset-log, summary,
trace, and journal hash and found **zero mismatches**. All 100 reset down/up
exit statuses were zero. Raw files remain on Thor; the compact summary is
copied byte-for-byte into this repository.

The development smoke cases and earlier partial batches remain separate:
`final-target-v1-7b48965` was interrupted after 21 trials when independent
review found reset and synchronous-telemetry defects;
`final-target-v2-669c74d` was interrupted after 13 trials when review found a
heading timestamp alignment defect. Neither partial batch is counted in the
v3 rate. The v3 preflight on Thor passed 22 focused Python 3.12 tests and
matched every frozen config hash. The v3 development smoke had zero missed
control deadlines, zero safety violations, and an 8.02 ms maximum heading
sample delay. The final 100-trial batch is the only reported target result.

## Decision and boundary

**P7-02 = FAIL:** correct-direction rate is below `0.90`, and only 96 rather
than 100 trials met the valid-target floor. Safety remained within bounds.
This negative result does not show that all MaleCNS-based controllers fail;
it shows that this frozen controller and simulation experiment did not
demonstrate required target steering. No target or trial definition, yaw sign,
safety limit, or acceptance threshold was changed after the final v3 batch.

Per the requested phase sequence, P7-03 and P7-04 are not started and G7 is
not declared PASS. The 40 pre-registered no-target trials have not run.
Independent exact-head review of this evidence is pending. The P7-02 branch
must not merge unless a subsequent independently reviewed task disposition
explicitly authorizes preserving the failed experiment on main.
