# P8-03-R2 pose reset remediation protocol

Status: prospective development protocol. P8-03-R1 is terminal FAIL in PR #80
and GitHub Release `p8-03-r1-evidence-v1`; this protocol does not revise it.
No R1 final trial, including RS04 seed 887204, may be rerun or counted in R2.

## Diagnosis and limits of inference

RS04 failed before arm: its second heading was 0.018440959 rad against the
frozen R1 first-reset reference 0.116933584 rad, a 0.098492625 rad difference
above the unchanged 0.08 rad tolerance. The two RS04 reads 100 ms apart differed
by only 0.000061442 rad, so late drift during those reads is not the explanation.
R1 did not record simulator clock for RS04, so its precise onset cannot be
reconstructed. The policy file, policy readback, and healthy robotd logs matched
the other R1 runs.

R2 exploratory Thor traces used 64 fresh resets, separately from every final
seed. All simulator clocks advanced, all cleanups and manifests passed
independent review. In a deferred-load SIT run, one heading was approximately
0.067 rad **before** explicit walking-policy load, while the other resets were
near 0.117 rad. It persisted after load and was stable within the two-second
observation. HOME and STAND keyframes had still larger between-reset spreads.
This supports real pose variation by the end of official `duck-sim up` and
robotd stand-up. Stale reads, explicit policy-load settling, and pose read
timing after up are not sufficient explanations for that observed variation.
The precise simulator/robotd startup mechanism remains unproven; no numerical
tolerance is changed on that inference.

The four immutable exploratory manifests are under Thor
`evidence/p8-v2-final/p8-03-r2-diagnosis-{r1cadence,deferred-policy,home,stand}-v1`.
Their SHA256 values, in that order, are
`3188ad67cabf91d6abcdea3b4539b0f357bcc99597448b573588998d348abced`,
`47a9173d70e74f587404ed5f006128f38624fb0d3b0f160777551a9d27ac8738`,
`f44b068778f7779905a46e0beb07749d9ecc85076443fe0b108f45e14bf642a0`,
and `88bacd161c570b4e09592ba3bac0a5021baa4ba686a99d3dd5a14a817b260fe7`.

## Frozen R2 intervention

Use the R1 RS00 first-reset pose as a **prospective R2 reference**, explicitly
named in `config/p8_03_r2_protocol_v1.json`. This fixes the R1 ambiguity in
which the first final seed implicitly defined the reference. The scene's SIT
keyframe, official fresh down/up, and pinned walking policy remain. An
acknowledged robotd stop, fresh advancing official simulator pose reads, healthy
robotd, finite roll/pitch within 0.5 rad, and x/y/z within the unchanged pose
tolerance must precede any preparation command.

If heading error exceeds the preregistered 0.06 rad guard, a development-only
preparation prototype may issue high-level robotd `robot.move` commands with
zero requested translation and yaw at most 0.2 rad/s. It is outside the scored
window, uses the 100 ms command TTL, stops at 0.03 rad error, has a three-second
hard deadline, and makes one attempt per fresh reset. Any stale/late read,
health loss, translation or attitude bound, ACK loss, timeout, or cleanup fault
fails that reset; stop, down, and probe follow. It never commands servos.
The pilot and 60-reset development evidence determine whether this intervention
is viable. Successful preparation demonstrates a repeatable **prepared**
initial condition, not deterministic raw simulator resets.

After acknowledged stop, wait a separate fixed 1 s settling interval, then
obtain 21 sequential 50 ms pose samples over at least 0.95 s, with strictly
advancing simulator time, host response intervals of 30–75 ms, and no read
older than 100 ms.
Require healthy robotd, three zero-applied-motion state observations, every
sample within x/y 0.03 m, z 0.025 m, heading 0.08 rad of the frozen reference,
heading within the stronger 0.06 rad guard, and heading drift at most 0.005 rad.
No neural stop, visual score, or trial outcome enters this decision.
The final trial must start only after this preparation and qualification, and
the original moving-body precondition and arm checks still apply.

## Development and final gates

