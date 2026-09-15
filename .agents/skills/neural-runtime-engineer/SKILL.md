---
name: neural-runtime-engineer
description: Design, implement, test, and profile the MaleCNS-derived temporal neural runtime for MicroDuck Connectome. Use for LIF/leaky dynamics, sparse graph execution, stimulation/readout timing, determinism, numerical stability, CPU/GPU profiling, or multi-rate runtime decisions.
---

# Neural Runtime Engineer

## Mission
Create a simple, explicit, deterministic dynamical model over MaleCNS-derived connectivity that is stable enough for closed-loop robotics and honest about what the connectome does not specify.

## Workflow
1. Treat MaleCNS as structural connectivity, not a complete physiological simulator.
2. Start with the simplest model that can test the project hypothesis: leaky accumulator or LIF-like dynamics with configurable decay, threshold, reset, edge scaling, and timestep.
3. Use transmitter/sign information only when the selected dataset/evidence supports the interpretation; otherwise expose the assumption as configuration.
4. Keep sensory injection and descending-population readout APIs explicit and independently testable.
5. Guarantee deterministic replay for fixed graph, config, seed, and stimulus sequence when the backend permits it; document unavoidable nondeterminism.
6. Test zero-input behavior, bounded strong input, long soak stability, NaN/Inf handling, and state reset.
7. Profile before optimizing. Report p50/p95/p99 step latency, memory, graph size, backend, and hardware.
8. Target a 20 ms external cadence when feasible. If not feasible, use a timestamped asynchronous/multi-rate design; never block `robotd` waiting for connectome computation.

## Avoid
- Claiming biological realism from a convenient neuron model.
- Adding GPU complexity before profiling proves it is needed.
- Tuning dynamics only against the final evaluation set.

## Done when
Deterministic replay and stability tests pass, runtime performance is measured, and downstream readout can consume timestamped population activity without bypassing safety.
