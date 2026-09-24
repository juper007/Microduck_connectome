# P7-02 root-cause diagnosis and remediation boundary

This document records **development diagnostics**, not a reinterpretation of
the failed frozen v3 batch and not G7 evidence. The v3 result remains 0 correct
among 96 valid target trials, four invalid resets, and zero safety violations.
The immutable v3 source, manifest, raw journal, and independent FAIL review are
identified in [README.md](README.md).

## Where sustained steering was lost

The Thor v3 raw traces contain 14,496 correlated records. In the 47 valid
static-target trials, DNa02/pre-safety yaw appeared in same-sign pulses of about
100 ms, with no opposite-sign pre-safety rows while the target was visible.
There were 115 left-target inter-pulse gaps (median 260.0 ms, maximum 281.4 ms)
and 144 right-target gaps (median 199.9 ms, maximum 220.1 ms). Thus the first
loss of continuous intent occurs at the neural readout/decoder output, before
the safety gate. The v3 P7 decoder's nonzero demand is already saturated at
±0.5 rad/s when present; increasing its instantaneous gain cannot bridge a
zero-demand gap.

The frozen SafetyClamp correctly applied its 1.5 rad/s² yaw slew. Across all
valid trials, pre-safety yaw was nonzero in 2,900 rows, post-safety yaw in
5,397, and robot-facing yaw in 5,382; the largest robot-facing yaw was
0.152293 rad/s and the largest robotd-applied yaw was 0.094540 rad/s. The
watchdog was healthy in 14,400 rows; each trial had one expected end-of-run
safe stop. No mid-trial staleness or IPC loss explains the failure. The largest
actual MuJoCo heading change in any frozen 200 ms response window was
0.016667 rad, below the preregistered 0.02 rad threshold even before the 80%
same-sign requirement.

Static left trials (23) had median pre-safety yaw integral +0.30265 rad and
robotd-applied yaw integral +0.08577 rad, but median visible-period heading
change was −0.01279 rad. Static right trials (24) had corresponding integrals
−0.34958 and −0.10397 rad and heading change −0.02289 rad. The target-to-command
sign is therefore distinct for the two sides and reaches robotd; the body
response is weak and biased toward negative heading.

The P7-only remedy in this branch holds the **DN-selected** side through a
versioned 320 ms window while a fresh visual target remains present. The
observed maximum static gap was 281.4 ms. Visual presence can suppress a held
intent but never supplies the turn direction. Target loss or invalid input
requests stop; P6's decoder, yaw sign, clamp, watchdog, TTL, transport, and
robotd motor ownership remain unchanged. This is an engineering control
choice to be evaluated in a new experiment version, not a biological claim.
At clean Thor source `bc2f9f53763ee84387b49f3bbf4e15815a9e87f4`, static
left/right development trials held ±0.5 rad/s commands for about 2 seconds,
where the v3 pulses did not. Right produced a correct actual heading response;
left remained no-response. The no-target smoke sent stop with zero yaw in all
151 records. Focused Thor Python 3.12 tests passed 146/146; all three smokes
had zero safety violations and no missed deadlines. Development artifacts:
`/home/juper007/projects/microduck-connectome-thor/evidence/p7-02/r1-dev-review-bc2f9f5-v2`,
checksum manifest SHA256
`f2f510403ba51f7d9c7d3a080cb5e4fe15ab9e069dc1a29c94fb87b495bca264`.

## Official robotd/MuJoCo plant response

In isolated official-simulator diagnostics with fresh matched resets and
sustained high-level `robot.move` commands, both requested and applied yaw
reached the selected setpoint. These tests were deliberately outside the G7
controller path and cannot count as target-trial evidence.

| Official walking policy | Command | vx (m/s) | Peak qualifying-direction heading change in ~200 ms (rad) |
|---|---:|---:|---|
| `alpha_walking` | +0.2 | 0 | +0.00328, +0.00369 |
| `alpha_walking` | −0.2 | 0 | −0.02381, −0.02502 |
| `alpha_walking` | +0.5 | 0 | +0.01769, +0.01613 |
| `alpha_walking` | −0.5 | 0 | −0.04831, −0.04831 |
| `alpha_walking` | +0.5 | +0.04 | +0.01665, +0.01665 |
| `alpha_walking` | +0.5 | −0.04 | +0.02025, +0.01827 |
| `alpha_walking` | +0.5 | −0.08 | +0.01986, +0.01913 |
| `velstand` | +0.5 | 0 | +0.01213, +0.01086 |
| `velstand` | −0.5 | 0 | −0.04727, −0.04732 |

