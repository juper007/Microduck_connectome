# P8-R1 development stop persistence: negative evidence

Status: **FAIL / unmerged draft**. Owner skill: `$behavior-control-engineer`.
Supporting read-only roles: `$microduck-integration-engineer` and
`$robot-safety-engineer`. Base `origin/main`:
`e4ade0276e5e3f67381f4ca3da9f181077387fa1`.

This versioned remediation addresses the loss of `robot.stop` refresh after a
healthy DNp01/EscapeDecoder stop when RGB and neural updates continue. The
reusable high-level latch selects a newly timestamped stop intent before
SafetyClamp, which passes through the genuine healthy Watchdog and
RobotMotionAdapter. It retains origin step, threshold-qualified escape
activity and source. A fault stop has separate priority. Tests cover
in-flight movement, earlier ACK attribution, old neural-update races and
fault-before-ACK behavior. Thor Python 3.12 focused tests: 57/57 PASS at the
version 3 frozen source.

Each development version was committed before its three official Thor
duck-sim/robotd/MuJoCo trials. All nine planned trials completed. No seed was
replaced and no trial was reclassified. Raw directories contain trial events,
neural ledgers, command and state observations, batch summaries, reset logs,
and SHA256 manifests. The simulator was taken down after every batch.

| Version | Frozen source | Seeds | Frozen transport result | Raw directory | Batch SHA256 | Manifest SHA256 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `8274c5579a5995361fa5d96bbd3cde0042cec38c` | 881101–881103 | FAIL/FAIL/FAIL | `/home/juper007/projects/microduck-connectome-thor/evidence/p8-r1/dev-8274c55-20260925-1/` | `57c17df5058cf821acca3a9580067c14a658ece5993985c1f2565c1eb9af025f` | `ab074889c198805bf4523d57fb4f6c5be9f7a9353d61c368825dcd58953955b9` |
| 2 | `d8e1e225afb76d3b49e6777bde97c80ed98d8735` | 881111–881113 | PASS/FAIL/FAIL | `/home/juper007/projects/microduck-connectome-thor/evidence/p8-r1/dev-d8e1e22-20260925-1/` | `487b3cb523c312b891ede8b1f9a0e10b35bec0b222c97b1a4e2af4df10316be9` | `b045050be668500ef938200045565105beb29812453ac0c28d5b5a518352af0b` |
| 3 | `d07b8b45a742ae7f4dc373e9557263459d104eb9` | 881121–881123 | FAIL/FAIL/FAIL | `/home/juper007/projects/microduck-connectome-thor/evidence/p8-r1/dev-d07b8b4-20260925-1/` | `f939435c9e28aa497e207bce4509b2d8b75298a2d3d66014ef54d2a665f4a57f` | `228d5d3acecc0d57f4049ec94b1fd55c1fa8b594fb978f6705f439ad2baae790` |

Version 1 exposed a handoff race between neural candidate staging and the
50 Hz control thread, plus a pre-stop state sample received just after the
first stop call. Version 2 atomically handed the candidate to control and
used a causally prior state sample. All three version 2 trials then reached
healthy DNp01-origin `robot.stop` ACK with repeated refresh, applied velocity
decline, pose-derived stop, and no deadman-caused cessation. Its frozen
composite still failed twice: seed 881112 had a startup deadman readback,
while 881112 and 881113 missed the unchanged >0.015 m virtual sphere
clearance guard. Every neural trigger was after the frozen 0.25 m boundary.

Version 3 armed the same scenario at elapsed 2.0 s with fresh seeds, while
retaining the 0.25 m boundary and >0.015 m clearance requirement. It counted
deadman only after a sampled moving-body state, retaining startup observations
in raw events. Earlier arming did not advance the neural trigger sufficiently.
All three reached a healthy DNp01-origin stop ACK with stop refresh gaps below
25 ms and no deadman before cessation. All three failed the clearance guard;
two continuing visual streams entered the virtual sphere and raised a
perception worker fault. The version 3 frozen composite is **0/3**, and all
three behavioral boundary outcomes are **FAIL**. Per-trial values are in
`development-summary-v1.json`.

These results support the narrow claim that the new latch transported three
healthy neural stops through official `robot.stop` in versions 2 and 3.
They do **not** establish a passing P8-R1 remediation or P8-02 early
avoidance. The task remains open pending a separate, prospectively versioned
remediation with new seeds and full rerun. Draft PR #66 and its raw negative
evidence remain untouched.

Reproduce the current focused tests in the pinned Thor checkout:

```sh
PYTHONPATH=$PWD python3 -m unittest tests.test_neural_stop_latch tests.test_fault_stop tests.test_escape_decoder tests.test_safety_clamp tests.test_watchdog tests.test_g8_r5d_fixture -q
```

Re-run a frozen version only to reproduce it in a **new unused output
directory**, using `scripts/p8_r1_stop_persistence_batch.py` at the exact
source commit with the corresponding committed versioned config. Do not
overwrite any directory listed above.
