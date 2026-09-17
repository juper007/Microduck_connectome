# P1-04 validation handoff

- Implementation SHA: `b3a33ac3d595f004ae9eed7cd59321b7ad8cb5f4`; base `df43894143e15ec4cfe189764651ea3e19621cbe`, branch feature/p1-04-cache-provenance.
- Windows Python3.13.15: cache14, connectivity14, annotation15 tests pass. Supplemental platform only.
- Thor Linux aarch64 Python3.12.3: `python -m unittest discover -s tests` passes 72/72 from Git archive of implementation in `/home/juper007/projects/microduck-connectome-thor/p1-04-b3a33ac`; existing data environment unchanged.
- Additional real graph API probe: store/load equality, unchanged input, returned object isolation, changed-config identity, old entry preservation and corruption rejection all PASS; `P1-04-real-validation.json` records keys and implementation SHA. Fixture is committed P1-03 diagnostic graph; no new biological claims/source queries.
- Real probe uses a temporary directory cleaned after validation. Script retained on Thor as `p1_04_real_validation.py`.
- Atomic failure/race injection covered by unit tests, not actual power interruption. No directory-fsync crash durability claim. Hard-link-capable filesystem and trusted cache directory required.
- Context: task/skill/AGENTS, exact cache/provenance contract and direct modules only; <25K target; medium implementation effort, no seed needed.
- Final independent review pending; task REVIEW. No phase approval; no runtime/robot behavior or dependency changes. Raw upstream authenticity and completeness remain caller assertions.

- Initial independent review found a recoverable source-count inconsistency. Commit b3a33ac adds the required unselected-source row lower bound plus store/load rejection and valid-case regressions. Supported-environment suite and real graph probe rerun successfully after the fix. Final re-review pending.
