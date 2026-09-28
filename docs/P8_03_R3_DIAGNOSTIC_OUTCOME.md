# P8-03-R3 yaw diagnostic outcome

**Status: terminal FAIL / bidirectional mapping unestablished.** This is
development-only diagnostic evidence. PR #80 and Release
`p8-03-r1-evidence-v1` remain terminal R1 FAIL; PR #81 remains terminal R2
FAIL. Neither was changed or merged. No final P8-03 static or receding seed,
R2 60-reset qualification, or correction strategy ran.

## Frozen execution and evidence

The independent pre-execution reviewer passed source
`8ecc05023f1b40aac3aab8748feb14a8f66d8b6e` against base
`57161251c63be912a002d236d18e7c13cd48b1cc`. That exact clean head
ran on Thor in isolated checkout
`/home/juper007/projects/microduck-connectome-thor/p8-03-r3-yaw-source`,
using pinned MicroDuck `344925c9f8fa031f85428a305b1e8ec2eaae29c1`,
microduck_rl `cb70b792312d559a4da09064d92009079671815f`, model-1250
policy SHA256 `98c3ea73fa6bb196bcf16586cf38b9fffb782787447d638fa1c1028df9082c1a`,
and graph SHA256 `c4160c42941163079b6b569d117bf67afcf8b45eaa128c444f7c96c2567593cc`.
Six focused tests passed on the exact Thor checkout before execution.

The frozen 50-reset matrix used development IDs D00–D49, labels/seeds
887700–887749, with 20 positive, 20 negative, and 10 sham planned fresh
resets. The single-use evidence root is
`/home/juper007/projects/microduck-connectome-thor/evidence/p8-v2-final/p8-03-r3-yaw-diagnostic-v1`.
Only D00 and D01 were attempted; D02–D49 remain unrun and must not be
backfilled into this result.

| ID | Condition | Result | Finding |
| --- | --- | --- | --- |
| D00 | +0.2 rad/s for 0.20 s | VALID | Post-stop wrapped heading delta −0.004758654418 rad; absolute response is below the preregistered 0.005 rad minimum detection floor. |
| D01 | −0.2 rad/s for 0.20 s | FAIL | Runner reported `command-induced translation bound exceeded` during post-stop observation and aborted the matrix. No valid final heading delta. |

Both pulse stop ACKs, cleanup stop ACKs, official `duck-sim down` exit 0,
and final socket/port probes passed. The dedicated robotd socket and body
port were absent afterward. The D01 threshold-triggering pose was rejected
before append and is not in the raw trace: the last retained planar
displacement was 0.007467 m against the 0.01 m limit. The recorded error and
orderly abort are supported; the exact crossing cannot be independently
recomputed from retained pose rows. No stronger safety or mechanism claim is
made from that missing sample.

Independent raw scoring returned `FAIL` for incomplete matrix (2/50).
Independent evidence review verified all 13 manifest-listed files by hash,
size, and line count; manifest SHA256
`ca17dcd9317a769ee4b044c7a8883279dfbba74a25b10112081bbf0464a0f175`,
gate SHA256 `38c2a54c5b7aa5decff23a9041f9159c031658551ef1bd91aec687b3ee33e4c2`.
The published GitHub Release
`p8-03-r3-yaw-diagnostic-evidence-v1` targets the exact execution head.
Its `p8-03-r3-yaw-diagnostic-evidence-v1.tar.gz` asset SHA256 is
`f0720ff6d2b341c8b071a93639cf90dced5ad92c4b29c24de007bc926f0ab82c`.
The asset was downloaded from GitHub and matched Thor's SHA256; extracting it
and rescoring from raw traces again returned FAIL. GitHub reports
`immutable: false` for this published release, so retention relies on the
recorded tag and digest rather than GitHub release immutability enforcement.

## Interpretation and gate

The D00 positive-pulse response is below the frozen detection floor and
cannot establish positive yaw sign. D01 cannot establish negative sign because
it failed a safety bound before final measurement. No sham reset ran, so the
final sham-based floor was not estimable. This evidence does not isolate the
R2 correction-polarity mechanism among coordinate convention, robotd command
sign, MuJoCo heading, policy response/rebound, clamp, pose timing, reset
asymmetry, nonlinear contact, or infrastructure. Root-cause class:
**unresolved; development safety abort and incomplete bidirectional data**.
Bidirectional consistency is unestablished. A correction strategy and reset
qualification are ineligible. No final P8-03 seed may be inferred or
authorized from this terminal R3 result.

The next work item, if pursued, must be separately versioned and
preregistered before any new development reset. It must retain the
threshold-triggering pose in raw evidence and independently review a safe
diagnostic path. It must not reuse D00/D01 or any R1/R2 final seed.
