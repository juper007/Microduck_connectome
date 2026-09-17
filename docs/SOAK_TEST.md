# Neural Runtime Soak Test

Task: **P3-07 / G3 remediation**

The frozen neural timestep is 20 ms. Ten minutes of neural execution is exactly **30,000 synchronous steps = 600 seconds neural time**.

Two independent soaks are required:

1. **zero input** — 30,000 steps with no external current;
2. **bounded input** — 30,000 steps with a deterministic bounded pulse every ten steps (`body 1 = 1.0`, `body 200 = 0.75`). This crosses threshold and exercises spike/recurrent propagation.

Both runs use the deterministic 570-node / 21,142-edge synthetic matched-scale graph. The exact executable graph/schedule/timestep/step-count definition is produced by
`microduck_connectome.workload_identity.soak_workload_definition()` and hashed from canonical JSON at runtime.

Current graph content SHA256:

`2ba657e747e1680281572200dcee4fa239aabcccba028f28ac8360c8587847e0`

Current workload SHA256:

`867ff65644878af73d01873ed104e80e39827a6bb1ac91c845d891bf16c8b06c`

Changing generated graph content or another workload parameter changes the identity and regression tests verify the binding.

## Pass conditions

Each run must complete all 30,000 steps, remain healthy, encounter no NaN/Inf, and stay below the runtime numerical safety limit. The report records maximum observed absolute state, total spikes, final step count, simulated duration and wall-clock execution time.

The accepted result must come from supported Python 3.12 on the exact reviewed PR head. Wall time is operational context only; the ten-minute requirement is defined by 20 ms x 30,000 updates.

Historical v1/v2 evidence is retained. The current G3 remediation result is `soak-v3.json`, bound to the executable workload and generated graph-content identity.

## Scope

This is numerical/runtime stability on a synthetic matched-scale graph. It does not establish biological validity, actual full-MaleCNS topology performance, closed-loop robot stability, or robot safety.