One `alpha_walking` +0.5/−0.04 run barely crossed 0.02 rad and its repeat did
not. A single +0.5/+0.08 run reached only +0.01593 rad. No **tested** supported
high-level condition gave repeatable positive-direction response at the frozen
criterion. Negative-direction conditions did. Both policies showed substantial
heading rebound toward the initial orientation after `robot.stop`; stop only
zeros twist and does not reset pose. The heading is raw MuJoCo trunk freejoint
orientation and agrees with robotd odometry, so this is not a sign-conversion
or telemetry artifact.

The ONNX policy emits sign-asymmetric 14-joint actions. In a matched ±0.5 pair,
positive yaw drove *larger* hip-yaw joint-target and measured-joint changes yet
smaller body rotation; target-tracking RMS was similar. The first downstream
deficit is therefore after successful robotd command application. The precise
division between learned gait pattern and contact dynamics is not established
by these traces. MuJoCo left/right foot friction, joint axes, actuator gains,
and major mass properties were checked and had no obvious mismatched setting.
The existing official `velstand` policy also failed the positive-direction
diagnostic. The roller policy uses a different wheeled scene and is not a
same-plant substitute.

Thor diagnostic summaries and SHA256 identities:

| Artifact | SHA256 |
|---|---|
| `/tmp/p702-diag-plant-evidence/summary.json` | `a1431180d5e634c86550b8bd125d1378c37bd5b0185f3b497153b1db0927c7ee` |
| `/tmp/p702-diag-plant-evidence/mechanism-summary.json` | `33ff6dc3cad7e46b9a206964c5ec4beee7ef0c938a0146106a76e430cb3e7bc9` |
| `/tmp/p702-diag-plant-evidence/bounded-negative-vx-summary.json` | `76751a6894790712525697a8bae175d93547777ed31e997001df099dcb5a016e` |
| `/tmp/p702-diag-plant-evidence/policy-vs-physics-summary.json` | `7e13b92ad0db237e675c34071b1d2c0013726c20a9d521755da1f4a628fd5a75` |

The selected `alpha_walking.onnx` SHA256 is
`e36332d383997d51401897734cd3e79cf5038406feddb18b4d57ecfb141daa6c`.
The tested `velstand.onnx` SHA256 is
`1c659be55da94bc5753b707de5c6a3e7c49931e05ca3b6991615cef1a8ba9a45`.
The deployed ONNX metadata do not establish a model-specific yaw-input domain;
internally amplifying input beyond the frozen external ±0.5 envelope was not
adopted. An independent safety concept review requires a new named, bounded,
hash-pinned policy and full affected safety/behavior recertification rather
than treating such amplification as equivalent to P6.

The first from-scratch, provenance-pinned yaw-policy checkpoint (iteration 500,
seed 70202) is a **rejected development candidate**. Its checkpoint SHA256 is
`783ba4c78d52dd25b362c08f8ed201e871ddb1fcfab7ad02cfd3cb2c1b6ecbc9`;
exported ONNX SHA256 is
`1deaafc002a3c96885c963dd9e41aca45c0d849f7e08020f76cfdffb0c588e06`.
Four fresh official robotd/MuJoCo runs used external ±0.5 rad/s yaw and zero
vx. Positive-command net headings were −1.16087 and −1.14718 rad, both wrong
direction; negative-command headings were −1.05123 and −1.20509 rad. Short
positive-command 200 ms windows of +0.04510/+0.03465 rad were outweighed by
opposite-sign windows of −0.11954/−0.11887 rad. Thus selecting a policy from
one qualifying window alone would be misleading. The trial readback verified
the loaded ONNX; there was no policy load or safety/clamp fault. Thor summary:
`/tmp/p702-policy-evidence/plant-model-500/summary.json`, SHA256
`e97ef1b1c10467d02a149ef48c091844cadad60bf75a1d38e059909a2e5345ca`.
It is not G7 evidence and must not be used for v4 registration.

