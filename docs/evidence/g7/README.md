# G7 — steering behavior demonstrated in official simulation

**Independent G7 verdict: PASS** on merged `origin/main`
`1f9c7ca85070246eef5b5141007f474ca5e52951`, reported by the
non-author `$independent-phase-reviewer` agent `/root/p606_review`.
No blocking findings were reported. This is a record of that review,
not a new performance threshold or a hardware authorization.

## Scope and frozen decision

[Gate G7](../../COMPLETION_CRITERIA.md) requires correct-direction
steering on at least 90% of valid target trials, no-target false-turn
rate below its preregistered threshold, and zero safety-limit
violations. The P7-02 v4 manifest froze 120 target seeds and order,
the first actual MuJoCo heading-window response (at least 0.02 rad
over at least 0.2 s, at least 80% same-sign increments), target
bearing at response onset, no-response as an evaluated failure,
at least 100 valid target trials, and the 0.90 aggregate threshold.
P7-03 separately preregistered 40 new no-target controls; a false
turn is absolute robot-facing yaw at least 0.10 rad/s sustained for
0.2 s after 0.6 s warmup, with observed rate at most 0.05.
P7-04 preregistered a paired clean/moderate comparison without an
additional success-rate PASS threshold. None of these rules,
safety limits, yaw sign, seeds, exclusions, or response definitions
was retuned after its respective final result.

The exact reviewed merge chain is:

