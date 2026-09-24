# P7-01 deterministic target scenario evidence

## Scenario contract

`config/target_scenario_v1.json` freezes a 65×11 synthetic RGB camera frame,
5×5 red target marker, ±0.8 rad horizontal field of view, and left/right
near-center (`0.14`), medium (`0.36`), and far (`0.64`) radian bin centers with
at most `0.015` rad seeded jitter. Clean and moderate visual conditions are
versioned. Warm-up is `0.6 s`, slow crossing lasts `2.0 s`, and trial timeout
is `3.0 s`. The five P7-01 smoke seeds and classes are fixed in
`scenario-manifest-v1.json`; the final G7 trial seeds and order must be frozen
separately before P7-02.

The generator reads official MuJoCo heading, projects a world-fixed or slowly
crossing target into **camera pixels**, and feeds those pixels through the
existing CameraTargetDetector and PerceptionPipeline. A left bearing renders
at negative image `target_x`, consistent with the P6-03 simulator-calibrated
positive-left yaw. No-target frames keep the camera valid and contain no red
marker. Evaluator-only world bearing and class are computed separately after
pixels enter perception; they are not passed to the controller. This is an
engineering camera fixture, not a physical target object rendered by MuJoCo.

For identical seed, config, exact heading input, elapsed time, and frame index,
the pixel frame and perception are byte-for-byte deterministic. An official
`duck-sim down/up` reset restores the standing pose approximately; measured
pose variation must be retained rather than silently treated as an identical
initial condition. The world target bearing is anchored to each run's measured
initial heading, so the requested initial relative bearing remains defined.

## Thor smoke and reset replay

Source `2c283413fca03b6e46eb2acb3f2ab5aa64b5876e` ran on `jetsonthor01`
with the pinned official MicroDuck
`344925c9f8fa031f85428a305b1e8ec2eaae29c1` and microduck_rl
`cb70b792312d559a4da09064d92009079671815f`. The fixture SHA256 was
`2bd796acaed01f2f7ab1dec1434d6ea6ea1552f7854e0afd002873969ae80a4a`;
config SHA256 `089af4f05b5158579f7f335232793ffff5056fa3ea868d40cf0631fa0b33d804`;
manifest SHA256 `150afa5ee2ec5bf0e96917599a6edd74318e069358f53446c2e53e7e839f28de`.

The official simulator was started headless in a dedicated state directory.
Five smoke classes produced 150 valid perception frames and passed left/right,
crossing, no-target, pixel replay, official `robotd` health, and initial-pose
checks. A scoped official `duck-sim down/up` followed by the same five seeds
again passed all checks. Within-run initial heading spread was `0.0018293`
and `0.0018159 rad`; trunk-height spread was at most `5.8×10⁻⁶ m`. The first
trial's initial heading differed by `0.0001974 rad` across resets and trunk
height by `4.52×10⁻⁶ m`, within the frozen `0.02 rad` / `0.01 m` tolerance.

**149/150** frame pixel hashes matched across the two official resets. The
single difference was a crossing marker at frame 17 near the center pixel
boundary: measured robot headings differed by `0.000209 rad`, shifting the
detected centroid from `-0.03423` to `-0.00298`. Both runs individually
replayed **150/150** frames exactly when given their recorded heading samples.
This is measured simulator-state sensitivity, not a changed seed or config.

Thor Python 3.12 focused P7 scenario and P4 camera/perception tests:
**31 passed, 19 subtests passed**.

## Artifacts

Full frame-level JSONL remains on Thor under the two directories below. The
machine-readable summaries in this repository are byte-identical copies.

| Run / artifact | Bytes | SHA256 |
|---|---:|---|
| `20260924T-p701-smoke-v1/scenario-frames.jsonl` | 90,439 | `8b467a1e5198947babecb43fe32fd5ba5cfe2dfc872ab65606a150b0e526a076` |
| `20260924T-p701-smoke-v1/scenario-summary.json` | 4,031 | `3a0e88bb078b64c649d7b3c284ed7d228721bf4c9040141139ced879585ebaf6` |
| `20260924T-p701-smoke-v2/scenario-frames.jsonl` | 90,425 | `4d2f6898e3464bdb41901d80017af5e9eb162ec0b5ce097f444932ceb7025499` |
| `20260924T-p701-smoke-v2/scenario-summary.json` | 4,032 | `e1005b2c11898219dc3993c9aaaf6ce19eba9484b7150a80a135d9c7e9e95aaa` |
| `20260924T-p701-smoke-v2/python312-tests.log` | 100 | `57369e27931f2fe7813e181b1dc6bda5c1f3d84144e2657a58c548ca0a6126e4` |

Thor artifact root:
`/home/juper007/projects/microduck-connectome-thor/evidence/p7-01/`.

P7-01 verifies scenario generation and simulator-state replay. It does not
measure MaleCNS-derived steering success; P7-02 must run the full closed-loop
controller and score actual heading. Independent P7-01 review is pending.
