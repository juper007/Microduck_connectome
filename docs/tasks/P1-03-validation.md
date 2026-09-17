# P1-03 implementation handoff

- Task packet: `docs/tasks/P1-03.md`; owner: connectome-data-engineer.
- Input/fetched base: `357a5e5751251bd09c8e942ea2269ee09e0b851a`.
- Branch: `feature/p1-03-connectivity-extraction`; isolated checkout:
  `work/p1-03-connectivity-extraction`.
- Scope: packet, AGENTS/skill/token policy, exact neural/data-policy sections,
  P1-02 module/schema and focused tests; below 25K context target, no bulk reads.
- Implementation: `microduck_connectome/connectivity.py`; explicit bounded input
  API, full outgoing normalization before target selection, canonical manifest.
- Contract/usage: `docs/CONNECTIVITY_EXTRACTION.md`.
- Synthetic tests: `tests/test_connectivity.py` (14 tests). No random seed needed.
- `python -m unittest discover -s tests -p test_connectivity.py -v`: 14 passed
  on local Python 3.13. This interpreter is supplemental; the project specifies
  Python 3.12 and PM handles supported-environment validation.
- `python -m unittest discover -s tests -v`: 52 test methods passed; one module
  import error in existing `test_probe_annotations` because local Python lacks
  `pyarrow`. No dependency or environment changes made. PM owns full-suite
  validation using the existing Thor environment.
- `git diff --check`: clean before staging; staged check also required at commit.
- No source credentials, network calls, raw dataset or biological evidence added.
- Real-source fixture validation, independent review, reviewed head, PR, and
  pre-merge freshness are PM follow-up; no phase gate approved here.

The API and limitation contract are complete in the focused documentation.
Completeness and upstream source hashes remain caller assertions. The manifest
distinguishes the upstream source-file hash from the canonical supplied-row hash.
Mutable output must retain its entire manifest; this task adds no graph storage
reader/writer, bulk loader/cache, runtime API, or biological validation. P1-04 and
P1-05 remain separate.

## PM supported-environment validation

Implementation `ea744cc910ec60fea4759de664754fb701a6315f` was exported with git archive to isolated Thor directory `/home/juper007/projects/microduck-connectome-thor/p1-03-ea744cc`. Existing Python 3.12.3 data environment, no dependency changes: `python -m unittest discover -s tests` passed 58/58.

Real-source diagnostic: verified both official cached Feather SHA256 values recorded in `P1-03-real-validation.json`; scanned the full 151,856,684-row weight table and selected every outgoing row for body IDs 10005 and 523769 (23,080 rows), with no target filter. Selected IDs are diagnostic fixtures, not full biological populations. Source file confidence threshold is 0.5; no additional weight threshold. `P1-03-real-graph.json` includes the extraction config and provenance. The source-projection hash differs deliberately from the full-file hash.

The minimal annotation projection copies bodyId/type/instance/class and explicitly maps source somaSide `R` to `right`, `L` to `left`; original values and conversion remain in the oracle evidence. It never infers laterality from instance or ID.

Independent integer sum and raw-edge selection agree with the API: outgoing totals 23,423 and 24,134; induced edge 10005 → 523769 raw weight 297, normalized 297/23423. Reversed input rows yield an exactly equal artifact. No-outgoing, invalid rows, duplicate pairs, empty graph and subgraph invariance additionally covered by synthetic tests. No biological-function or phase-gate claim.

Validation scripts retained on Thor as `p1_03_source_fixture.py` and `p1_03_live_validation.py`; input `p1-03-evidence/source-fixture.json`. Only small graph/oracle evidence is committed. Raw official data remains outside Git. Final independent review pending; task REVIEW.
