# Neural Model Specification

Status: **FROZEN for MVP implementation**  
Version: P-1.1  
Date: 2026-09-15

## 1. Modeling principle

MaleCNS provides anatomical connectivity, not a complete executable nervous system. The MVP therefore uses an explicitly engineered dynamical model whose assumptions are visible and testable.

The runtime must always be described as a **MaleCNS-derived network model** or **connectome reservoir**, not as a faithful simulation of the living fly brain.

## 2. MVP model class

The first implementation uses a deterministic discrete-time leaky integrate-and-fire-like model over a weighted directed graph.

For neuron `i` at step `t`:

```text
u_i[t+1] = alpha * u_i[t]
           + external_i[t]
           + recurrent_gain * sum_j(W[j,i] * spike_j[t])

spike_i[t+1] = 1 if u_i[t+1] >= threshold else 0

if spike_i[t+1] == 1:
    u_i[t+1] = reset_value
```

This equation is an engineering abstraction. It does not claim to reproduce fly membrane biophysics.

## 3. Default parameters

Initial defaults:

```yaml
timestep_ms: 20
alpha: 0.90
threshold: 1.0
reset_value: 0.0
recurrent_gain: 1.0
state_dtype: float32
spike_dtype: bool
deterministic: true
plasticity: false
```

These defaults may be tuned during development fixtures, but the values used for benchmark/evaluation runs must be frozen in versioned configuration before comparative results are collected.

## 4. Graph representation

Each neuron is keyed by the MaleCNS v1.0 body ID.

Each directed edge stores at minimum:

```text
source_body_id
target_body_id
raw_synapse_weight
normalized_weight
source_type
target_type
provenance_dataset
```

The graph extraction must preserve the exact raw MaleCNS connection weight even when the runtime uses a transformed weight.

## 5. MVP weight normalization

For the MVP, incoming dynamics use a **non-negative unsigned graph** so that uncertain neurotransmitter/receptor interpretation is not silently converted into biological fact.

For each presynaptic neuron `j`:

```text
full_outgoing_sum[j] = sum_k(raw_weight[j,k])
                       over all retained-confidence outgoing MaleCNS v1.0 edges
                       in the source graph, before subgraph filtering

W[j,i] = raw_weight[j,i] / full_outgoing_sum[j]
```

**Normalization scope is the pinned source graph, not the extracted runtime subgraph.** This is mandatory so that an edge keeps the same normalized weight when the same neuron is evaluated in a small pathway subgraph versus the full graph.

The graph manifest must record the confidence/filter rules used to define the source graph whose outgoing sums are used.

Properties:

- relative outgoing routing from a neuron is preserved,
- a high raw synapse count remains more influential relative to that neuron's other targets,
- the total outgoing contribution of each firing neuron is bounded in the full source graph,
- subgraph extraction does not renormalize surviving edges and therefore does not silently amplify them,
- stability is easier to reason about than with raw unnormalized synapse counts.

If a source neuron has no outgoing edges after the frozen source-graph confidence/filter rules, its row contributes zero.

## 6. Neurotransmitter handling

MaleCNS provides neurotransmitter predictions for many neurons. These predictions are retained as metadata, but **MVP recurrent signs are unsigned**.

Reasons:

- transmitter identity alone does not fully determine postsynaptic sign in every case,
- glutamatergic and neuromodulatory effects cannot safely be reduced to a universal sign without additional receptor/context evidence,
- the first scientific question concerns whether the real topology is useful, so topology should be separated from a second hypothesis about synaptic sign.

A future signed-network experiment may be added as an explicit model variant. It must not retroactively replace the MVP definition without an ADR and review.

## 7. Sensory injection

Sensory encoders inject bounded external current/activity into configured populations.

Required rules:

- injection amplitude is normalized to `[0, 1]`,
- left/right populations are configured explicitly, not inferred from array order,
- injection is zero when source observations are stale or invalid,
- an encoder cannot set neuron internal state directly; it uses the public injection interface,
- maximum injection per population is configuration-limited.

## 8. Readout

A readout is computed from a named population over a rolling time window.

MVP default:

```yaml
readout_window_ms: 100
aggregation: spike_count_per_neuron_then_mean
```

For steering:

```text
steering_signal = activity_left - activity_right
```

The sign that maps this signal to robot yaw is defined in `INTERFACE_AND_TIMING_CONTRACT.md` and verified by an integration fixture before autonomous trials.

## 9. Runtime scope

The runtime must support two execution modes:

### Subgraph mode

Used for early pathway bring-up and unit/integration tests. The extracted graph contains selected sensory populations, candidate downstream paths, and readout neurons.

Subgraph mode uses the same source-graph normalization constants as full-graph mode; it must never renormalize surviving edges merely because other nodes were removed.

### Full-graph mode

Used once data/runtime performance is validated. The architecture must not make subgraph-only assumptions that prevent full MaleCNS execution later.

MVP acceptance does not require full whole-CNS real-time operation if a scientifically documented, reproducibly extracted subgraph closes the first vertical loop.

## 10. Timing and deterministic behavior

- Nominal neural timestep: 20 ms.
- State update is synchronous within one neural step.
- Fixed input trace + fixed graph + fixed config + fixed seed must produce identical spike/readout traces on the same supported backend.
- No online learning/plasticity in MVP.
- Random initialization, if any, must use an explicit seed and be logged.

## 11. Numerical safety

The runtime must fail closed on invalid state.

Required checks:

- reject non-finite external input,
- detect NaN/Inf neuron states,
- enforce configured maximum state magnitude before catastrophic growth,
- produce no robot intent directly,
- publish a runtime-health flag so the downstream safety gate can neutralize stale/failed output.

A 10-minute zero-input and bounded-input soak test must complete without NaN/Inf before the runtime passes its phase gate.

## 12. Performance gates

Primary target:

```text
nominal neural update rate: 50 Hz
preferred p95 neural step latency: <= 18 ms
```

The 18 ms target leaves scheduling/IPC margin relative to the 20 ms MicroDuck control period.

If full-graph p95 exceeds 18 ms, the connectome runtime must run asynchronously rather than blocking `robotd`. A multi-rate fallback is permitted with:

```text
minimum connectome update rate: 20 Hz
maximum neural-output age accepted by control: 100 ms
```

The MicroDuck control loop itself remains owned by `robotd` and is never slowed by this project.

## 13. Model-version identity

Every run must record:

```text
MaleCNS dataset version
source-graph confidence/filter config hash
graph extraction hash
neural model spec version
parameter config hash
code commit SHA
random seed
runtime backend (CPU/GPU)
```

## 14. Model changes requiring review

The following require an ADR + independent review:

- changing unsigned to signed recurrent weights,
- adding plasticity,
- changing normalization family or normalization scope,
- changing source-graph confidence/filter rules used by normalization,
- changing timestep semantics,
- using asynchronous neuron updates,
- adding learned recurrent weights,
- replacing the LIF-like model family,
- changing evaluation parameters after benchmark results are observed.

## 15. Preflight exit criteria

- [x] neuron dynamics are explicit,
- [x] edge normalization and source-graph scope are explicit,
- [x] subgraph/full-graph normalization consistency is required,
- [x] neurotransmitter treatment is explicit,
- [x] sensory input interface is bounded,
- [x] readout semantics are explicit,
- [x] deterministic/reproducibility requirements are explicit,
- [x] timing targets and asynchronous fallback are explicit,
- [x] claims are limited to a MaleCNS-derived model.
