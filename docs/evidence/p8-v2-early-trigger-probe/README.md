# P8-v2 early trigger development probe

Task: `P8-V2-EARLY-TRIGGER-PROBE`  
Primary skill: `$microduck-integration-engineer`  
Base `origin/main`: `34b48af891c508f83bf50eb9f8accd1f0a57bd22`  
Branch: `experiment/p8-v2-early-trigger-probe`  
Worktree: `C:\projects\Microduck_connectome\.worktrees\p8-v2-early-trigger-probe`

Supporting skills used in the task: `$robot-safety-engineer` reviewed stop
transport and lock ordering; `$perception-sensory-encoder` and
`$neural-runtime-engineer` provided read-only visual/neural raw-trace analysis;
`$experiment-evaluation-scientist` and `$reproducibility-devops-engineer`
receive this quantitative, hashed development handoff for preregistration.
Input identities: MaleCNS `male-cns:v1.0`, MicroDuck
`344925c9f8fa031f85428a305b1e8ec2eaae29c1`, microduck_rl
`cb70b792312d559a4da09064d92009079671815f`, graph SHA256
`c4160c42941163079b6b569d117bf67afcf8b45eaa128c444f7c96c2567593cc`.

This is development evidence for P8-v2 preregistration. None of these seeds
or responses count toward a final P8-02 benchmark. The frozen virtual center
distance boundary remains 0.25 m. The official MuJoCo body and robotd run on
Thor; virtual obstacle geometry is evaluator-only.

## Version 1: short observation windows

Frozen source: `8a065068ef621a3ec5f9e57ab759bee4213d4e03`  
Protocol: `config/p8_early_trigger_probe_v1.json`  
Protocol SHA256: `7e9b06db255a1852d87e58062b00e004249c7848d3d8b8c3e15ccb339acc53e8`  
Remote raw: `/home/juper007/projects/microduck-connectome-thor/evidence/p8-v2-early-trigger-probe/dev-8a06506-20260925-1/`  
Manifest: `v1-raw-manifest.json` (SHA256
`286cf34ce08968bbd02db5359e34253f897b4ec6afe921b0be0de2670fd65637`)

| Seed | Arm time | Frozen neural window | Healthy neural stop | Result |
| --- | ---: | ---: | --- | --- |
| 880901 | 2.4 s | 650 ms | None | FAIL |
| 880902 | 2.6 s | 650 ms | None | FAIL |
| 880903 | 2.8 s | 650 ms | None | FAIL |

All three started trials are retained. Each had 32 acknowledged positive
motion refreshes, 18 visual frames with maximum frame gap below 41 ms, and
zero safety limit violations. There was no `robot.stop` ACK before the frozen
neural observation deadline. The ledger contains positive looming/LPLC2 and
up to 0.2 DN escape activity, below the unchanged 0.5 stop threshold.
`batch-summary.json` and all event, neural, visual, policy, and simulator logs
are covered by the manifest. Simulator final down returned successfully.

## Version 2: earlier arm

Frozen source: `186ed8a9f8c2774334907589e84cc86fa53e4d51`  
Protocol: `config/p8_early_trigger_probe_v2.json`  
Protocol SHA256: `58ba4764f43bc2013da002323aa5449388d9e881c4f8f8fd78a95fbfec91d538`  
Remote raw: `/home/juper007/projects/microduck-connectome-thor/evidence/p8-v2-early-trigger-probe/dev-v2-186ed8a-20260925-2/`  
Manifest: `v2-raw-manifest.json` (SHA256
`221b6e328620d964eb9ccaf6ef364410f71ffebff5c7530029d904f71414e4ed`)

Seed 880904 started at arm 2.0 s, with a 1000 ms observation window. The
canonical initial center distance was 0.5424428 m. First positive looming and
LPLC2 were at measured boundary margins 0.2522021 and 0.2479030 m; DN escape
reached only 0.2, below the unchanged 0.5 decoder threshold. There was no
healthy neural stop. All 50 motion refreshes were acknowledged with maximum
request gap 22.83 ms, 27 visual frames had maximum gap 40.09 ms, safety
violations were zero, and final simulator down exited 0. Result: **FAIL**.

The first v2 command stopped before any trial because its output directory had
been precreated. Its raw command log and empty output directory are retained
under `dev-v2-186ed8a-20260925-1/`, with
`v2-launch-raw-manifest.json` (SHA256
`66c3b4f5fa7bbc5f7799d079d121ddd8c5ec9f9aad857d31b7929f0cef964b43`).

## Version 3: near-field arms

