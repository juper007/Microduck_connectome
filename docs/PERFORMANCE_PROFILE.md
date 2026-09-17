# Neural Runtime Performance Profile

Task: **P3-06**

The P3 performance harness measures `SparseNeuralRuntime.step()` wall-clock latency with `time.perf_counter_ns()` after a warmup period. It reports nearest-rank p50, p95 and p99 latency plus min/max.

## Workload

The committed benchmark workload is deterministic and **synthetic matched-scale**, not an actual MaleCNS topology:

- 570 neurons;
- 21,142 unique directed non-self edges;
- normalized edge weight 0.01;
- 100 warmup steps;
- 500 measured steps;
- every tenth measured step injects 0.5 into body 1 and 0.25 into body 200.

The scale matches the selected G1 graph evidence (570 nodes / 21,142 edges) so it is useful for runtime-cost characterization while respecting the policy not to commit the bulk graph artifact. It does not preserve G1 degree distribution or topology and must not be presented as a biological performance result.

Canonical workload identity: `297f11c6248142fc89c875d7547574a7c97e44eb46335069af82a1935a4540d9`.

## Acceptance interpretation

The frozen P-1.1 preferred target is p95 neural step latency <=18 ms. The benchmark reports the target and whether the measured supported-environment run meets it. The threshold is not adjusted after seeing results.

The versioned evidence under `docs/evidence/p3-06/` is populated from the supported Python 3.12 PR workflow. Measurements from unsupported local interpreters are not acceptance evidence.
