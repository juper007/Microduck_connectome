# Neural Runtime Soak Test

Task: **P3-07**

The frozen neural timestep is 20 ms. P3-07 therefore defines ten minutes of neural execution as exactly **30,000 synchronous steps = 600 seconds neural time**.

Two independent soaks are required:

1. **zero input** — 30,000 steps with no external current;
2. **bounded input** — 30,000 steps with a deterministic bounded pulse every ten steps (`body 1 = 1.0`, `body 200 = 0.75`). This intentionally crosses threshold on body 1 and repeatedly exercises spike/recurrent propagation.

Both runs use the deterministic 570-node / 21,142-edge synthetic matched-scale graph from P3-06. Workload SHA256:

`5cc7f9e8801359c995538fc8f65ede403ce647808d9a82a9d54a98fff7591bdb`

## Pass conditions

Each run must complete all 30,000 steps, remain healthy, encounter no NaN/Inf, and stay below the runtime's configured numerical safety limit. The report records maximum observed absolute state, total spikes, final step count, simulated duration and wall-clock execution time.

The accepted result must come from supported Python 3.12 on the exact reviewed PR head. The wall time is reported for operational context but **does not define the ten-minute requirement**; 600 seconds of neural time is defined by the frozen 20 ms timestep and 30,000 updates.

## Scope

This is a numerical/runtime stability test on a synthetic matched-scale graph. It does not establish biological validity, whole-CNS topology performance, closed-loop robot stability, or robot safety.
