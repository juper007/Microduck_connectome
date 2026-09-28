# P8-03-R1 acquisition durability and final control protocol

Status: **preregistered, not executed**. Base: fetched `origin/main`
`57161251c63be912a002d236d18e7c13cd48b1cc`. PR #79 and Release
`p8-03-s00-interruption-v1` remain immutable negative history. S00/881000
has unknown arm state and is permanently ineligible for R1. Never resume the
original output root or rewrite its journal, manifest, or archive.

## Root cause

**KNOWN:** S00 entered ACQUIRING after preflight PASS. The last journal says
`armed=false`; a zero-byte `down.log` was absent from its checkpointed
manifest. There is no completed trial or final down record. The old
`run_child` opened the log before waiting for the child; the supervisor
checkpointed only after return. The old arm marker was a plain text write,
without fsync. The old recovery correctly classified S00 unknown-arm.

**INFERRED:** termination while `duck-sim down` ran or after its log opened
fits these bytes. Fragile SSH orchestration and the checkpoint gap are
plausible contributors, not proven causes.

**UNKNOWN:** exact terminating actor, signal/exit status, whether down
started, whether arm happened after the checkpoint, and S00 safety count.
Root-cause class **UNKNOWN**; a harness evidence-durability defect is
confirmed. R1 fixes that defect and decouples supervisor lifetime from SSH.

## Frozen inputs and seed audit

`config/p8_03_r1_protocol_v1.json` is the machine-readable final matrix.
The normative `config/p8_v2_final_protocol_v1.json` is bound by SHA256
`d281d239b9d080027d4c2662f889f76e68e04ef06599d78bb0cd644dcf515e42`.
R1 changes only trial identities and acquisition/evidence plumbing. It keeps
the V2.4 controller, RGB representation, looming estimator, graph-v2, neural
model, DNp01 threshold, EscapeDecoder, SafetyClamp, Watchdog, robot.stop,
robotd authority, 20/50/50 Hz rates, 100 ms TTL, geometry, 1,000 ms scored
window, scoring definition, and acceptance thresholds fixed.

Tracked config, task protocols, scripts, tests, historical evidence, and the
live P8 Releases (`p8-02-r1-evidence-v1` and
`p8-03-s00-interruption-v1`) were checked for seed references. No prior
reference to the chosen R1 ranges was found. Thor preflight also rejects
pre-existing R1 output or launch roots.

| Seed/range | Historical reference | Executed? | Armed? | Reserved? | R1 eligible? |
| --- | --- | --- | --- | --- | --- |
| 880000–880119 | P8-02 and reserved extensions | mixed | mixed | yes | no |
| 881000 | P8-03 S00 negative Release | interrupted | unknown | yes | no |
| 881001–881023, 882000–882023 | original P8-03 matrix/extensions | no verified run | no verified arm | yes | no |
| 883000–883009 | P8-04 final faults | no final run | no | yes | no |
| 884000–884102, 885xxx, 886020–886022 | P8 development/R1 | mixed | mixed | yes | no |
| 887100–887105 | no prior reference found | no | no | R1 development | development only |
| 887200–887219 | no prior reference found | no | no | R1 static | yes |
| 887300–887319 | no prior reference found | no | no | R1 receding | yes |

The exact order is RS00–RS19 with seeds 887200–887219, then RR00–RR19
with seeds 887300–887319, ascending. Each row inherits its original S/R
arm-cycle and matched-approach metadata. Development seeds never enter the
40-trial denominator. No replacement seed or result-driven ordering.

## Source, arm state, and evidence

Use one clean Thor checkout at the **independently reviewed exact R1 HEAD**.
Any source edit after review requires another review. Use the pinned
upstream commits, graph/policy hashes, Python 3.12, official duck-sim,
robotd, isolated port 7895 and state `/tmp/p8-03-r1-state`, and unused
paths in `config/p8_03_r1_execution_v1.json`. A preflight mismatch assigns
zero final IDs. Record source HEAD, config hashes, upstream hashes, ID,
seed and attempt.

