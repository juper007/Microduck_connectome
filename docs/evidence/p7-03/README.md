# P7-03 official Thor no-target controls — aggregate PASS, review pending

P7-03 used a newly preregistered set of 40 no-target trials after P7-02
PR #49 merged. The official batch met the frozen observed false-turn and
safety thresholds. Independent final evidence review is still pending;
this record does not declare P7-03 or G7 complete.

## Identity and prior evidence

The dedicated branch is `experiment/p7-03-no-target-controls`, created
directly from fetched `origin/main` merge commit
`41a9849325e2a52714ecd23fd75c2a394c28c658`. The clean Thor source
head for all 40 trials was
`316b9b11bf7043e2127d768bb680f68615b87218`.
The committed [control manifest](../../../config/steering_no_target_p7_03_v1.json)
has SHA256
`fccc4a08656c8b3a81db6b7c8bd0a0b724abadc87c36163ca052ffc77d63c75b`;
the [official batch harness](../../../scripts/p7_03_no_target_batch.py) has
SHA256 `bb25a74cb4a0e96aca3866a7aed4dcc74e7ab25f9954fdeff41c4a1171e91858`.
The deterministic [preregistration generator](../../../scripts/p7_03_preregister.py)
has SHA256
`ac4533ad79fc849ab19212310765a9b1a0e8c7a91a79c6c5a400295cdb5a7903`.
Its control-order seed is **7030301**. All 40 control seeds and trial IDs
are unique and disjoint from the 120 P7-02 target plus 40 early diagnostic
control seeds and IDs; 20 new trials are clean and 20 moderate visual noise.

The target component was **reused as historical P7-02 evidence**, not
rerun or rescored: 120 valid targets, 108 correct, zero safety violations.
Its batch summary SHA256 is
`8f2e7d797b1bf01a4249f9cad9e17ca8c57e4574750e653d7d56a438347192ca`;
journal SHA256
`f9379d4911cc2075d28e09f579c583dca87403dd1617e0bde487adf79f54225b`.
The source P7-02 manifest SHA256 is
`f24170521f049cec6a65a88285925343316f84ce9bdaf59a1a668257db5460cd`.
The new manifest retains its controller/config hashes, target specifications,
policy, validity, safety, stop/TTL and response rules. Only the experiment
identity, P7-03 provenance block and the 40 no-target specifications changed.

The walking policy is the same unmodified model1250 ONNX, SHA256
`98c3ea73fa6bb196bcf16586cf38b9fffb782787447d638fa1c1028df9082c1a`;
its metadata SHA256 is
`2e0a16534b30772eecafa1f405f596b085043aea20b33236fd7b34857e64c1c5`,
training recipe SHA256
`a5672f17d25e834a8c6c5c4710dd4fa04c9d0cb8f2bc095d1bf949dc3deedf47`,
checkpoint SHA256
`e2354a97fa87e2bddca1e4dd1896bdaa04c671d1f62cd96ea77bdc107e1902e6`,
and resume manifest SHA256
`5920758f0c00a49c38fc92473bae16d8f0bc8d677323f7cc0691b5d59fc05a3e`.
Training/export source was
`601239073ab58b1586e02d4851910d996e842838`, seed 70202, 4096
environments, iteration 1250. The exact-policy affected P6 simulation
recertification summary SHA256 is
`1183d980e1a1f267cd05d1645049266f05c4503497f02eb21c9a4b68b7affbea`
and its independent prerequisite review reported PASS.
Official MicroDuck and `microduck_rl` commits were
`344925c9f8fa031f85428a305b1e8ec2eaae29c1` and
`cb70b792312d559a4da09064d92009079671815f`; graph key
`340f6a3180026f6c61f19ebc016ae8610ec9f4a07af2af589e4d6d89e5b31f70`.

## Frozen rule and official result

A false turn is `abs(robot_facing_vyaw) >= 0.10 rad/s` for at least
0.2 s after 0.6 s warmup. The observed rate must be at most 0.05,
with zero safety-limit violations. The committed harness requires an
official simulator down/up, exact policy load/readback, pose acquisition
and healthy runtime for each trial; no started trial is replaced. It
stops the batch and takes the simulator down on a started-trial or safety
failure. Each scored trace is bound to trial summary SHA, row count and
timestamp span, committed-spec SHA, manifest, policy and journal hashes.

