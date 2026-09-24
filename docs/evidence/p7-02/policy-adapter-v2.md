# P7-02 official walking-policy candidate and input adapter

This is a **development policy candidate**, not P7-02/G7 completion evidence.
The complete official simulator artifacts are on Thor at
`/home/juper007/projects/microduck-connectome-thor/evidence/p7-02/policy-development-6012390-20260924/adapter-v2`.

## Why a new policy identity was needed

The unmodified provenance-pinned iteration-750 walking policy responded in
both directions to external ±0.5 rad/s commands but failed the frozen P6-03
external −0.2 rad/s sign calibration. Its requested and robotd-applied command
were both −0.2, while actual trunk heading turned positive on two fresh
resets. See [remediation-diagnosis.md](remediation-diagnosis.md) and the Thor
affected-P6 FAIL summary SHA256
`ca40749af5d50cf9cb09e71575d0ade84f687bff158a10b0a6514a4de679f09c`.

The new version is a policy-specific ONNX observation adapter. It changes only
the yaw-command value delivered to the 61-input/14-output walking network:

```text
policy_input_yaw = clip(2.5 * robotd_external_yaw, -0.5, +0.5)
```

The official `robotd` input tensor remains named `obs`; the other 60
observation values are unchanged. This is an **engineering choice**, not a
MaleCNS or biological inference. External controller intent remains subject
to the unchanged P6 ±0.5 rad/s yaw limit, 1.5 rad/s² yaw slew, watchdog/TTL,
stop, and robotd motor ownership. The policy input stays within ±0.5, inside
the model's pinned training yaw-command range of ±1.0. The adapter increases
small-command gain and internal input slew, so actual body motion, near-zero
noise, command reversal, stop, and failures require new exact-hash validation.

## Artifact identity and development checks

| Artifact | SHA256 |
|---|---|
| Adapter v2 ONNX | `8ef31f969c6fd096b40e51639cb6c3bb7e8816998a08ba4720affe5dffa945a1` |
| Base iteration-750 ONNX | `be5c5d1efa2ffdf2d5276cbc0350095faef52ec27b6d8aac451f85390c1e573d` |
| Base iteration-750 checkpoint | `bacdd77bfbb06e454e408278b800e13f99793abe5e3a9d34e60a17603cf5d84e` |
| Adapter offline equivalence report | `605bce94cb08487c2e920419793b50e82aeeca0b52cb443c8583133e25f6aba7` |
| 20-run official development summary | `a2d33cd205b4591dae7d50b9d7202741294544e9da95cc6b952b1b3a68ca13be` |
| Durable adapter evidence manifest | `08d3aaf25699cdb4acd3affaca9ca28b9c4ccf3d9fde2507201a87b26fb12970` |

The model training/export source commit is
`601239073ab58b1586e02d4851910d996e842838`, with recipe SHA256
`a5672f17d25e834a8c6c5c4710dd4fa04c9d0cb8f2bc095d1bf949dc3deedf47`,
seed 70202, 4096 environments, and checkpoint iteration 750. The official
MicroDuck and simulator sources remain pinned at
`344925c9f8fa031f85428a305b1e8ec2eaae29c1` and
`cb70b792312d559a4da09064d92009079671815f`.

Offline ONNX Runtime comparison over 100 random 61-value observations for
each external yaw 0, ±0.2, ±0.5 gave identical 14-action outputs to the base
network fed the mapped yaw (maximum absolute action difference 0.0). The
first adapter v1 was rejected by the official loader because its input tensor
was named `external_obs`; v2 preserves the required `obs` contract and loaded
successfully through the official policy interface.

The v2 ONNX then ran 20 isolated official robotd/MuJoCo development trials:
five fresh resets for each external +0.2, −0.2, +0.5, and −0.5 rad/s at zero
forward speed. All 20 six-second net trunk-heading changes had the commanded
sign. Each run had a command-sign 200–270 ms window above 0.02 rad, at least
15 such windows, no command limits, and no fall. Robotd requested/applied yaw
matched the external command; the loaded policy readback was hash-checked.
The weakest −0.2 net heading was −0.0247 rad, so the small negative response
has limited margin. These runs selected a candidate for affected P6 tests and
are not counted as final target trials.

## Promotion boundary

The exact adapter ONNX must pass the fresh P6 signed-yaw, bounded-motion,
stop/TTL, fault, restart, and 10-minute soak checks. Only then may the v4
experiment manifest be generated. It pins the adapter, its base checkpoint,
recipe, construction script, offline equivalence, 20 development traces, and
affected-P6 PASS summary. Final official P7 target trials use new
preregistered seeds, with unchanged response and safety thresholds. P7-03
no-target final trials remain a later task after P7-02 PASS and merge.
