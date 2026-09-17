# Sparse Neural Runtime

Task: **P3-02**

`SparseNeuralRuntime` implements the P3-01 synchronous discrete-time model over a bounded `ConnectomeGraph`-compatible object.

## Execution

- body IDs must be unique, positive and ascending;
- stored `normalized_weight` values are consumed as-is;
- no runtime-subgraph renormalization occurs;
- recurrent input uses only the previous step spike vector;
- all candidates are computed before any next-step spike/reset state is committed;
- zero external input applies only leak + recurrent input.

## Safety / health

The runtime starts healthy and becomes unhealthy if a step receives an unknown body ID, non-finite/non-numeric external value, non-finite/excessive neural state, or arithmetic overflow. Once unhealthy, stepping is rejected until `reset()` is called.

`reset()` restores zero membrane-like state, no spikes, step count zero and healthy status.

`max_abs_state` is a local numerical safety bound, not a biological parameter and not a robot safety threshold.

## Scope

P3-02 deliberately does not define sensory-population stimulation, rolling population readout, robot intents, scheduling, performance acceptance or soak acceptance. Those remain P3-03 through P3-07.