Iteration 750 is a **promising development candidate**, not yet selected for
v4. Its checkpoint SHA256 is
`bacdd77bfbb06e454e408278b800e13f99793abe5e3a9d34e60a17603cf5d84e`;
ONNX SHA256 is
`be5c5d1efa2ffdf2d5276cbc0350095faef52ec27b6d8aac451f85390c1e573d`.
Five fresh official resets per sign at vx=0 and external yaw ±0.5 yielded
positive-command net headings +1.1867 to +1.3511 rad (median +1.2189) and
negative-command net headings −0.5440 to −0.3868 rad (median −0.3868).
Every run had at least 19 command-sign 200–270 ms windows above 0.02 rad;
the smallest per-run maximum was 0.0879 rad. There were no command limits,
faults, or falls; walking was active on all 60 command samples per trial.
The robotd policy readback confirmed the actual loaded ONNX. Thor summary:
`/tmp/p702-policy-evidence/plant-model-750/summary.json`, SHA256
`19790445a05c47ba3bfac03c69464f3392faedf16e879af8f4f3cab9d1cbf29d`.
This candidate still requires policy selection and affected P6 safety/soak
revalidation before v4 preregistration or a final target batch.

Iteration 1000 was compared under the same official simulator protocol and
regressed positive yaw: two +0.5 runs had net headings +0.0728 and −0.0097 rad,
while two −0.5 runs had −1.5969 and −1.7776 rad. Its checkpoint SHA256 is
`7f3170b1af39b838694ee5ea36c26556d9559060f3b24b29b3ef63a699c44348`;
ONNX SHA256 is
`a73c94a66e5b0bac01e2f39319de37bf3baaffad42881609bc44b66c5124f8ce`.
No command limits or falls occurred. Thor summary
`/tmp/p702-policy-evidence/plant-model-1000/summary.json` has SHA256
`ea39667a03d04cebcb1f921c97163c7a9e6f66aeebaa5cd7f806b1e57d884c5`.
Iteration 750 is therefore the preliminary policy choice for same-hash P6
recertification. This selection used only development plant diagnostics,
before any v4 target-trial seed was run.

## Initial-pose validity

Frozen v3 had four invalid target trials whose official reset exits succeeded
but initial heading or trunk height was outside the preregistered tolerance.
The old logs omitted the measured values. A new isolated 30-reset diagnostic
found one persistent heading failure: measured 0.07920046 rad versus reference
0.11884765 rad (error 0.0396472 > frozen 0.02 rad), still 0.0390227 rad away
after 1 second. Trunk height stayed within tolerance. Official `duck-sim`
starts the MuJoCo body from the SIT keyframe, then runs the stand policy for
six seconds and checks height/gravity; a longer post-start settle alone did not
fix this case. The simulator has no supported post-stand pose reset call.
The pinned Thor reset diagnostic is
`/home/juper007/projects/microduck-connectome-thor/evidence/p7-02/r1-reset-review-bc2f9f5`:
`summary.json` SHA256
`f57656e8523aa2542568042ae39703b99834bdae52f6b110e12ff7b92dfa5ad9`,
`resets.jsonl` SHA256
`a3774c526ebc8818f721d753a84bfbe1532c0c78b1dc746a8581567cce1d1949`.
The relevant official source is `microduck/scripts/duck-sim` lines 666-667
(SIT body-server launch) and 503-515 (standing and six-second wait), plus
`microduck_rl/src/mjlab_microduck/sim/body_server.py` lines 261-274
(fixed initial qpos/qvel).

The new pose-check helper records numerical heading/height and unchanged
tolerances before a trial. A future preregistration may define bounded
**pretrial** official down/up reacquisition, recording every attempt and
failing if no acceptable pose is obtained. It must never replace a started
trial or alter the frozen v3 exclusions. The final acquisition rule is not yet
registered or used for G7.

## Decision boundary

The first neural-pulse continuity defect is fixed in the P7 branch and
development-tested. P7-02 remains **FAIL** until a provenance-pinned official
walking policy demonstrates repeatable bidirectional body response, a new
experiment version is frozen before a complete Thor target batch, at least
100 target trials are valid, the correct-direction rate reaches 0.90 with zero
safety violations, and an independent review passes at the final branch head.
P7-03, P7-04, and G7 remain unstarted.
