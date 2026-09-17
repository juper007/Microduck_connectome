# Population Readout Contract

Task: **P3-04**

The MVP readout is a rolling spike summary over named populations.

## Aggregation

Default timing is 20 ms neural steps and a 100 ms window (5 samples). For each population:

1. count each neuron's spikes in the current rolling window;
2. take the arithmetic mean of those per-neuron counts.

This produces `spike_count_per_neuron_then_mean` exactly as frozen in P-1.1. It is not a firing-rate estimate unless a downstream consumer explicitly converts units.

## Population construction

A readout can be constructed from explicit body IDs or from exact `ConnectomeGraph.select_type()` matches. Unknown body IDs, empty type selections, non-bool/misaligned spike vectors and non-integral window/timestep combinations are rejected.

## Reset and scope

`reset()` clears only readout history. It does not reset the neural runtime.

P3-04 does not map left/right activity to yaw, apply smoothing beyond the rolling window, interpret biological function, or send robot commands. Those remain downstream control/integration tasks.
