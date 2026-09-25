# P8-02 feasibility blocker — frozen graph cannot express looming escape

**Proposed task status: BLOCKED, pending independent exact-head review.** No P8-02 final trial, preregistered final manifest, or G8 result was produced.

## Scope and frozen identities

Work began from freshly fetched `origin/main` `1ed286c3f7c223057ae1419979ad6c064f756a0a` on isolated branch `experiment/p8-02-looming-stop`. The audit uses the merged P8-01 [virtual scenario](../p8-01/README.md): synthetic visual sphere, official robot pose for evaluator truth, center-distance boundary 0.25 m, no MuJoCo obstacle contact. It does not send a robot command. The [machine summary](feasibility-blocker.json) has all full SHA-256 identities and three deterministic condition outcomes.

| Frozen input | SHA-256 or identity |
| --- | --- |
| Selected graph key/file SHA-256 | `340f6a3180026f6c61f19ebc016ae8610ec9f4a07af2af589e4d6d89e5b31f70` |
| Sorted selected graph body-ID membership SHA-256 | `e9bfa8d271405ddab9197e6794a3a3daabe724e9724d155c85114cae829ad003` (570 nodes) |
| P8-01 scenario config | `3967c2efa327c0a69a6f9629a12ac0c80f38a7ca6b02b4e9aceecd4cbd53c9eb` |
| P7 v4 manifest | `f24170521f049cec6a65a88285925343316f84ce9bdaf59a1a668257db5460cd` |
| Model1250 ONNX, hash checked on disk | `98c3ea73fa6bb196bcf16586cf38b9fffb782787447d638fa1c1028df9082c1a` |
| Sensory mapping / DN readout | `241fa094a5ab1da5834019039ae976387f9cdb72461431129a42b7c0f84c913f` / `9d171cd17d548fa51bbf5c8fbd807d01fc7297f39366bb53ebe361e6a130d291` |
| Escape decoder / motion adapter | `932ec651a595f1f98bdabd4d42d76297d95c9ba43d7ffeea5bdb84d4d1343547` / `a5aa8d9360379db8a032e526c7d7ed43135b06daf52ced17f80d74ea156e39ee` |
| Audit script, committed source SHA | `cc1251de6a5ebc412667b012828efdb9ddc29c98c00a257beb91dddac7bc4f3f` / `8082f4be5a76458982974926f257b6fcc990c08b` |

Graph cache path: `/home/juper007/projects/microduck-connectome-thor/g1-bfddc98/results/run1/graphs/340f6a3180026f6c61f19ebc016ae8610ec9f4a07af2af589e4d6d89e5b31f70.json`. The loader verifies the expected key/integrity; the file SHA equals the key.

## First broken stage and downstream consequence

1. [P4 sensory mapping](../../../microduck_connectome/sensory_mapping.py) lines 152–157 maps perceived looming equally to bilateral LPLC2 channels. The committed sensory config lists **185** LPLC2 body IDs; **0/185** are present in the selected graph. [P6 FullChain](../../../scripts/p6_telemetry_runtime_fixture.py) line 171 filters mapped inputs to graph nodes, so the looming-specific LPLC2 stimulus is discarded **before the neural runtime**.
2. Frozen [DN readout](../../../config/dn_readout_v1.json) lines 21–27 uses bilateral DNp01 IDs **10001 and 10010** for escape. Neither is in the selected graph. [FullChain](../../../scripts/p6_telemetry_runtime_fixture.py) lines 173–175 substitutes `False` for missing readout IDs; [aggregator](../../../microduck_connectome/dn_aggregator.py) line 152 therefore cannot report a stimulus-driven escape signal.
3. [EscapeDecoder](../../../microduck_connectome/escape_decoder.py) lines 67–74 asserts a stop on unhealthy runtime, escape >= frozen 0.5 after gain, or an upstream base stop. With a healthy runtime and escape fixed at zero, the looming stimulus cannot assert the intended stop. A watchdog/fault/shutdown stop is a safety action and would not be a **valid looming trigger before the boundary**.
4. The robot-facing [motion adapter](../../../config/motion_adapter_v1.json) line 6 remains sealed to `robot_stop`; the [client](../../../microduck_connectome/robotd_client.py) lines 173–246 sends/refreshes that high-level stop. The exact model1250 ONNX and prior official P6 recertification summary SHA `1183d980e1a1f267cd05d1645049266f05c4503497f02eb21c9a4b68b7affbea` establish policy load/motion/acknowledged stop on the previous task's tested path. They cannot repair absent graph nodes. No new stop transport or direct motor control is proposed.

## Reproducible offline trace

Run, without simulator or hardware:

```sh
PYTHONPATH=. python3.12 scripts/p8_02_feasibility_audit.py \
  --root . \
  --graph-cache /home/juper007/projects/microduck-connectome-thor/g1-bfddc98/results/run1/graphs \
  --output docs/evidence/p8-02/feasibility-blocker.json
```

The script uses `FullChain` unmodified: P8-01 RGB pixels → P4 `PerceptionPipeline` → LPLC2 mapping → selected MaleCNS runtime → DN aggregator → `EscapeDecoder` → frozen safety clamp. It replays **201 ticks at 20 ms** for each fixed-pose seed (approach 80101, static 80102, receding 80103). The 20 ms replay samples are an offline interface check, not an official robotd motion trial. Pixel quantization and simulator timing cannot restore missing graph nodes.

| Condition | Peak P4 looming | Peak LPLC2 channel | Graph spikes total | Peak DN escape | Neural stop-intent ticks | First nonzero looming |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Approaching | 1.0 | 1.0 | 843 | 0 | 0/201 | 0.76 s |
| Static | 0 | 0 | 0 | 0 | 0/201 | none |
| Receding | 0 | 0 | 0 | 0 | 0/201 | none |

The approaching virtual boundary is passed by the uncommanded offline trajectory at 4 s (margin −0.0995 m). This is **not a robot collision or stop result**. No target truth, class, distance, or boundary is sent to the perception/controller chain. The precise first loss is LPLC2 at graph input; the absent DNp01 output is a second independent structural break.

## Decision and next dependency

The frozen Behavior B threshold remains ≥0.95 valid looming triggers before the boundary, false-positive rate ≤0.05, safety violations 0. P8-02 cannot honestly preregister and execute a final batch as a feasible neural-chain stop experiment with the current selected graph. Graph expansion or readout remapping would be a separate versioned, independently reviewed task with renewed P6/P7 safety and behavioral validation as appropriate; this branch changes **no** graph, biological IDs, decoder threshold, safety envelope, P7 steering, policy or stop transport. P8-03/04, G8 and Phase 9 were not started. Reviewer determination on this exact head is pending.
