# Data and Reproducibility Policy

Status: **FROZEN for Phase 0/MVP**  
Version: P-1.0  
Date: 2026-09-15

## 1. Principle

A result is not considered project evidence unless another agent can identify the exact code, graph, configuration, seed, and scenario that produced it.

Large upstream datasets must remain reproducibly obtainable without being copied into Git history unnecessarily.

## 2. Source-of-truth datasets

### MaleCNS

Pinned dataset for MVP:

```text
male-cns:v1.0
```

Official source:

- https://male-cns.janelia.org/
- https://male-cns.janelia.org/download/

The official download/query page is the source of truth for dataset access methods and released files.

### MicroDuck

The exact upstream MicroDuck and `microduck_rl` commits used by the project must be pinned in a version manifest during Phase 0.

Floating `main` references are allowed for research comparison but are not valid identities for reproducible experiment runs.

## 3. What belongs in Git

Commit these:

- source code,
- small test fixtures,
- schemas,
- configuration defaults,
- neuron population definitions/body-ID manifests,
- graph extraction/query code,
- dataset/version manifests,
- checksums,
- experiment definitions,
- fixed trial-seed lists,
- compact processed summary tables,
- documentation,
- scripts that download/rebuild external data.

## 4. What must not be committed directly

Do not commit by default:

- full MaleCNS bulk datasets,
- raw EM volumes,
- large skeleton/synapse dumps,
- regenerated caches,
- large MuJoCo/experiment videos,
- virtual environments,
- model/runtime caches,
- local credentials/tokens,
- personal filesystem paths,
- temporary profiler output,
- large raw experiment batches.

If a large artifact must be versioned later, choose an explicit artifact store/release mechanism and document it; do not casually add it to normal Git history.

## 5. Repository paths

Recommended structure:

```text
config/                 versioned runtime/experiment configs
data/
  manifests/            dataset and graph identities; committed
  fixtures/             small committed test fixtures
  cache/                regenerated local cache; ignored
results/
  local/                developer outputs; ignored
experiments/
  definitions/          versioned benchmark definitions
  seeds/                frozen seed lists
  summaries/            compact reviewable summaries
```

A directory should be created only when implementation needs it; this document defines ownership, not empty scaffolding requirements.

## 6. MaleCNS extraction manifest

Every derived graph used for a test or experiment must have a manifest containing at minimum:

```yaml
dataset: male-cns:v1.0
extraction_tool_version: <git commit or package version>
query_or_extraction_config: <path/hash>
created_utc: <timestamp>
node_count: <integer>
edge_count: <integer>
raw_weight_sum: <integer or exact numeric value>
body_id_set_hash: <sha256>
edge_table_hash: <sha256>
```

For subgraphs, also record:

```yaml
seed_populations: [...]
readout_populations: [...]
path/depth/filter rules: ...
```

## 7. Body-ID policy

Code must not scatter literal MaleCNS body IDs through algorithms.

Body IDs belong in versioned population/graph manifests with:

- type/cell annotation,
- anatomical side,
- dataset version,
- evidence/source note,
- query date or extraction commit.

Algorithms reference named populations, not unexplained numeric IDs.

## 8. Artifact identity

Every experiment run receives a stable run identity derived from metadata.

Required metadata:

```text
project commit SHA
MaleCNS dataset version
graph hash
upstream MicroDuck commit
upstream microduck_rl commit when applicable
neural-model config hash
perception config hash
decoder/safety config hash
scenario definition/version
scenario seed
network/shuffle seed when applicable
controller class
runtime backend
```

Recommended run ID form:

```text
<experiment>-<controller>-<short_commit>-<config_hash>-s<scenario_seed>-n<network_seed>
```

## 9. Configuration policy

- Runtime parameters must be config-driven, not hidden constants where practical.
- Evaluation configs are immutable once a benchmark batch starts.
- A modified evaluation config receives a new version/hash and starts a new benchmark batch.
- Safety limits are stored separately from model parameters so model tuning cannot silently change the safety envelope.

## 10. Random-seed policy

Every source of intentional randomness must accept an explicit seed.

Separate namespaces:

```text
scenario_seed
network_seed
training_seed (if learned readout/ML is used)
```

Never reuse one implicit global random stream to control both scenario generation and network randomization.

## 11. Logging policy

Experiment telemetry must use a structured machine-readable form such as JSONL, Parquet, or equivalent schema-controlled format.

Minimum timestamped channels:

- perception feature frame,
- neural runtime/readout health,
- pre-safety behavior intent,
- post-safety robot-facing intent,
- robot state/heading needed by metrics,
- scenario ground truth,
- fault events/timeouts.

Logs must preserve enough information to distinguish model failure from perception, safety, IPC, or simulator failure.

## 12. Checksums

Externally downloaded files that are relied on for reproducibility should have cryptographic checksums when practical.

Use SHA-256 for project-generated manifests/checksums unless an upstream release provides a canonical stronger/equivalent identity.

A download script must fail loudly on a known checksum mismatch rather than silently accepting changed bytes.

## 13. Credentials and MaleCNS access

Any neuPrint token or other credential:

- lives in environment/secret storage,
- is never committed,
- is never printed into experiment logs,
- is represented in docs only by variable name/placeholders.

Suggested environment variable naming must be documented when implementation is added.

## 14. Licensing/provenance

Every imported/derived dataset or third-party asset must record:

- upstream project/source URL,
- version/release,
- applicable license if known,
- whether the artifact itself is redistributed or only downloaded by the user.

MaleCNS official download documentation currently states connectome data availability and should be checked during Phase 0 before redistributing derived files.

## 15. Clean-checkout reproduction gate

Before Phase 0 is complete, an independent reviewer must be able to start from a clean checkout and:

1. create the supported Python environment,
2. acquire/query the pinned MaleCNS dataset using documented steps,
3. build a small deterministic graph fixture,
4. run a smoke neural step,
5. launch or follow the documented launch path for the pinned MicroDuck simulator,
6. run project smoke tests,
7. obtain the same fixture hashes expected by the repository.

This reproduction must be demonstrated twice from fresh environments as already required by the project execution plan.

## 16. Benchmark evidence package

Every formal benchmark batch should produce:

```text
manifest.json/yaml
frozen configs
seed lists
raw metrics/telemetry reference
summary tables
analysis script/version
review notes
```

The final report must be regenerable from retained raw/processed results, not manually copied numbers.

## 17. Preflight exit criteria

- [x] source-of-truth dataset is pinned,
- [x] Git vs non-Git data policy is explicit,
- [x] graph manifests/hashes are required,
- [x] literal body IDs are centralized,
- [x] run identity is defined,
- [x] seed namespaces are defined,
- [x] structured telemetry is required,
- [x] credential rules are explicit,
- [x] clean-checkout reproduction gate is explicit.
