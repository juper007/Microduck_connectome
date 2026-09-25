# P7-02 v4 Thor evidence handoff — target threshold met, final review pending

This record is for task **P7-02-R1**. It supplements the immutable
[v3 FAIL record](README.md); it does not replace or reclassify that result.
The P7-02 target metric met its frozen threshold on Thor, but the combined
exact-head independent review is in progress. This document does **not**
declare P7-02 merged, P7-03 or P7-04 complete, or G7 PASS.

## Source and frozen protocol

The work uses branch `experiment/p7-02-target-steering`, based directly on
fetched `origin/main` commit
`34c8857251e14f83a9dff9697f947599781ff01e`. The clean local Thor
checkout is
`/home/juper007/projects/microduck-connectome-thor/p702-v4-manifest-54fa362`.
The target batch ran at
`fdde4578f0705a1a30cfe1c2ea5d5e48faf0d2aa`. The later no-target
harness ran at `a6e5bf30f427cc36d2211f6c1f6ad9af9c61cb3a`; this
advance added the no-target harness and tests only. Target trial code,
controller, and the committed v4 manifest did not change between batches.
The documentation commit will be a still later head and requires its own
review. No GitHub push, PR merge, or Phase 8 work is part of this handoff.

The preregistered manifest is
[`config/steering_experiment_v4.json`](../../../config/steering_experiment_v4.json),
SHA256 `f24170521f049cec6a65a88285925343316f84ce9bdaf59a1a668257db5460cd`.
It fixes the 120 target seeds/order and reserves 40 no-target seeds/order.
The exact unmodified walking policy is
`/home/juper007/projects/microduck-connectome-thor/evidence/p7-02/policy-development-6012390-20260924/checkpoint1250-diagnostic/model1250.onnx`,
SHA256 `98c3ea73fa6bb196bcf16586cf38b9fffb782787447d638fa1c1028df9082c1a`.
The model metadata SHA256 is
`2e0a16534b30772eecafa1f405f596b085043aea20b33236fd7b34857e64c1c5`;
training/export source `601239073ab58b1586e02d4851910d996e842838`,
seed 70202, 4096 environments, checkpoint iteration 1250. See
[model1250-candidate.md](model1250-candidate.md) for selection provenance.
Official MicroDuck and `microduck_rl` were pinned at
`344925c9f8fa031f85428a305b1e8ec2eaae29c1` and
`cb70b792312d559a4da09064d92009079671815f`, respectively. The
MaleCNS graph key was
`340f6a3180026f6c61f19ebc016ae8610ec9f4a07af2af589e4d6d89e5b31f70`.

The frozen target rule requires the **first** actual MuJoCo heading window
to change at least 0.02 rad over 0.2 s with at least 80% same-sign
increments. Correct direction is evaluated against the target bearing at
response onset. At least 100 valid target trials, correct-direction rate
at least 0.90, and zero safety violations are required. No-response is an
evaluated failure. Each trial uses an official simulator down/up, exact
policy load/readback, one-second settle, initial-pose check, and at most
three logged pretrial acquisition attempts; no started trial is replaced.
The P6 yaw sign, external 0.50 rad/s yaw and 0.08 m/s forward bounds,
watchdog/TTL, stop transport, response definition, exclusions, seeds, and
acceptance threshold were not relaxed.

## Exact-policy affected P6 prerequisite

The selected ONNX was revalidated through official Thor robotd/MuJoCo on
the same policy SHA. The aggregate affected-P6 summary is
`/home/juper007/projects/microduck-connectome-thor/evidence/p7-02/policy-development-6012390-20260924/checkpoint1250-diagnostic/affected-p6-recert/summary.json`,
SHA256 `1183d980e1a1f267cd05d1645049266f05c4503497f02eb21c9a4b68b7affbea`.
It reports **PASS** for paired six-second ±0.2 rad/s net-heading signs,
bounded motion, acknowledged stop, reconnect/robotd restart, fault/TTL,
and a 605.184 s closed-loop soak with 30,252 telemetry records. Its
`artifact_sha256` map binds 106 raw files. The independent prerequisite
review reported **PASS** after auditing those raw hashes. That review is
separate from the still-pending combined P7-02 final evidence review.

P6 recertification is simulation only. The soak was primarily stationary;
moving response was covered by calibration and bounded probes. After
robotd restart the policy slot persisted during homing, so each final P7
trial reloaded and read back the exact policy before motion.

## Official P7-02 target batch

Raw directory:
`/home/juper007/projects/microduck-connectome-thor/evidence/p7-02/final-target-v4-model1250-fdde4578`.
The `batch-summary.json` SHA256 is
`8f2e7d797b1bf01a4249f9cad9e17ca8c57e4574750e653d7d56a438347192ca`;
`trial-results.jsonl` SHA256 is
`f9379d4911cc2075d28e09f579c583dca87403dd1617e0bde487adf79f54225b`.
All 120 journal rows contain per-trial spec, summary and raw trace hashes;
the raw `<trial_id>/trace.jsonl` and `summary.json` files remain there.
The launch command and console log are adjacent to the directory as
`final-target-v4-model1250-fdde4578.launch-command.txt` (SHA256
`75a9ed55c1e4f667d459e3be10ac89d0d1fb156c2c88facca1351c32a02f8027`)
and `final-target-v4-model1250-fdde4578.launch.log` (SHA256
`517625a998fb4a9dbdb5a86fed6d8a7fad9047cf57eb67c18d6ca1b7d04b8fed`).