R1 makes one attempt per ID. A simulator-up failure stops the batch and
requires a separately reviewed recovery decision; the harness never
automatically retries. A durable marker means ARMED and bars retry.
Missing marker is PRE_ARM only when exact reviewed code and raw data prove
arm never happened. Corrupt, conflicting, or unprovable state is UNKNOWN_ARM;
no retry and no PASS. The marker is written to a unique temporary file,
flushed, fsynced, atomically renamed, and parent-fsynced **before** neural
arm. Journal/marker disagreement blocks PASS.
Before a child starts, creation of the output, ID and attempt directories
is followed by fsync of each containing parent directory; the marker's
rename then fsyncs the attempt directory itself.

Every created log is checkpointed on open and after exit. Other meaningful
transitions checkpoint the journal and full SHA256/byte/record-count
manifest with artifact class, attempt and state. Following forced
termination, `--recover-only --r1` writes a recovery report and reconciles
partial/zero-byte artifacts. It never launches a trial or changes an arm
marker. Final verification checks every file; missing, extra, or mismatched
bytes block PASS.

Each R1 child starts through `p8_03_r1_child.py`, which sets Linux
`PR_SET_PDEATHSIG=SIGINT` and checks its expected parent before executing
the command. A supervisor death during the launch-to-PID-record gap
therefore prevents the child from arming; recovery still reports UNKNOWN_ARM
for that gap and performs stop/down/probe. Recovery refuses to touch a
batch whose recorded supervisor PID and process start identity are alive.
An unreadable or missing recorded identity also blocks recovery writes.
After verified supervisor death, recovery performs stop/down/probe even
for a provably PRE_ARM attempt; arm classification and simulator cleanup
are separate decisions.

Start Thor's authoritative supervisor once with
`python3.12 -B scripts/p8_03_r1_remote.py start --state <unused-root> --
python3.12 -B scripts/p8_03_batch.py --r1 ...`. It creates a detached
session with closed stdin, captures stdout/stderr in `supervisor.log`,
records PID and Linux process start ticks, and refuses a second launch at
that root. The detached helper waits for both durably written
`launch.json` and `start-ack.json` before executing the batch; a launcher
death before acknowledgement times out without assigning an ID.
`INCOMPLETE_LAUNCH_NO_BATCH_ACK` is a retained no-retry status for that
root. Reconnect with `status --state <root>`; never auto-restart.
`interrupt --state <root>` sends SIGINT for stop, checkpoint, down and
probe. LOST requires recovery and review.

The exact static launch/status/reconnect form on Thor is:

```bash
SOURCE=/home/juper007/projects/microduck-connectome-thor/p8-03-r1-source
THOR=/home/juper007/projects/microduck-connectome-thor
EVIDENCE=$THOR/evidence/p8-v2-final
HEAD=$(git -C "$SOURCE" rev-parse HEAD)
cd "$SOURCE"
python3.12 -B scripts/p8_03_r1_remote.py start \
  --state "$EVIDENCE/p8-03-r1-static-launch-v1" -- \
  python3.12 -B scripts/p8_03_batch.py --r1 --stage S \
  --root "$SOURCE" --reviewed-head "$HEAD" \
  --microduck "$THOR/microduck" --microduck-rl "$THOR/microduck_rl" \
  --graph "$THOR/evidence/g8-r1/graph-v2/c4160c42941163079b6b569d117bf67afcf8b45eaa128c444f7c96c2567593cc.json" \
  --policy "$THOR/evidence/p7-02/policy-development-6012390-20260924/checkpoint1250-diagnostic/model1250.onnx" \
  --sim-executable "$THOR/microduck/scripts/duck-sim" \
  --output "$EVIDENCE/p8-03-r1-static-v1" \
  --audit "$EVIDENCE/p8-03-r1-preflight-audit.jsonl" \
  --sim-state /tmp/p8-03-r1-state --body-port 7895
python3.12 -B scripts/p8_03_r1_remote.py status \
  --state "$EVIDENCE/p8-03-r1-static-launch-v1"
```

After a LOST status, use the same batch arguments with
`--recover-only` while the original source remains at that exact HEAD;
the recovery path refuses a live supervisor. Receding uses stage R and
the frozen receding output/launch roots; it starts only after static PASS.

## Development interruption gate

Before **any** final seed, run a retained synthetic/development-only
interruption suite on Thor using 887100–887105 where a seed is needed.
Retain raw, journals, markers, manifests, recovery reports, logs and
down/probes.

