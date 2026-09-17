# MVP Neural Model Runtime Contract

Task: **P3-01**  
Frozen source specification: `docs/preflight/NEURAL_MODEL_SPEC.md` version **P-1.1**  
Executable configuration: `config/neural_model_v1.json`

## Scope

P3-01 fixes the meaning of one neural step before P3-02 implements sparse graph execution. It is an engineering model over MaleCNS-derived connectivity, not a biophysical simulation of a fly nervous system.

This task does **not** implement sparse propagation, sensory injection, population readout, robot intent, or any actuator interface.

## State and initialization

For each selected MaleCNS body ID `i`, the runtime state is:

- membrane-like scalar state `u_i`, represented as `float32` by the MVP runtime;
- spike state `spike_i`, represented as boolean;
- initial state is exactly `u_i[0] = 0` and `spike_i[0] = false`.

There is no random initialization and no plasticity in the MVP.

## One synchronous step

Given state at step `t`, bounded external input `external_i[t]`, and the P1 graph's stored normalized edge weights:

```text
candidate_i = alpha * u_i[t]
              + external_i[t]
              + recurrent_gain * sum_j(W[j,i] * spike_j[t])

spike_i[t+1] = candidate_i >= threshold

u_i[t+1] = reset_value  if spike_i[t+1]
             candidate_i  otherwise
```

All `candidate_i` values are computed from the **previous-step** spike vector `spike[t]`. A spike produced during step `t -> t+1` cannot influence another neuron until the following step. There is no neuron-order-dependent cascade inside one step.

Reset occurs after threshold comparison in the same synchronous step. The emitted `spike_i[t+1]` remains true for that discrete step even though `u_i[t+1]` is reset.

## Frozen MVP invariants

The machine-validated config requires:

- model family `discrete-time-lif-like`;
- neural model spec version `P-1.1`;
- synchronous updates using previous-step recurrent spikes;
- unsigned recurrent weights;
- normalization scope `full_source_before_subgraph_filtering`;
- deterministic execution contract;
- no plasticity;
- zero initial state;
- `float32` state and boolean spikes.

Changing these invariants is outside P3-01. Changes covered by the preflight review list require an ADR and independent review.

## Weight contract

`W[j,i]` is the P1 normalized edge weight whose denominator is the presynaptic neuron's complete retained-confidence outgoing weight in the pinned source graph **before runtime-subgraph filtering**. P3-02 must consume that stored value and must not renormalize a smaller runtime subgraph.

The recurrent graph remains non-negative for the MVP. Neurotransmitter predictions may be retained as metadata but do not become signed recurrent effects here.

## Default parameter set

`config/neural_model_v1.json` records the P-1.1 defaults:

```text
timestep_ms = 20
alpha = 0.90
threshold = 1.0
reset_value = 0.0
recurrent_gain = 1.0
state_dtype = float32
spike_dtype = bool
deterministic = true
plasticity = false
```

The numeric defaults may be changed for development fixtures only through a versioned, validated config. Evaluation parameters must be frozen before comparative results are collected.

## Validation and identity

`microduck_connectome.neural_model` validates the config without third-party dependencies and computes SHA-256 over canonical JSON. The hash is a parameter/config identity only; a complete run identity must additionally record dataset version, source/filter config hash, graph extraction hash, code commit, seed, and backend as required by P-1.1.

The validator intentionally fails closed for non-finite numbers, invalid types, nondeterministic/plastic settings, signed weights, subgraph renormalization semantics, asynchronous updates, same-step recurrent spikes, or random initialization.

## Handoff to P3-02

P3-02 may implement a sparse CPU backend against this contract. It must separately prove graph-shape validation, deterministic stepping, zero-input behavior, bounded-input behavior, state reset, NaN/Inf handling, and runtime-health reporting. Performance and long-soak gates remain P3-05 through P3-07 concerns.
