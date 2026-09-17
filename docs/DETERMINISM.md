# Deterministic Replay

Task: **P3-05**

`microduck_connectome.determinism` creates a fresh `SparseNeuralRuntime` for each replay, captures every exact snapshot, serializes snapshots with canonical JSON and hashes the bytes with SHA-256.

The committed P3-05 fixture uses 3 neurons, 2 directed normalized edges and a 5-step external-input trace. Two independent runtime instances produce exact-equal snapshot sequences with SHA-256:

`e03ac3bbe892f45b2d2797a4618fa1de952ca29b58c7b07b879c7353cafaa702`

The evidence also pins the synthetic graph fixture hash, input-trace hash, frozen neural config hash, dataset/model context, backend label, base runtime commit and producer commit. Tests compare the entire committed graph/trace fixture to the executable fixture so evidence drift fails validation.

## Producer commit semantics

`producer_commit` is the first branch commit containing the replay implementation used to generate the deterministic result. Later commits may add or strengthen tests/evidence/docs without changing the replay algorithm. The final merge commit is deliberately not embedded because doing so would make the evidence self-referential; final-head review verifies that any commits after the producer do not invalidate the evidence.

The graph in this evidence is explicitly a **synthetic contract fixture**, not an extracted MaleCNS subgraph. `dataset: male-cns:v1.0` records the frozen project/dynamics context and does not claim that fixture body IDs are biological identities from that dataset.

## Scope

This proves deterministic replay for the frozen Python CPU float32-contract runtime and fixture on a supported backend. It is not evidence of biological validity, whole-CNS determinism on every hardware/backend, performance, or long-duration numerical stability. Those are separate tasks/gates.
