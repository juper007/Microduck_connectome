# P7-04 official Thor paired visual-noise result — independent review pending

The committed P7-04 design ran 60 matched base-seed pairs, one clean and one moderate target trial per pair, on official Thor robotd/MuJoCo. All 120 trials were valid and the batch status was `COMPLETE`. The observed moderate-minus-clean correct-direction difference was **−3.33 percentage points**, with a paired bootstrap 95% interval of **[−13.33, +5.00] points**. The interval crosses zero: the direction and size of a noise effect are **inconclusive under tested noise**. No new P7-04 performance PASS threshold was set. Independent final evidence review is pending; this record does not declare P7-04 or G7 complete.

## Frozen identity and design

The isolated Thor branch `experiment/p7-04-noise-robustness` was created from fetched `origin/main` `fcc2a77dade05d21a603ee887c4f28ee22401e37`. The exact clean source head used for the final run was `62915f900d8a3620bb7528a2378cb28bcedb9a9e`. The [manifest](../../../config/steering_noise_p7_04_v1.json) SHA256 is `58ec776f12d87966d1cfd5da5555d0d2c8276fa5468be0f211a8af4a67eaf808`; [generator](../../../scripts/p7_04_preregister.py) `16e1abd4bea013d3162f622f70041c5e5c829b721954a03b32362374aa8cd7d5`; [official harness](../../../scripts/p7_04_noise_batch.py) `1a651ee5af20a18909521f4f243ccbb263aaec3e7b72164b5345f9a6fb9e1da1`.

The manifest preserves the merged P7-03 source manifest SHA256 `fccc4a08656c8b3a81db6b7c8bd0a0b724abadc87c36163ca052ffc77d63c75b` and historical P7-02 manifest SHA256 `f24170521f049cec6a65a88285925343316f84ce9bdaf59a1a668257db5460cd`. The scenario config SHA256 is `089af4f05b5158579f7f335232793ffff5056fa3ea868d40cf0631fa0b33d804`. The unmodified model1250 ONNX SHA256 is `98c3ea73fa6bb196bcf16586cf38b9fffb782787447d638fa1c1028df9082c1a`; official MicroDuck and `microduck_rl` commits are `344925c9f8fa031f85428a305b1e8ec2eaae29c1` and `cb70b792312d559a4da09064d92009079671815f`. The graph key and cache SHA256 are both `340f6a3180026f6c61f19ebc016ae8610ec9f4a07af2af589e4d6d89e5b31f70`.

Twelve side × eccentricity × motion cells each contained five new matched base seeds; the 60 seeds were disjoint from prior P7-02/P7-03 seeds. Pair order and within-pair condition order were frozen by seed 7040401. Clean used target-pixel dropout 0 and background RGB jitter 0; moderate used the existing P7-01 values 0.2 and 20. Both trials in a pair shared the seed and target geometry. The controller, graph, walking policy, P6 safety envelope, response definition, validity rules, and trial timeout were unchanged. No failed or no-response trial was replaced. The preregistered paired bootstrap used seed 7040402 and 10,000 resamples.

## Official result

| Measure | Clean | Moderate |
|---|---:|---:|
| Valid / attempted | 60 / 60 | 60 / 60 |
| Correct | 53 | 51 |
| Incorrect | 7 | 7 |
| No response | 0 | 2 |
| Correct-direction rate | 88.33% | 85.00% |
| Wilson 95% interval | [77.82%, 94.23%] | [73.89%, 91.90%] |
| Response-only latency median / p95 | 0.764 / 0.807 s | 0.765 / 1.472 s |
| Terminal absolute target-bearing error median / p95 | 0.1685 / 0.8436 rad | 0.1809 / 0.8294 rad |
| First-response heading magnitude median | 0.0424 rad | 0.0402 rad |

