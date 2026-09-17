# Neural Runtime Soak Test

Task: **P3-07 / G3 remediation**

The frozen neural timestep is 20 ms. Ten minutes of neural execution is exactly **30,000 synchronous steps = 600 seconds neural time**.

Two independent soaks are required:

1. **zero input** — 30,000 steps with no external current;
2. **bounded input** — 30,000 steps with a deterministic bounded pulse every ten steps (`body 1 = 1.0`, `body 200 = 0.75`). This crosses threshold and exercises spike/recurrent propagation.

Both runs use the deterministic 570-node / 21,142-edge synthetic matched-scale graph. The exact executable graph/schedule/timestep/step-count definition is produced by
`microduck_connectome.workload_identity.soak_workload_definition()` and hashed from canonical JSON at runtime.

Current v2 workload SHA256:

`191354438f84809050c7e739964b0a862bac0571451bca8d44db1de17a828c88`

Changing a workload parameter changes the hash and regression tests verify this behavior.

## Pass conditions

Each run must complete all 30,000 steps, remain healthy, encounter no NaN/Inf, and stay below the runtime numerical safety limit. The report records maximum observed absolute state, total spikes, final step count, simulated duration and wall-clock execution time.

The accepted result must come from supported Python 3.12 on the exact reviewed PR head. Wall time is operational context only; the ten-minute requirement is defined by 20 ms x 30,000 updates.

Historical v1 soak evidence is retained. G3 remediation adds v2 evidence tied to the executable workload hash and final supported-environment run.

## Scope

This is numerical/runtime stability on a synthetic matched-scale graph. It does not establish biological validity, actual full-MaleCNS topology performance, closed-loop robot stability, or robot safety.
