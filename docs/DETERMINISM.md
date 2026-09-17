# Deterministic Replay

Task: **P3-05**

`microduck_connectome.determinism` creates a fresh `SparseNeuralRuntime` for each replay, captures every exact snapshot, serializes snapshots with canonical JSON and hashes the bytes with SHA-256.

The committed P3-05 fixture uses 3 neurons, 2 directed normalized edges and a 5-step external-input trace. Two independent runtime instances produce exact-equal snapshot sequences with SHA-256:

`e03ac3bbe892f45b2d2797a4618fa1de952ca29b58c7b07b879c7353cafaa702`

The regression suite also verifies that a valid stimulus-trace change changes the replay hash.

## Scope

This proves deterministic replay for the frozen Python CPU runtime and fixture on a supported backend. It is not evidence of biological validity, whole-CNS determinism on every hardware/backend, performance, or long-duration numerical stability. Those are separate tasks/gates.
