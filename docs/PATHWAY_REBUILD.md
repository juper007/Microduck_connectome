# Public-source pathway rebuild

Run from the repository root in the locked project environment (Python 3.12,
PyArrow supplied by the existing lock). No credentials are needed. Explicit file
arguments permit an existing cache anywhere; `--download` acquires missing files
from the pinned public URLs and verifies SHA-256 before publishing them.

```sh
python -m microduck_connectome.rebuild_pathway \
  --annotations data/cache/body-annotations.feather \
  --weights data/cache/connectome-weights.feather \
  --output-dir results/g1-pathway \
  --code-commit "$(git rev-parse HEAD)" --download
```

The committed source manifest is `data/manifests/pathway-source-v1.json`; the
selection is `config/pathway-lc10a-dna02-v1.json`. Both are embedded and hashed in
`pathway-report.json`. Custom `--manifest` and `--config` files are supported for
fixtures or explicit alternate inputs. Public-source evidence must use the pinned
defaults. The supplied code SHA identifies the executed checkout; the caller must
ensure it is accurate and the checkout clean. The fixed configuration timestamp
is a reproducibility label, not the wall-clock execution time.

Selection uses exact source type names: every LC10a and DNa02 body is retained,
along with annotated distinct intermediate bodies on directed two-edge routes.
Unannotated intermediary IDs and endpoints occurring as intermediary candidates
are counted and excluded. All induced edges among the selected nodes are retained;
the result is not merely a list of selecting paths. No minimum weight is applied.
All outgoing source rows for selected nodes, including unannotated targets, enter
the existing strict extraction API, preserving complete source denominators.

Two full Feather V2 IPC batch scans use Arrow filters. The 151 million source rows
are never converted into a Python row list. Only rows outgoing from selected nodes
are materialized for the existing extraction API; memory therefore scales with
that bounded population's outgoing edges, not just induced graph size. The public
files' hashes/counts are checked and all scanned endpoint/weight values validated.
Duplicate selected-source edges fail extraction; global uniqueness outside selected
sources is not independently rechecked (the source bytes are pinned).

The report includes exact candidate IDs and raw records for LC10a, LC4, LPLC2,
DNa02, DNp01, DNge104 and MDN. Absent names are explicit, never aliases. The flat
file population means all annotation rows, not a neuPrint `Neuron` label query.
Raw selected annotation records preserve `superclass`, `somaNeuromere`, and side.
Only literal L/R become canonical left/right. M, empty, null and other raw side
values remain separately visible in the report; the narrower annotation-v1 view
represents these as null (not a left/right claim). Empty optional text becomes null
in that view. `source-metadata.json` preserves the raw source evidence for anatomical
queries, identifies its producing code SHA in `extraction_commit`, and its digest
is recorded in the report.

Generated graphs are content-addressed under the output's `graphs/` directory.
Use ignored `results/` or `data/cache/` for outputs; do not commit source/cache
files. Version the small report as evidence after a real rebuild. Run twice with
the same code SHA/config/source and compare report bytes and graph cache keys.
Connectivity observations alone establish neither biological function nor a robot
sensory/readout mapping; Phase 2 evidence remains separate.