The pilot uses three unnumbered development resets and cannot qualify finals.
The first perturbation development output, `p8-03-r2-alignment-perturbation-v1`,
is terminal FAIL: a pose read immediately after the first accepted command
failed freshness or bounds; the rejected pose was not retained, so unchanged
simulator time is an inference from timing. It remains immutable and is
excluded from the held-out batch. Version 2 waited for the fixed 50 ms tick,
then failed the corrective path after its first negative command: the next
fresh pose increased error by 0.016366 rad. Residual motion after the deliberate
turn is a plausible cause, not a proven yaw-sign error. Version 3 adds a fixed
one-second post-perturbation settle and requires a stable offset still outside
the guard before attempting correction. Versions 1 and 2 remain terminal FAIL.
Version 3 also remained below its
deliberate 0.09 rad perturbation target at its one-second deadline: 20 accepted
commands changed final heading by about 0.053 rad. The acknowledged stop came
39 ms after that deadline, so v3 correctly remained FAIL despite successful
cleanup. None of versions 1–3 count toward qualification. Version 4 gives
this auxiliary offset generation a three-second motion-through-stop bound
while retaining the same 0.2 rad/s command cap, fresh-pose checks, translation
bounds, stop ACK requirement, and separate one-second settling interval. The
last 500 ms are reserved for the 100 ms command ACK, 100 ms pose read, bounded
robotd stop attempt, and connection closure. The independent 100 ms robotd
command TTL bounds motion if a stop ACK cannot be obtained; such a reset FAILs.
If those resets never require alignment, a separate two-reset development
perturbation deliberately turns the body once in each yaw direction by at
least 0.09 rad through bounded high-level robotd intent, stops, then runs the
same preparation gate. Its resets are excluded from the 60-reset estimate and
cannot become final trials. This tests the otherwise unexercised corrective
path without tuning to a final result. Its three-second maximum includes the
acknowledged final stop, not merely reaching the target heading.
If it fails, revise the intervention as a new version and rerun an independent
review before starting a held-out batch. The held-out development matrix is
887400–887459, in three consecutive groups of 20. All 60 fresh resets must pass
with zero retries, zero exclusions, a complete manifest, and exact-head
independent review. A failure is terminal for this protocol version and bars
every R2 final seed. Zero failures in 60 gives a one-sided 95% binomial upper
failure-rate bound of about 4.87%, not proof of deterministic raw resets.

Only after that gate may static R2S00–R2S19 use seeds 887500–887519 and
receding R2R00–R2R19 use 887600–887619, in that order. Each ID gets one fresh
reset and one pre-arm attempt. The original 1 s scored window, geometry,
false-stop thresholds, zero safety-violation rule, and raw scoring stay frozen.
No R1 seed, final ID, partial arm, or result is recycled. A failed R2 seed is
reported terminally, with the remaining IDs pending, not silently replaced.

Final evidence requires a complete immutable GitHub Release, a clean remote
download and hash/manifest re-verification, independent raw re-score, and
exact-final-head review before a PASS can be claimed. The release, source and
protocol hashes, graph, policy, simulator commits, seed matrix, reset traces,
stop ACKs, and post-down probes form the provenance record.

## Exact Thor handoff

Use isolated source
`/home/juper007/projects/microduck-connectome-thor/p8-03-r2-source` at the
independently reviewed SHA, Python 3.12, pinned MicroDuck
`344925c9f8fa031f85428a305b1e8ec2eaae29c1` and microduck_rl
`cb70b792312d559a4da09064d92009079671815f`. Before execution verify a
clean `git status --porcelain`, exact source HEAD, pinned graph/policy SHA256,
unused dedicated output and `/tmp/p8-03-r2-reset-development-state`, and
an idle simulator/socket/port 7898. Run the reviewed development entry point:

```sh
python3.12 -B scripts/p8_03_r2_reset_development.py --kind pilot --reviewed-head <EXACT_REVIEWED_SHA> --output /home/juper007/projects/microduck-connectome-thor/evidence/p8-v2-final/p8-03-r2-reset-pilot-v1
```

If the reviewed pilot PASSes and the protocol/code are frozen on a newly
reviewed exact head, run `--kind perturbation` with
`p8-03-r2-alignment-perturbation-v4` as output, then run
`--kind qualification` with
`p8-03-r2-reset-qualification-v1` as output. Do not infer qualification from
the pilot or launch a final seed from a protocol without a PASS gate.
Any remote disconnect requires inspecting the same output/state and process
identity; it never authorizes a replacement attempt.

## Phase continuation

If P8-03-R2 final static and receding gates PASS with current exact-head
review, continue P8-04, then final regression, then G8 on separate task
branches and reviews. Stop before Phase 9. If any gate FAILs, retain its raw
evidence and mark downstream gates BLOCKED.