| Measure | Result |
|---|---:|
| Attempted / valid evaluated | 40 / 40 |
| No-target outcome / false turns | 40 / 0 |
| Observed false-turn rate | 0.000 |
| Wilson 95% interval | [0.000, 0.08762] |
| Invalid / started-trial failures / safety violations | 0 / 0 / 0 |
| Clean / moderate visual-noise trials | 20 / 20 |
| Official final `duck-sim down` | exit 0 |

This meets the preregistered **observed** 0.05 false-turn-rate threshold.
The Wilson upper bound exceeds 0.05: forty zero-event trials do not
establish an underlying false-turn probability below 5% with 95%
confidence. The current no-target scene has clean/moderate background
visual noise but **no separately rendered decoy object**. This run
measures false steering in that baseline, not responses to a distinct
visual distractor. It is official Thor simulation evidence, not a
physical-robot test.

## Secondary motion and raw evidence

All 40 traces contained 151 control records (6,040 total). Both the
full-trial and post-warmup maximum absolute robot-facing yaw were
**0 rad/s**; the maximum sustained interval above the false-turn
threshold was **0 s**. The median absolute final trunk-heading change
was `0.000461176 rad`; maximum absolute final change and maximum
post-warmup excursion were `0.000966634 rad`. These tiny nonzero
heading changes are measured MuJoCo body motion, not command-triggered
false turns. Maximum command-to-heading sample delay was
`26.121 ms`, below the frozen 100 ms validity limit.

The raw directory is
`/home/juper007/projects/microduck-connectome-thor/evidence/p7-03/final-no-target-v1-316b9b1`.
Its `batch-summary.json` SHA256 is
`0b284ca64144e7c40d1d63cb6ae29cacc93cee8529f10335515bab219f52859d`;
`trial-results.jsonl` SHA256 is
`ad59a20c6848486aaabb53ff4a2d783b2c78c5a8462531b61a0c10fc90664dfa`.
Every row names a raw `<trial_id>/trace.jsonl`, `summary.json`,
`trial-spec.json`, `trial-command.json`, and pretrial retry log hashes.
The separate `postrun-audit.json` checked 952 identity, order, safety,
status, and raw-file hashes: PASS, SHA256
`f308c71e85400d458289c9b44cc70bdad1ae260584730b4710489209fbe3f41b`.
A per-trial machine-readable digest and these secondary metrics are in
[control-summary-v1.json](control-summary-v1.json), SHA256
`12ab41418a85a8c77ebe0395c9124c73d90f414413018e73b83d1ffb4f036424`.

The separate preflight JSON SHA256 is
`b7c811979c9e9d7a0b9057bf2e8559c9d93bcdc4e81115aca6030fb7c181a68f`;
console SHA256 is
`23a4f110c506623e470fb74b6cc9d17a3c605c513318b52e102f0f100df42f97`.
Both are in Thor `evidence/p7-03` with prefix
`final-no-target-v1-316b9b1`. Final official-down log SHA256 is
`d3f4afe57114c117d294acd158e7e26c1e0555df5b2145a4933c323f20891b7c`.
The dedicated state used port 7875, which was closed after the final down;
the unrelated port-7864 simulator was untouched.

The earlier P7-02 **40/0** run remains a pre-P7-03 diagnostic/control
record and is not counted here. Its summary/journal SHA256 values are
`90284a8d680892ed5a77f25635b561b7e1dbe726188c78c8be8640f0400d78be`
and `ce90c78c62340b50c191b3910c15a98fa3f7fcb38ceaf2bb1820db89e7b4e7e1`,
respectively. None of its seeds or trial IDs was reused.

## Validation and status

The exact prelaunch source head passed Thor Python 3.12 focused tests
(27 passed), deterministic manifest regeneration, P7-02 target
summary/journal readback, and independent prelaunch review GO. The
postrun audit passed and source remained clean. The final P7-03 raw
evidence still needs independent exact-head review. P7-04 and G7 are
not declared complete; no GitHub push, merge, Phase 8, or hardware
execution is included in this record.
