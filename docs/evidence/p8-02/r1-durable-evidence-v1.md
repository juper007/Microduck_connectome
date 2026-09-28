# P8-02-R1 published evidence verification

Task `P8-02-R1-EVIDENCE-FINAL-REMEDIATION`. The evidence verdict below uses a newly downloaded GitHub Release asset and the frozen R1 decision rule. The phase gate also requires an independent exact-head review and PR merge. No D or B trial was rerun.

## Durable GitHub Artifact

| Field | Verified value |
| --- | --- |
| Release and tag | [p8-02-r1-evidence-v1](https://github.com/juper007/Microduck_connectome/releases/tag/p8-02-r1-evidence-v1) |
| Exact asset | [p8-02-r1-evidence-v1.tar.gz](https://github.com/juper007/Microduck_connectome/releases/download/p8-02-r1-evidence-v1/p8-02-r1-evidence-v1.tar.gz) |
| Published and downloaded bytes | 893,054 / 893,054 |
| Published and downloaded SHA256 | `744a785f366417243e3715736c33c6903e75ead2ca0a371c277f83fbefbdbb3a` / same |
| Identity | **MATCH / PASS** |
| Archive format | gzip and tar listing/extraction PASS; 342 tar entries |

The downloaded asset was extracted into a fresh temporary directory. Every verification below used that extraction as evidence input. Historical Thor paths are retained only as recorded path identifiers. The archive was not modified or repacked.

## Archive Inventory

| Directory | Files | Subdirectories | Uncompressed bytes | Contents |
| --- | ---: | ---: | ---: | --- |
| `p8-02-r1-development-v1/` | 42 | 6 | 763,840 | 3 attempt directories, 3 each of `armed.json`, `events.jsonl`, `neural-ledger.jsonl`, `visual-frames.jsonl`, `trace.jsonl`, `progress.jsonl`, `summary.json`; journal, manifest, batch summary, score, final down/probe, per-attempt logs |
| `p8-02-r1-approach-v1/` | 246 | 40 | 5,023,909 | 20 attempt directories and the corresponding raw, journal, manifest, score, final down/probe, and per-attempt logs |
| `p8-02-r1-no-seed-gate-v1/` | 5 | 0 | 4,701 | `gate.json` and four testcase logs |

The only file omitted from each stage's raw manifest is the manifest itself. No unexpected archive file or ID directory was found. The attempt records contain stdout/stderr and acquisition logs; there is no separate file named `checkpoint` because the durable journal and manifest are the checkpoint records.

## Full D Manifest Verification

`D_EXPECTED_IDS=3`, `D_PRESENT_IDS=3`, `D_MANIFEST_ENTRIES=41`, `D_HASH_MATCH=41`, `D_BYTE_MATCH=41`, `D_RECORD_MATCH=41`, `D_MISSING=0`, `D_EXTRA=0`, `D_MISMATCH=0`. Every recorded path was resolved within the extracted D root, and every listed file was opened and independently hashed, sized, and line-counted. D00–D02 have the fixed seeds 886020–886022. The historical “39/39” claim counted a subset; the full manifest contains 41 entries.

## Full B Manifest Verification

`B_EXPECTED_IDS=20`, `B_PRESENT_IDS=20`, `B_MANIFEST_ENTRIES=245`, `B_HASH_MATCH=245`, `B_BYTE_MATCH=245`, `B_RECORD_MATCH=245`, `B_MISSING=0`, `B_EXTRA=0`, `B_MISMATCH=0`. This covers **every** manifest entry for B00–B19, seeds 880020–880039, including raw JSONL, logs, summaries, journal, score, and final state files. The previous B00/B16/B19 spot check is superseded.

## Journal / Attempt Accounting

D has 3 planned IDs and 3 `attempt-01` records; B has 20 and 20. Each ID has its fixed seed, one `armed=true` attempt, `ARMED_COMPLETE` journal status, a retained `armed.json`, `TRIAL_EXITED` with exit 0, and a `summary.json` whose identity and SHA256 match its journal entry. Progress records include motion confirmation, arm, neural stop, stop request, ACK, stopped confirmation, and completion. All attempt files are included in the complete manifest verification. No `attempt-02/03`, replacement seed, overwritten attempt, interrupted/unknown-arm state, or unaccounted assigned ID was found. The next attempt begins with a recorded simulator down; each batch has a final down/probe record. The journal's status and original score are PASS for both batches.

## Published-Archive Independent Re-score

The canonical `scripts/p8_02_r1_score.py` was run against the extracted D and B roots using `config/p8_02_r1_protocol_v1.json`. Its original absolute-path guard rejected relocated release files. The added `--recorded-raw-root` option maps each embedded historical absolute path to the corresponding extracted path, then retains the SHA256 and record-count checks; the original local-path behavior is unchanged. This permits scoring the published bytes without editing any raw, journal, manifest, or original score file.

| Stage | Result | Healthy causal preboundary successes | Failures | Safety-limit violations | All raw accounted | Pose-confirmed preboundary stops (secondary) |
| --- | --- | ---: | ---: | ---: | --- | ---: |
| D | PASS | 3/3 | 0 | 0 | true | 2/3 |
| B | PASS | 19/20 | 1 (B16) | 0 | true | 12/20 |

The original `score.json` files agree with the newly generated scores on results and per-ID classifications. The scorer output, not the original trial summary's `behavior_result`, controls the gate.

## Historical B15/B16 Reconciliation

PR #76 described B15 as the single non-preboundary failure. The published raw and deterministic scorer establish **B16**, seed 880036, as the sole R1 gate failure: `raw_deadman_limiter`. B15, seed 880035, is PASS. Both IDs have one armed attempt, measured moving precondition, positive looming, LPLC2 stimulation, DNp01 peak 0.6 above threshold 0.5, healthy neural stop, `robot.stop` request and ACK, and zero safety-limit violations.

| Raw-derived point | B15 | B16 |
| --- | ---: | ---: |
| Neural stop boundary margin (m) | +0.274702 | +0.143053 |
| First stop request margin (m) | +0.273219 | +0.141655 |
| Stop ACK margin (m) | +0.273176 | +0.141506 |
| Pose-confirmed stop margin (m) | +0.129254 | −0.000639 |
| Startup deadman marker | 0 | 1 |
| Deterministic scorer | PASS; no failure causes | FAIL; `raw_deadman_limiter` |

B16's `precondition_motion` raw event contains `robot_state.limited_by=["deadman"]` before stopped confirmation. The deterministic scorer conservatively disqualifies any such raw state sample up to confirmation. The B16 trial summary says `behavior_result=PASS` and `deadman_limiter_seen_before_stopped=false`; this is a **mechanical trial-summary versus stricter raw scorer classification difference**, not a changed or missing raw file. Its preboundary trigger/request and later pose crossing do not turn it into a gate success. B15's raw and scorer establish a healthy preboundary request and pose stop. PR #76's B15 label is a historical reporting error; that PR is retained unchanged. The score files already classified B16 as the sole failure. There is no ambiguity in the raw-derived fixed-denominator 19/20 result.

## No-Seed Gate Verification

The downloaded `gate.json` is SHA256 `ac4a1efd2e04c086dfb7d3e0a60b644943339b14dc8e9165af9f0ac80f35b071`. Four named cases each have an existing log with matching recorded SHA256 and byte count, exit 0, `PASS`, a matching harness testcase, and `Ran 1 test … OK`: `wrong_operator_path`, `wrong_audit_path`, `sigint_checkpoint`, `sigkill_audit_only`. Result: **4/4 PASS**. These are synthetic/pre-arm tests, not replacement D/B trials.

## Final Down / Port Verification

The D final down exited 0, with a PASS probe SHA256 `16c5c6ab505f5400c200bd291e4dd75e2a530126518225db283ca97d9db68780`; its journal checkpoint is 2026-09-26 01:42:38 UTC. The B final down exited 0, with a PASS probe SHA256 `4202e8ec552354c906693dd3ad5c724917a45c20e68e7a707337ac5841323a4a` timestamped 2026-09-26 01:49:28 UTC, after B19; B's journal checkpoint is 01:49:29 UTC. Both probes report body port 7893 and `/tmp/p8-02-r1-state/duck-a.sock` not connectable. The shared final-down log SHA256 is `d3f4afe57114c117d294acd158e7e26c1e0555df5b2145a4933c323f20891b7c`. These are verified historical shutdown records; no simulator was started during this audit.

## Source / Config / Upstream Verification

Both stage journals record execution source HEAD `4fc5a818249ee1fae4a603fa770beffd825fe967`, MicroDuck `344925c9f8fa031f85428a305b1e8ec2eaae29c1`, and microduck_rl `cb70b792312d559a4da09064d92009079671815f`. Both record graph SHA256 `c4160c42941163079b6b569d117bf67afcf8b45eaa128c444f7c96c2567593cc`, walking policy SHA256 `98c3ea73fa6bb196bcf16586cf38b9fffb782787447d638fa1c1028df9082c1a`, and no-seed artifact SHA256 above. These agree with the frozen R1 protocol and execution configs. The graph manifest SHA256 is `bb1d0e73f0b463ba908977d4e858f0219f956f72ebd830efc21e6fa40853fcfc` in both configs and trial summaries.

SHA256 of committed bytes at execution HEAD (using `git show 4fc5a818:<path>`, avoiding checkout line-ending conversion) matches the journal's recorded hashes:

| Frozen file | SHA256 |
| --- | --- |
| R1 protocol | `63d42a9bbd0808a7c4f507b04319bef7616fabe0fef8f37a3cdd4eb6a70de1dd` |
| D execution config | `d24e06706b4b7047bc2f59e27edacf835d35251e44d97dedc1cc0f121ff6d16c` |
| B execution config | `ef354533db117920a5fcad2fea1680fb810dd8b712d8a3dac69e7d1908cf5f9b` |
| P8-V2 final protocol | `d281d239b9d080027d4c2662f889f76e68e04ef06599d78bb0cd644dcf515e42` |
| Scenario config | `3967c2efa327c0a69a6f9629a12ac0c80f38a7ca6b02b4e9aceecd4cbd53c9eb` |
| R1 scorer / batch / trial scripts | `8f2f2d854fb168af8b3936c82afa2e88c28c3bdb05237cb4cd7221a3ee01e6af` / `9af398af405ca544a5e11d183f54ae8531cde67376e707eb6cb656d8a9e19c09` / `f8ccb6eec603495de79880ec8bb693acd756092ffd80cdef29224eccce9b769f` |

The frozen protocol and D/B configs agree on the 8×8 fractional RGB renderer, log-area estimator A, 20 Hz visual and 50 Hz neural/control scheduling, 100 ms freshness, graph/manifest hashes, DNp01 threshold 0.5, SafetyClamp and Watchdog config hashes, 500 ms deadman, 100 ms stop-ACK refresh, 0.25 m evaluator boundary, and `robot.stop` transport. Their component hashes cover the renderer, estimator, decoder, safety envelope, scheduler, and Watchdog. Raw per-trial summaries and the scorer checked these operating values and lineage. The archive does not contain independent graph, ONNX policy, or upstream repository bytes; the contemporaneous preflight hashes/commits and frozen repository references are the evidence for those external inputs.

## Reproduction

Download the exact release asset above into a new directory and check 893,054 bytes and the stated SHA256 before extraction. From this repository, run:

```text
python scripts/p8_02_r1_verify_archive.py <extracted-root>
PYTHONPATH=. python scripts/p8_02_r1_score.py --raw-root <extracted-root>/p8-02-r1-development-v1 --recorded-raw-root /home/juper007/projects/microduck-connectome-thor/evidence/p8-v2-final/p8-02-r1-development-v1 --protocol config/p8_02_r1_protocol_v1.json --output <temporary-D-score.json>
PYTHONPATH=. python scripts/p8_02_r1_score.py --raw-root <extracted-root>/p8-02-r1-approach-v1 --recorded-raw-root /home/juper007/projects/microduck-connectome-thor/evidence/p8-v2-final/p8-02-r1-approach-v1 --protocol config/p8_02_r1_protocol_v1.json --output <temporary-B-score.json>
```

Set `PYTHONPATH=.` through the local shell's environment syntax. The outputs must be outside the extracted archive.

## Final Evidence Verdict

**PASS** for the published-archive P8-02-R1 evidence: prior D development 3/3, B 19/20 with all 20 fixed IDs accounted, zero safety-limit violations, verified manifest and journal accounting, no prohibited retry or replacement, four no-seed cases, final down/port, and no observed frozen source/config hash mismatch. Pose-confirmed preboundary cessation is a separate secondary 12/20 B outcome. The release asset, not PR prose, is the verification input. This evidence verdict does not by itself close the independent exact-head review or PR freshness/merge gates. P8-03 remains a separate later task.