The paired moderate-minus-clean correct indicator averaged **−0.03333**, with fixed-seed paired bootstrap 95% interval **[−0.13333, +0.05000]**. Pair discordance was 48 both correct, 5 clean-only correct, 3 moderate-only correct, and 4 neither correct. Latency and first-response heading summaries include responding trials only (clean 60; moderate 58); terminal error includes all 120 valid trials. Safety-limit violations, invalid trials, and started-trial failures were **0**. Maximum command-to-heading sample delay was **24.035 ms**. The official final `duck-sim down` exited 0; dedicated port 7876 and state process were gone afterward, while unrelated port 7864 remained active.

| Cell (side / eccentricity / motion) | Clean correct / 5 | Moderate correct / 5 |
|---|---:|---:|
| left / far / slow crossing | 4 | 5 |
| left / far / static | 5 | 5 |
| left / medium / slow crossing | 5 | 4 |
| left / medium / static | 5 | 5 |
| left / near center / slow crossing | 0 | 1 |
| left / near center / static | 5 | 3 |
| right / far / slow crossing | 5 | 5 |
| right / far / static | 5 | 5 |
| right / medium / slow crossing | 5 | 5 |
| right / medium / static | 5 | 5 |
| right / near center / slow crossing | 5 | 4 |
| right / near center / static | 4 | 4 |

The known P7-02 left / near center / slow crossing **0/10** subgroup was not excluded or reweighted; its P7-04 outcomes are shown above. The separate P7-02 G7 target aggregate was 108/120 (90.0%) and is historical evidence, not pooled into this P7-04 comparison.

## Raw evidence and integrity

The immutable raw directory is `/home/juper007/projects/microduck-connectome-thor/evidence/p7-04/final-noise-v1-62915f9`. Its `batch-summary.json` SHA256 is `044143f37207f2df3995426e397f3cb0f6a43075dd17e66096f8da5b9a6c4f74`; `trial-results.jsonl` SHA256 is `2f86749fb32fcc01b2fb822aae36ca03141a4c54ad3f7fb98ab88a4f67822130`. Every journal row binds its trace, trial summary, committed spec, command and acquisition SHA. Per-trial acquisition records bind policy-load/readback and retry logs. A postrun audit verified all 120 trace/summary/spec/command hashes, all 120 trial summary trace SHA and record counts, and 125 successful policy readback attestations (including pose-acquisition retries). The separate 1,476-file `final-noise-v1-62915f9-audit.json` SHA256 is `5d084f150c2ef46cbc33fc0b9195f19b7c8652d5c4bdf53858078a3410ae35d1`.

The separate `final-noise-v1-62915f9-preflight.json` SHA256 is `45ba4c2e544f2285749036e03860890b9477711309afc71aa8a493dfda35d535`; console log `final-noise-v1-62915f9-console.log` SHA256 is `5a1babbcd8ea271826397e8942b424f9306458dcc8be79f857820eb7ec274f88`; final `batch-final-sim-down.log` SHA256 is `d3f4afe57114c117d294acd158e7e26c1e0555df5b2145a4933c323f20891b7c`. One initial *prelaunch-only* preflight probe expected the graph cache path without its `.json` suffix; it failed before simulator or trial startup. The corrected probe changed no committed source, manifest, policy, command or seed. That failure is preserved in `/home/juper007/projects/microduck-connectome-thor/evidence/p7-04/preflight-attempt-001.json`, SHA256 `9f6e4efb1e2531ed84355c77baf7e0289d6eab54f4558f2292f97ed0cb304d90`.

The [machine-readable result](noise-robustness-v1.json) carries the complete class breakdown, uncertainty, identity and evidence paths. The prelaunch source head passed 23 focused Thor Python 3.12 tests and independent prelaunch GO. Final independent exact-head/raw review is pending. Only two existing synthetic visual-noise levels were tested; there was no separately rendered visual decoy and no physical-robot test. No GitHub push, merge, Phase 8, or threshold change is part of this record.
