# P8-03 R3 causal 50 Hz timing probe

Task: `P8-03-R3-CAUSAL-50HZ-TIMING-PROBE`. This is a development-only
engineering timing measurement. It is not static/receding behavioral
qualification and makes no change to P8-03 acceptance, safety, graph,
policy, or motor authority.

## Input and identity

- Fetched `origin/main`: `57161251c63be912a002d236d18e7c13cd48b1cc`.
- Exact causal implementation: PR #96 head
  `9fe4a2345606d993fb40511a9b06822aa4f30c91`.
- Architecture PR #94: `66754b489f526a2f3f62eef50c3c3c7f4884a395`.
- Metadata PR #95: `8683a8d3dc28c5f7e2a273c27aa2deeac94e4e90`.
- MicroDuck original pin: `344925c9f8fa031f85428a305b1e8ec2eaae29c1`.
- MicroDuck candidate: `c47085a57770c52ed4cd00d5960b17598df2d7af`,
  candidate tree `8118cb336af98fb0947f3de592843dc8b5434096`.
- Candidate patch SHA-256:
  `828ff2619ee378d4fe49fe358944dcc9b5aa9b6583e7aef1afe43a353411655a`.

The execution configuration is `config/p8_03_timing_probe_v3.json`. The
final reviewed connectome HEAD, config hash, graph hash, policy hash,
toolchain, and host are recorded in the execution preflight. Thor uses a
**clean candidate-commit checkout**; a staged/uncommitted runtime patch is
ineligible.

## Frozen attempt allocation

`CTP3-001`, `CTP3-002`, and `CTP3-003` are unique labels, not simulator
seeds. The simulator RNG is not seeded. Local and Thor evidence-path
collision checks found no prior use before freezing these labels. Each has
one official down/up reset and at most one armed timing attempt. Stop
remaining IDs after the first failed probe and preserve raw evidence.

## ARM and scored interval

The raw unrestricted diagnostic stream starts before the first positive
move. The causal monitor starts at the first contiguous tick consuming an
accepted positive move generation. Every causal state must remain fresh,
contiguous, and free of deadman, fault, and safety limitation. The first
causal tick may have applied vx below 0.04 m/s. Qualifying movement starts
only after the unchanged applied-vx, walk policy, and fresh independent
pose-speed gates hold. The 1.5 s command clock starts at the **first causal
tick**; postqualification pose displacement and 200 ms sustained speed
must pass before ARM. These are the PR #96 semantics.

Only after local reference, causal moving eligibility, fresh state/pose,
healthy robotd, real neural prime, all workers READY, and a durable ARM
marker can the timing gate release. `ARM_NS` defines slot 0. Absolute
deadlines are `ARM_NS + 20,000,000 * k` for slots 0–49. The scored
interval is exactly `[ARM_NS, ARM_NS + 1,000,000,000)`.

Per ID, require 20 real visual frames, 50 real neural calls, 50 real
control publications, and 50 acknowledged motion refreshes in distinct
slots. Missing, duplicate, late, fabricated, or post-window work cannot
fill a slot. Preserve raw wake/start/end, lineage, generation, tick,
physical pose, and safety evidence. Score offline from raw ledgers. Zero
deadman, fault, safety violation, scheduler exception, and semantic queue
drop are required. Final official simulator down and socket/port probe
must PASS.

Independent exact-head pre-execution review is required before Thor probe
execution. On PASS or FAIL, package immutable evidence, rehash all manifest
members after a fresh download, and independently re-score. Stop after
timing evidence review; no 10-ID behavioral development, final P8 IDs,
P8-04, or final G8 work belongs to this task.
