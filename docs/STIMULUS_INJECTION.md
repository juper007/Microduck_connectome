# Stimulus Injection Contract

Task: **P3-03**

`StimulusInjector` is a pure adapter from named sensory populations to the external-input mapping accepted by `SparseNeuralRuntime.step()`.

## Population configuration

Each population must declare:

- explicit `body_ids` present in the current runtime graph;
- explicit side metadata: `L`, `R`, or `M`;
- `max_amplitude` in `[0, 1]`.

MVP population body-ID sets must not overlap. This avoids hidden summation/order semantics; a future overlapping mapping would require an explicit aggregation contract.

## Input semantics

Stimulus amplitudes must be finite values in `[0, 1]`. Values above a population's configured maximum are capped to that maximum. A zero amplitude is omitted from the returned mapping.

When the source observation is stale or invalid, the adapter returns an empty mapping so the neural runtime receives zero external injection.

## Architecture boundary

The adapter has no reference to neural membrane/spike state and cannot mutate it. It only returns a detached `body_id -> amplitude` mapping for the public runtime step interface.

This task does not define camera/ToF feature extraction, timestamps/TTL evaluation, population readout, behavior decoding or robot commands.