| Task | PR | Merge commit |
|---|---:|---|
| P7-01 scenario | [#48](https://github.com/juper007/Microduck_connectome/pull/48) | `34c8857251e14f83a9dff9697f947599781ff01e` |
| P7-02 target | [#49](https://github.com/juper007/Microduck_connectome/pull/49) | `41a9849325e2a52714ecd23fd75c2a394c28c658` |
| P7-03 no target | [#50](https://github.com/juper007/Microduck_connectome/pull/50) | `fcc2a77dade05d21a603ee887c4f28ee22401e37` |
| P7-04 noise | [#51](https://github.com/juper007/Microduck_connectome/pull/51) | `1f9c7ca85070246eef5b5141007f474ca5e52951` |

The [P7-01 scenario evidence](../p7-01/README.md) fixes
`config/target_scenario_v1.json` SHA256
`089af4f05b5158579f7f335232793ffff5056fa3ea868d40cf0631fa0b33d804`;
its smoke manifest SHA256 is
`150afa5ee2ec5bf0e96917599a6edd74318e069358f53446c2e53e7e839f28de`.
The [P7-02 v4 manifest](../../../config/steering_experiment_v4.json)
SHA256 is
`f24170521f049cec6a65a88285925343316f84ce9bdaf59a1a668257db5460cd`.
The [P7-03 manifest](../../../config/steering_no_target_p7_03_v1.json)
SHA256 is
`fccc4a08656c8b3a81db6b7c8bd0a0b724abadc87c36163ca052ffc77d63c75b`.
The [P7-04 manifest](../../../config/steering_noise_p7_04_v1.json)
SHA256 is
`58ec776f12d87966d1cfd5da5555d0d2c8276fa5468be0f211a8af4a67eaf808`.
All final batches used the unmodified model1250 walking ONNX SHA256
`98c3ea73fa6bb196bcf16586cf38b9fffb782787447d638fa1c1028df9082c1a`,
MaleCNS graph key/cache SHA256
`340f6a3180026f6c61f19ebc016ae8610ec9f4a07af2af589e4d6d89e5b31f70`,
official MicroDuck commit
`344925c9f8fa031f85428a305b1e8ec2eaae29c1`, and
`microduck_rl` commit
`cb70b792312d559a4da09064d92009079671815f`.
The exact-policy affected-P6 simulation recertification summary
SHA256 is
`1183d980e1a1f267cd05d1645049266f05c4503497f02eb21c9a4b68b7affbea`;
its independent prerequisite review reported PASS for yaw sign,
bounded motion, stop, reconnect/restart, TTL/fault, and a 605.184 s
closed-loop soak.

## Official results and uncertainty

| Frozen or preregistered measure | Official observation |
|---|---:|
| P7-02 valid target / correct | 120 / 108 |
| P7-02 correct-direction rate | **0.9000**; Wilson 95% [0.8333, 0.9419] |
| P7-02 incorrect / no response / invalid | 11 / 1 / 0 |
| P7-03 valid no-target / false turns | 40 / 0 |
| P7-03 observed false-turn rate | **0.0000**; Wilson 95% [0, 0.08762] |
| P7-04 clean valid / correct | 60 / 53; Wilson 95% [0.7782, 0.9423] |
| P7-04 moderate valid / correct | 60 / 51; Wilson 95% [0.7389, 0.9190] |
| P7-04 paired moderate minus clean | −0.03333; bootstrap 95% [−0.13333, +0.05000] |
| Total official Phase-7 trials / telemetry rows | **280 / 42,280** |
| Safety-limit violations / started-trial failures | **0 / 0** |

P7-02 met the frozen **aggregate** 0.90 target criterion exactly,
with no margin above it. Its left/right breakdown was 49/60 and
59/60; static/slow-crossing breakdown 59/60 and 49/60.
The left/near-center/slow-crossing subgroup was **0/10** and remains
in the denominator. The Wilson lower bound below 0.90 does not establish
a population-level success probability above 0.90. The earlier
[P7-02 v3 FAIL](../p7-02/README.md), with 96 valid and zero
qualifying responses, remains an immutable negative record; it was
not reclassified by v4.

P7-03's 0/40 observed rate meets its preregistered 0.05 control
threshold, but the Wilson upper bound of 0.08762 means 40 zero-event
trials alone do not bound the underlying false-turn probability below
5% at 95% confidence. The early P7-02 40/0 no-target run was a
pre-P7-03 diagnostic and is **not** counted among these 280 official
trials.

[P7-04](../p7-04/README.md) used 60 fresh base seeds in 60 matched
clean/moderate pairs across all 12 side × eccentricity × motion cells.
It observed 53/60 clean and 51/60 moderate correct, or **104/120**
on new seeds across both conditions. This descriptive new-seed result
is not a rerun of the P7-02 frozen acceptance sample and does not
replace its 108/120 G7 target decision. The two observations per pair
are correlated; 104/120 must not be treated as 120 independent
generalization draws. Pair discordance was 48 both correct, 5
clean-only, 3 moderate-only, and 4 neither. The paired interval
crosses zero, so the noise effect is **inconclusive under these two
tested levels**. The hard left/near-center/slow-crossing cell was
0/5 clean and 1/5 moderate; it was neither excluded nor reweighted.
Only synthetic clean/moderate pixel dropout and RGB jitter were
tested; there was no separate rendered decoy object.

Across official trials, P7-02 contributed 18,120 telemetry records,
P7-03 6,040, and P7-04 18,120. Per-trial official simulator
down/up, exact walking-policy load/readback, initial-pose validity,
raw trace and command logging, and final down were retained.
All three final batches reported zero safety-limit violations.

## Representative causal traces

Two successful **P7-02 official** static, moderate-noise trials show
the measured chain from camera perception through the MaleCNS-derived
high-level command to actual MuJoCo body heading. These are illustrative
traces, not a replacement for all 120 scored trials:

| Trial / raw trace SHA256 | Camera → stimulation → DNa02 → command | First qualifying body response |
|---|---|---|
| Left `p7-v4-target-002`, `a53d32aa215d69fff68751291f4a9103da546d5f16a58ebdc7e6549efe5e0730` | `target_x = −0.4625`; `lc10a_left = 1.0`; steering left/right `0.2/0.0`; pre/post-safety yaw `+0.5/+0.5 rad/s`; robotd move transport | `+0.04020 rad` over 0.20069 s, onset target bearing `+0.38842 rad`, latency 0.774 s |
| Right `p7-v4-target-001`, `285b629e83f7225162080866b90e1ba5205d64f277b009d80988f7fda78b09b0` | `target_x = +0.4669`; `lc10a_right = 1.0`; steering left/right `0.0/0.2`; pre/post-safety yaw `−0.5/−0.02798 rad/s` at response start (slew clamp), robotd move transport | `−0.02115 rad` over 0.22031 s, onset target bearing `−0.36806 rad`, latency 0.334 s |

The sample values above are from telemetry records nearest each
response start; each response delta is the frozen scorer's first
qualifying window. The controller issued bounded **high-level**
motion intents; official `robotd` and its motion/safety stack kept
motor ownership. Perception labels, stimulus, DNa activity,
pre/post-safety yaw, transport and body heading are in the raw trace,
so a visible target or a nonzero neural command alone was not counted
as steering success.

## Raw evidence and independent review

| Official batch | Raw directory on Thor | Summary SHA256 | Journal SHA256 |
|---|---|---|---|
| P7-02 target | `evidence/p7-02/final-target-v4-model1250-fdde4578` | `8f2e7d797b1bf01a4249f9cad9e17ca8c57e4574750e653d7d56a438347192ca` | `f9379d4911cc2075d28e09f579c583dca87403dd1617e0bde487adf79f54225b` |
| P7-03 no target | `evidence/p7-03/final-no-target-v1-316b9b1` | `0b284ca64144e7c40d1d63cb6ae29cacc93cee8529f10335515bab219f52859d` | `ad59a20c6848486aaabb53ff4a2d783b2c78c5a8462531b61a0c10fc90664dfa` |
| P7-04 paired noise | `evidence/p7-04/final-noise-v1-62915f9` | `044143f37207f2df3995426e397f3cb0f6a43075dd17e66096f8da5b9a6c4f74` | `2f86749fb32fcc01b2fb822aae36ca03141a4c54ad3f7fb98ab88a4f67822130` |

Each path above is under
`/home/juper007/projects/microduck-connectome-thor/`.
The [P7-02 handoff](../p7-02/v4-final-handoff.md),
[P7-03 record](../p7-03/README.md) and
[P7-04 record](../p7-04/README.md) identify all per-trial raw files,
logs, retries and limitations. The P7-03 postrun audit SHA256 is
`f308c71e85400d458289c9b44cc70bdad1ae260584730b4710489209fbe3f41b`;
the P7-04 1,476-file audit SHA256 is
`5d084f150c2ef46cbc33fc0b9195f19b7c8652d5c4bdf53858078a3410ae35d1`.
P7-04 preflight SHA256 is
`45ba4c2e544f2285749036e03860890b9477711309afc71aa8a493dfda35d535`;
its separate prelaunch-only failed probe is preserved as SHA256
`9f6e4efb1e2531ed84355c77baf7e0289d6eab54f4558f2292f97ed0cb304d90`
and did not start the simulator or a trial.

The independent reviewer `/root/p606_review` reported **G7 PASS,
zero blocking findings** at merged main
`1f9c7ca85070246eef5b5141007f474ca5e52951`.
The reported review scope was the PR #48–#51 reviewed-head/merge
chain; frozen P7-02/03/04 manifests and policy/config/graph/upstream
SHA; preregistration timing, seeds, order and failed-trial retention;
all three raw summaries/journals and representative left/right actual
heading traces; selected ONNX and exact-policy P6 recertification;
280 trials, 42,280 telemetry rows, safety bounds/watchdog/`robotd`
ownership; and **39 source tests passed**. This G7 record itself is
a later documentation-only commit and awaits its own final exact-head
independent review before PR or merge.

This evidence supports [H1 target-following steering](../../preflight/EXPERIMENT_PROTOCOL.md)
within the pinned official simulation and tested scenarios. It does
not test H3 topology value: no matched shuffled/random topology
comparison was run, and G9 remains separate. G7 authorizes planning
the next **simulation** phase, subject to its own task packets and
reviews. It does not satisfy G10 or permit autonomous physical
hardware testing.