| Frozen target measure | Observed |
|---|---:|
| Attempted / valid evaluated | 120 / 120 |
| Correct / incorrect / no response | 108 / 11 / 1 |
| Correct-direction rate | 0.9000 |
| Wilson 95% interval | [0.8333, 0.9419] |
| Invalid / started-trial failures / safety violations | 0 / 0 / 0 |
| Maximum command-to-heading sample delay | 23.669 ms |
| Final official simulator down | exit 0 |

Thus the target batch meets the frozen **aggregate** P7-02 target threshold
exactly, conditional on combined independent review. It has no margin above
0.90: one fewer correct trial would fail. The 10
left/near-center/slow-crossing trials had **0/10 correct**. This subgroup
failure remains visible rather than being reclassified or excluded. Left
overall was 49/60, right 59/60, static 59/60, crossing 49/60. The Wilson
interval describes sampling uncertainty; its lower bound is below 0.90 and
does not imply population-level performance above the threshold.

## Early no-target control run: sequencing deviation

The [P7-02 remediation task packet](../../tasks/P7-02-remediation.md)
reserves the 40 no-target final trials for **P7-03 after P7-02 PASS and
merge**. The 40 reserved no-target seeds were run early, before that
sequence completed. Preserve the immutable raw data, but classify this as
a **pre-P7-03 diagnostic/control run**, not formal P7-03 final evidence,
and do not use it to declare P7-03 or G7 complete. No further no-target
trial is authorized by this handoff.

The early run used the same v4 manifest and policy, an isolated simulator
state/port, and the committed no-target harness SHA256
`dc7468fcc78841574868a7ab81cb02f5855a5f9e8b0a0b61df895b9793ea833e`.
Its frozen exploratory false-turn definition was absolute robot-facing yaw
at least 0.1 rad/s sustained for 0.2 s after the 0.6 s warmup, with
observed rate at most 0.05. It recorded **40/40 valid no-target outcomes,
0/40 false turns, zero safety violations**, and official final down exit 0.
The 95% Wilson interval for the observed false-turn rate is [0, 0.0876],
so these 40 zero-event trials alone do not bound the underlying rate below
5% at 95% confidence.

Raw directory:
`/home/juper007/projects/microduck-connectome-thor/evidence/p7-02/final-no-target-v4-model1250-a6e5bf3-r1`.
Its `batch-summary.json` SHA256 is
`90284a8d680892ed5a77f25635b561b7e1dbe726188c78c8be8640f0400d78be`;
`trial-results.jsonl` SHA256 is
`ce90c78c62340b50c191b3910c15a98fa3f7fcb38ceaf2bb1820db89e7b4e7e1`.
The separate postrun integrity audit of 937 hash/identity/status checks is
`postrun-audit.json`, SHA256
`b4acfd630b5d52e23fe869ce8c793c775938cf95914480ea9d0ea9c74b52e518`.
Every raw trace, trial summary, generated spec, command, and pretrial retry
log is named by its journal row; scored trace bytes were checked against
the trial summary's artifact SHA, row count and timestamp range, and the
manifest-derived trial-spec SHA.

The first launch attempt failed **before creating a simulator state or
starting any trial** because a direct Python file invocation could not
import `scripts`. Its preflight JSON SHA256 is
`040abd084d2243dce577bd6fee787daa5544ba092a9721d6094c70dabaaad9ff`;
console SHA256 is
`7f1263caf8eb024a36e35f8b36b0fe7384c338769d09c0e7de16f79153344656`.
Both remain in the parent Thor `evidence/p7-02` directory with prefix
`final-no-target-v4-model1250-a6e5bf3`. The successful retry used
`python3.12 -m scripts.p7_no_target_batch_v4` and a new `-r1` output
directory; its preflight JSON SHA256 is
`688846d7f6bc2e979358ca7768edb93b46725f1c8f88f68def4d40f6a641be6e`,
console SHA256 is
`b479d7be40024fc0541f59451f0cea6c4a5eb96b4a6973349fbfec7ffb53595e`.
No failed attempt was overwritten or counted as a trial.

## Validation and disposition

The Thor Python 3.12 focused suite for the no-target harness, pretrial
acquisition, target batch and steering trial had **20 passing tests** at
the no-target execution head. A read-only postrun audit found 937 passing
checks across 40 raw runs, and the source worktree remained clean.
The v3 negative result, the v4 target raw batch, the early no-target
diagnostic/control run, and development diagnostics are distinct records.

The P7-02 target aggregate is eligible for the ongoing exact-head
independent review. Final P7-02 disposition and any merge await that
review of the latest task branch head. P7-03/P7-04/G7 remain open.
