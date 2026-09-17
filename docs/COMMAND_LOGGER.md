# Phase-5 Command Logger

Task: **P5-06**

The command logger records enough structured state to explain why a Phase-5 intent was passed, clamped, stopped, or neutralized before future robot integration.

Each record contains:

- monotonic output timestamp and sequence;
- neural-readout summary when available;
- pre-safety behavior intent when available;
- post-safety-clamp intent when available;
- final watchdog intent;
- explicit final stop state and runtime health;
- watchdog state / stale reason / decoder liveness;
- clamp-applied flag and clamp reasons;
- controller identity;
- SHA-256 identities for the five Phase-5 configs.

Fault paths may legitimately have missing neural or decoder data; those fields are written as JSON null rather than fabricated values.

Serialization is deterministic canonical JSONL. Retained records are detached from caller-owned mappings. The logger stores hashes and logical component names only, not credentials or local filesystem paths.

P5-06 also owns the final Phase-5 integration fixture: synthetic DN activity flows through the real aggregator, steering/escape decoder, safety clamp, watchdog, and logger. This remains internal intent processing only; no robot API is called.
