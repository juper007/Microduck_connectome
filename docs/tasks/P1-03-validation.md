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
