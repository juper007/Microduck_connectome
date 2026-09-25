# P8-01 — virtual visual looming scenario evidence

**Status:** P8-01 implementation and official Thor smoke passed; final independent exact-head review pending. This record does not establish P8-02 stop behavior or G8.

## Frozen setup

- Source: `feature/p8-01-looming-scenario`, base `origin/main` `367fed5522c4b4ca974c170fb9972fea2c0627f9`; scenario source commit `71ccff579c4a446d97f6a5a10d23f91352e40e56`.
- Official upstream: MicroDuck `344925c9f8fa031f85428a305b1e8ec2eaae29c1`; microduck_rl `cb70b792312d559a4da09064d92009079671815f`; pinned scene XML SHA-256 `9a85461121ba8273083c482c166f27e143ca386993b3ec8f8d97eb09aa257d31`.
- [Scenario config](../../../config/looming_scenario_v1.json) SHA-256 `3967c2efa327c0a69a6f9629a12ac0c80f38a7ca6b02b4e9aceecd4cbd53c9eb`; [three-seed manifest](../../../config/looming_scenario_smoke_v1.json) SHA-256 `00e73e09902a59da52c27f940292df53f1d8a454825c39d9b25771097a7849c7`.
- A **world-anchored virtual sphere** is drawn into synthetic RGB pixels from official MuJoCo trunk x/y/heading. It is a virtual/synthetic visual obstacle; there is **no MuJoCo obstacle body or contact**. The existing ToF input remains a far fixture (2000 mm), not an obstacle-distance signal.
- Evaluator-only truth uses the same official trunk pose and virtual sphere world trajectory to calculate center distance, boundary margin and stationary-robot time-to-boundary. The controller perception pipeline receives only RGB pixels and the far ToF fixture; class, world position and distance are calculated/logged outside that call. A missing/nonfinite official pose fails closed.
- Frozen center-distance boundary: **0.25 m** = 0.1162391645 m nominal STAND robot planar extent + 0.0037608355 m rounding allowance + 0.07 m virtual sphere radius + 0.06 m additional margin. Extent was measured from pinned MuJoCo STAND keyframe as the maximum planar distance from trunk origin to each nonworld geom center plus its `geom_rbound`. This is a nominal-pose estimate; it does not prove a dynamic swept envelope, physical contact, or hardware clearance. Boundary was frozen before any P8-02 result.
- Initial center distance 0.85 m plus seeded axial jitter up to 0.01 m; warmup 0.5 s; approach/static/recede along the initial trunk forward axis at −0.20/0/+0.20 m/s; 4.0 s duration; 10 Hz rendered frames. Three fixed seeds 80101–80103.

## Official Thor smoke

An isolated official `duck-sim` state `/tmp/p801-looming-state`, body port 7888 and real robotd were used. Each of two independent `duck-sim up` cycles replayed all three conditions (123 raw frames per reset). Robotd health and official pose were read before/during/after each run; no motion or stop command was issued. The final `duck-sim down` completed and port 7888 was closed. The first up command returned healthy robotd but printed a policy-fetch shell warning; because this read-only smoke does not load/command a walking policy, that warning does not validate policy readiness for P8-02.

| Condition | Reset 1 boundary margin, first→last (m) | Reset 2 (m) | P4 looming peak (resets 1/2) |
| --- | ---: | ---: | ---: |
| Approaching | 0.6005 → −0.0995 | 0.6005 → −0.0995 | 0.8021 / 0.8028 |
| Static | 0.6095 → 0.6094 | 0.6095 → 0.6094 | 0 / 0 |
| Receding | 0.5999 → 1.2998 | 0.5999 → 1.2998 | 0 / 0 |

Static measured margin changes by ~0.00007 m because the official standing robot pose drifts slightly. Deterministic fixed-pose unit tests show strictly decreasing/static/increasing distance and replay-identical pixels; official replay initial pose differed by at most 0.00031 m x/y and 0.00172 rad heading, within the frozen tolerances. The approaching virtual boundary crosses because this is a scene smoke **without a controller stop trial**. P8-02 must demonstrate actual robot.stop before the evaluator boundary under separately preregistered trials; no collision conclusion follows from this smoke.

[Machine-readable smoke summary](smoke-summary.json) SHA-256 `067d9241b467d956786d51a28afa1559c74983e398bdd4901b3b18e24f54891f` lists every external raw/log path and SHA-256. Raw and summaries are durable under `/home/juper007/projects/microduck-connectome-thor/evidence/p8-01/20260924T-scenario-smoke`: reset1 raw `867e1a3f92ef08a2147a81c5bbbe2f0b1c2904ac6f57384a1139c50f3a83a97c`, summary `cd548435b5da77745a83be901a116fde51be67998d34f6eed419cd797fc16974`; reset2 raw `7dfc8752e45df0c46ac2a7c3b6f55cb6b91d658b39137642d9d14026148505`, summary `855bbc5c716e52f82850b4dadfee1f04c38636d9a626659ffc033d5412e0595e`. No P8-02 final seeds or results exist.

## Verification and limits

`python3.12 -m unittest -q tests.test_looming_scenario`: 4 tests passed. `python3.12 -m py_compile scripts/p8_looming_scenario_smoke.py` and `git diff --check` passed. Tests cover frozen manifest/boundary, seed/reset deterministic pixels, approach/static/recede distance and image-area direction at fixed official pose, perception-only input, pose dependence, and malformed/nonfinite pose rejection. Reviewer must verify exact final head before P8-01 PASS. Neither looming response nor G7 residual graph coverage proves a MaleCNS causal mechanism.

Known constraints: synthetic RGB does not include occlusion, rendered decoys, lighting, MuJoCo obstacle contact, or a ToF return from the virtual obstacle. The read-only scenario does not test reaction latency, stop transport, safety, physical collision, or hardware.
