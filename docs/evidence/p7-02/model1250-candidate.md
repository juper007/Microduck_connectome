# P7-02 unmodified walking-policy checkpoint 1250

This is a policy-selection record. No run here counts toward the final P7-02
target batch or G7. The previously tested model-750 adapter passed affected
P6 simulation recertification but gave a reproducible wrong-way **first**
heading response to a left target. See [policy-adapter-v2.md](policy-adapter-v2.md).
The frozen P7 criterion selects the first qualifying 200 ms body-heading
window, so eventual net left rotation does not repair that result.

## Candidate identity

The unmodified checkpoint-1250 policy is exported from the same pinned
training recipe and source as model 750, after a documented resume from the
model-1000 checkpoint. Its artifact is on Thor at
`/home/juper007/projects/microduck-connectome-thor/evidence/p7-02/policy-development-6012390-20260924/checkpoint1250-diagnostic/model1250.onnx`.

| Artifact | SHA256 |
|---|---|
| Model-1250 ONNX | `98c3ea73fa6bb196bcf16586cf38b9fffb782787447d638fa1c1028df9082c1a` |
| Model-1250 training checkpoint | `e2354a97fa87e2bddca1e4dd1896bdaa04c671d1f62cd96ea77bdc107e1902e6` |
| Training recipe | `a5672f17d25e834a8c6c5c4710dd4fa04c9d0cb8f2bc095d1bf949dc3deedf47` |
| Resume provenance manifest | `5920758f0c00a49c38fc92473bae16d8f0bc8d677323f7cc0691b5d59fc05a3e` |
| Direct 10-run selection diagnostic | `ae3a7a84e33f983919e3c22ab9be4caa94e8e0861cf6264051f8035c9efc19fb` |
| Five-run full-chain development smoke | `7439a98b36dd35f293a57ea6c6c655165d9903d3a9333794e99f0aa06abc30bb` |

Training/export source commit is
`601239073ab58b1586e02d4851910d996e842838`, seed 70202, 4096
environments, iteration 1250. The selected ONNX preserves the official `obs`
input and 61-observation/14-action contract without an input adapter.

## Development results and limits

Five fresh official robotd/MuJoCo resets per external yaw sign (±0.5 rad/s,
zero forward speed) all had the commanded six-second net heading sign and the
commanded **first qualifying** 200–270 ms heading sign. Positive first
windows were +0.0744 to +0.0839 rad and negative first windows about
−0.0482 to −0.0485 rad. Policy readback was hash-checked for every run; no
fault or fall occurred. Raw traces/readbacks are referenced by path and
SHA256 in `checkpoint1250-diagnostic/candidate-diagnostics.json`.

Five separate non-final full MaleCNS/robotd/MuJoCo development trials on
fresh resets gave `correct` for static left, static right, moving left, and
moving right; the no-target trial gave `no_target`. The first target-heading
responses were +0.04269, −0.02100, +0.05108, and −0.02571 rad respectively.
All validity and safety checks passed, and the loaded policy was the selected
ONNX. The left-moving trial's final net heading was only +0.0084 rad, which
illustrates why the preregistered **first** response and full raw trajectory
must both be retained. The development summary and raw hashes are at
`checkpoint1250-diagnostic/p7-development-smoke/summary.json`.

These small, deliberately selected development sets establish only that this
policy is suitable for affected P6 recertification and a newly preregistered
P7 target batch if P6 passes. They do not estimate the 120-trial target rate.
The exact ONNX must pass fresh P6 ±0.2 net-sign calibration, stop, restart,
fault/TTL, bounded motion, and 10-minute soak. Final P7 target trials must use
the new v4 manifest and its untouched, balanced seeds. External safety limits,
controller yaw sign, TTL, stop, and P7 scoring remain frozen.