| Case | Required observation |
| --- | --- |
| A | interruption before marker proves PRE_ARM |
| B | interruption after durable marker proves ARMED; retry prohibited |
| C | SIGINT during acquisition stops safely, checkpoints, down/probe |
| D | supervisor termination/SSH disconnect reconnects; no duplicate/retry |
| E | zero-byte/partial logs fully accounted |
| F | final-down failure recorded and cannot PASS |

All six cases, focused regressions, and independent review of development
evidence must PASS. Freeze a gate artifact at the configured
`development_gate` path with six PASS cases, exact reviewed source HEAD
and review result PASS. The final batch preflight checks it before assigning
IDs. A development FAIL stops all final execution.

The versioned no-final-seed runner is
`scripts/p8_03_r1_dev_gate.py`.
The first development run at `p8-03-r1-development-gate-v1` remains retained
as a failed evidence review: its top-level inventory omitted five nested
manifests and its case E overwrote the zero-byte checkpoint. Its result and
manifest SHA256 values are `f1d5300c99963f4617cd79661e5d9e3744b4afef68136479976fdb9420d8cbac`
and `83de41fc1cf7572b29150732af20eb16e6adfa7e0ea65785f5a4ad1eb349d4fc`.
The v2 development rerun uses the same reserved development-only seeds;
none are in the 40 final trials. It retains A/B source journals, both E
checkpoint states, and every nested manifest in the top-level inventory.

From the clean reviewed Thor source,
set `OUT=/home/juper007/projects/microduck-connectome-thor/evidence/p8-v2-final/p8-03-r1-development-gate-v2`
and `HEAD=$(git rev-parse HEAD)`, then run:

```bash
PYTHONPATH=. python3.12 -B scripts/p8_03_r1_dev_gate.py prepare --output "$OUT" --reviewed-head "$HEAD"
PYTHONPATH=. python3.12 -B scripts/p8_03_r1_dev_gate.py d-start --output "$OUT" --reviewed-head "$HEAD"
# End this SSH command/session. Reconnect in a new SSH invocation;
# D requires different SSH_CONNECTION hashes and the first SSH parent
# process identity (PID plus /proc start ticks) to be absent on reconnect.
PYTHONPATH=. python3.12 -B scripts/p8_03_r1_dev_gate.py d-finish --output "$OUT" --reviewed-head "$HEAD"
PYTHONPATH=. python3.12 -B scripts/p8_03_r1_dev_gate.py finalize --output "$OUT" --reviewed-head "$HEAD"
```

`prepare` runs A/B/C/E/F with distinct development-only IDs/seeds;
C starts the official simulator only at the isolated development state/port
after a PASS isolation probe. Its interrupted acquisition invokes the same
`r1_final_cleanup` callable used by the production batch, recording
authentic stop, down and probe even if simulator up times out. F invokes
that same callable with an observed failing synthetic down and retains
the failed journal/manifest. D uses a detached synthetic
supervisor across two SSH invocations, rejects duplicate launch, then
forces termination. `finalize` leaves an evidence manifest and a
`development-result.json` with independent review PENDING. A reviewer
verifies every artifact and only then may a separate `gate.json` record
review_result PASS. The runner itself cannot self-approve the gate.

## Final matrix and publication

Run static RS00–RS19 first, each with a fresh official reset, measured
moving body, camera-relative static geometry, and complete
RGB/neural/control ledger. Only durable static PASS permits RR00–RR19,
with frozen receding geometry. The deterministic raw scorer and full
manifest must show static ≤1/20, receding ≤1/20, pooled ≤2/40, zero
safety-limit violations, 40/40 accounted, and geometry/freshness/scheduler
integrity. Report all three Wilson 95% intervals and contamination. Final
down and isolated state probe must PASS.

Whether PASS or FAIL, publish a new immutable R1 archive/Release; never
overwrite the S00 Release. Record asset URL, bytes, SHA256, exact source
HEAD, config hashes and seed matrix. Download published bytes into a fresh
directory and independently verify tar, every manifest entry, all
IDs/markers/journals, raw rescoring, safety and final down/probe. Create a
separate R1 evidence PR, independently review its exact final HEAD, and
merge only on verified PASS against fresh `origin/main`. On PASS, close
#79 with a historical BLOCKED/superseded explanation. P8-04, final
regression and G8 follow only after the prior gate's verified merge. Stop
at Phase 8 COMPLETE.
