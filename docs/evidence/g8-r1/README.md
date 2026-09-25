# G8-R1 graph-v2 remediation evidence

The historical graph v1 (`340f6a3180026f6c61f19ebc016ae8610ec9f4a07af2af589e4d6d89e5b31f70`)
and G7 PASS are unchanged. This is a separately versioned source-derived graph,
not a retrospective alteration of G7.

The pinned `male-cns:v1.0` annotation and weight Feather files were verified
against `data/manifests/pathway-source-v1.json` before each build. The exact
source selection rule was committed at `45ffa290ee33fbe4ec9572d95ec17d0cd50b2dd7`
before graph construction; the final counting implementation is
`7a6e45aa3c555ca2616b5455594b5c3251bcb3b5`.

| Evidence | Result |
| --- | ---: |
| LPLC2 left/right source IDs | 94 / 91 |
| DNp01 left/right source IDs | 1 / 1 |
| LPLC2→DNp01 direct edges | 185, raw weight sum 4,862 |
| LPLC2→DNp01 two-edge paths in selected graph | 8,562 through 341 distinct annotated intermediates |
| LPLC2→DNp01 two-edge paths in full source overlap | 22,579; includes unselected/unannotated intermediates |
| LC10a→DNa02 directed two-edge paths | 6,571 through 293 distinct annotated intermediates |
| Frozen graph v1 | 570 nodes / 21,142 edges |
| Graph v2 | 1,098 nodes / 72,782 edges |
| Frozen v1 selected nodes absent from v2 | 0 |

`reachability-report-v1.json` contains the exact body IDs, soma-side records,
path counts, selection config, and graph manifest. It is evidence of directed
structural connectivity. It does not establish sufficient DNp01 activity under
the frozen neural dynamics or a robot stop response.

The 14 MB canonical graph is preserved read-only on Thor at the path in
`data/manifests/controller-graph-v2.json`; SHA256 is
`c4160c42941163079b6b569d117bf67afcf8b45eaa128c444f7c96c2567593cc`.
Two full source rebuilds produced byte-identical graph and report files.
The report SHA256 is `ffb8ad507bfe2ef4ce66d69546d4ff23577c237f2a1c57b47bacb1de3e461410`.

On Thor, run the graph-v2 build command in the manifest with the verified
source files and Python 3.12 environment. For integrity tests:

```sh
G8_R1_BUILD_DIR=results/g8-r1-corrected1 python -m unittest \
  tests.test_g8_r1_artifact tests.test_rebuild_mvp_graph -v
```

The three focused checks pass: immutable selection semantics, source-shaped
selection, and graph-v2 equality with frozen P4/P5 populations and Phase-2
LPLC2→DNp01 direct edges. Rebuilding and comparing the two canonical files
is the source-level reproduction check.

Safety and behavior remain unassessed for graph v2. G8-R2 through G8-R6 are
required before any new P8 final batch; graph-v1 G7 cannot be inherited.