Frozen config: `config/p8_early_trigger_probe_v3.json` (SHA256
`4ffa630cccd979705862f4812ff25e6679e32673832af39be83c462cd06a651b`).
The first source `9d1fe840fc0775fecca89daa6b63e97532fa6c6c` accepted the
CLI version but rejected v3 in the trial verifier. Both official fresh resets
therefore exited before neural observation or a trial summary. This is an
infrastructure failure, not two unsuccessful neural trials. The raw batch,
trial logs, and final down are retained under `dev-v3-9d1fe84-20260925-1/`
with `v3-preflight-raw-manifest.json` (SHA256
`55124f79cc421b1ec59cccb52bbc82065eedd464c49cd1f6224f6ee75625e099`).

The corrected version guard was frozen at
`666b3b1680663d66dcc5d6c69cf17781f730b740`. The same dev seeds then ran
under `/home/juper007/projects/microduck-connectome-thor/evidence/p8-v2-early-trigger-probe/dev-v3-666b3b1-20260925-2/`;
`v3-raw-manifest.json` SHA256 is
`9fbbde32e2319e1f887eb299b4b5fc0c168b71aff1ef50287fc20f2db91acd07`.

| Seed | Arm time | First LPLC2 margin | DN peak | Neural stop margin | Result |
| --- | ---: | ---: | ---: | ---: | --- |
| 880905 | 3.0 s | +0.074706 m | 0.6 | −0.038122 m | FAIL: late trigger; no pose stop confirmation before deadman limiter |
| 880906 | 3.1 s | +0.070423 m | 0.4 | None | FAIL: no neural stop in 700 ms |

For seed 880905, actual pose speed and robot.state applied velocity were
positive before the first neural stop. The final pre-stop `robot.move` ACK was
16.12 ms before the first `robot.stop` ACK. There were zero positive move
requests after the motion arbiter latched and zero positive move ACKs after the
first stop ACK. Acknowledged `robot.stop` requests occurred at +0, +23.03, and +40.52
ms. Continued RGB then produced a non-stop WatchdogOutput. The isolated
publisher rejected this **attempted** non-stop publish; `post_stop_move_count=1`
does not mean a `robot.move` RPC reached robotd. The scheduler stopped
refreshing. Applied vx first declined at +32.81 ms and reached near zero at
+192.06 ms; pose speed first met the stopped threshold at +492.93 ms, without
the required 200 ms sustained confirmation. A robotd deadman limiter appeared
at +552.76 ms, before stopped confirmation. Body cessation cannot be credited
to maintained neural stop. Seed 880906 had no stop. Both trials had zero
safety-limit violations and the simulator final down exited 0.

## Conclusion and next dependency

Across six development neural-observation trials, there were **zero healthy
neural stops before the frozen 0.25 m boundary**. One stop was healthy but
late, and its stop refresh did not persist through actual stopped confirmation
with continuous visual input. The current 65×33 RGB presentation and
unchanged neural/decoder path are not established as feasible for P8-02's
early-boundary acceptance. P8-v2 final protocol must remain unfrozen pending a
separate versioned sensory/presentation remediation with new development seeds.
That remediation must also latch the first neural stop through authentic
decoder, SafetyClamp, Watchdog, and RobotMotionAdapter outputs until
pose-derived cessation while RGB continues. Do not tune the graph, frozen
boundary, decoder threshold, or these retained results in place.

All six attempted observation trials, both preflight reset failures, the
zero-trial launch error, and their raw logs are preserved. The manifests list
relative path, byte count, JSONL record count, and SHA256 for every raw file.
`v1-batch-summary.json`, `v2-batch-summary.json`, and
`v3-batch-summary.json` contain the per-trial metrics and source identities.
These development failures do not count toward P8-02 final statistics.

## Reproduction and validation

The commands below run on Thor in an isolated source checkout with the pinned
official MicroDuck and microduck_rl directories. Each output path must be new;
the harness refuses an existing output directory and creates it itself. Use a
dedicated `DUCK_SIM_STATE` and body port for serial simulator ownership.

```sh
R=/home/juper007/projects/microduck-connectome-thor/p8-v2-early-trigger-probe
B=/home/juper007/projects/microduck-connectome-thor
cd "$R"
python3.12 -m unittest tests.test_p8_probe_motion_arbiter tests.test_p8_early_probe_protocol tests.test_g8_r5d_fixture tests.test_g8_r5d_metrics -q
PYTHONPATH="$R" python3.12 -m scripts.p8_early_trigger_probe_batch \
  --root "$R" --microduck "$B/microduck" --microduck-rl "$B/microduck_rl" \
  --output "$B/evidence/p8-v2-early-trigger-probe/NEW-UNUSED-OUTPUT" \
  --sim-state /tmp/p8-early-probe-state --body-port 7897 \
  --protocol-version 3 --development-probe
```

Local and Thor Python 3.12 test runs each passed 28 tests for frozen source
`666b3b1`; `git diff --check` and `py_compile` passed. Every development
batch's final `duck-sim down` exited 0. Independent exact-head review,
current-main freshness check, PR status, and merge status are recorded in the
handoff after submission. This historical FAIL evidence must remain unmerged.
