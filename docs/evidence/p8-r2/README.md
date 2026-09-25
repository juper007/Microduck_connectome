# P8-R2 RGB representation development evidence

The 129×65 candidate and its three paired development seeds were committed
before this run. The candidate source/protocol head was
`a2b8f7ebc6c934d9a7c4e1551bc900a61df102cf`; the original preselection
commit was `e82ed01dfb1dfa41a540a8c773e246f86b884e67`. The task base was
`e4ade0276e5e3f67381f4ca3da9f181077387fa1`. No P8-v2 final seed was used.

## Internal graph-v2 RGB path: development result

Thor Python 3.12.3 ran `scripts/recertify_p8_r2_rgb_path.py` from a clean,
detached checkout of the frozen source. This replay uses a fixed robot pose;
it does **not** contact duck-sim or robotd and cannot prove a moving-body stop.
The identical virtual world geometry and evaluator-only 0.25 m boundary were
retained in both representations. Only the synthetic RGB resolution changed.

| Seed / arm | RGB | Positive looming frames | Positive LPLC2 steps | Peak LPLC2 | Peak DNp01 escape | Healthy neural stop |
|---|---|---:|---:|---:|---:|---|
| 884201 / 2.0 s | 65×33 baseline | 3 | 6 | 0.559 | 0.2 | none |
| 884201 / 2.0 s | 129×65 candidate | 6 | 12 | 0.286 | 0.0 | none |
| 884202 / 2.6 s | 129×65 candidate | 7 | 14 | 0.382 | 0.2 | none |
| 884202 / 2.6 s | 65×33 baseline | 3 | 6 | 0.746 | 0.2 | none |
| 884203 / 3.0 s | 65×33 baseline | 4 | 8 | 0.746 | 0.2 | none |
| 884203 / 3.0 s | 129×65 candidate | 8 | 16 | 0.429 | 0.4 | none |

The candidate provided more frequent but smaller looming/LPLC2 pulses. It
produced **zero of three** internal healthy neural stops at the unchanged 0.5
escape threshold. This is negative neural-sufficiency evidence under the fixed
pose replay, not a final P8-02 trial. A moving robot changes the retinal rate;
the frozen six-row official comparison remains required before classifying
the complete P8-R2 candidate. No gain, temporal filter, graph, decoder,
threshold, boundary, or seed was adjusted after this result.

The candidate static and receding controls (seeds 884204/884205) had zero
positive looming frames, LPLC2 steps, DNp01 escape, and healthy neural stops.
Stale RGB, invalid camera, and invalid ToF mapped to empty neutral external
injection. These are internal controls, not official P8-03/P8-04 outcomes.

Raw report:

| Artifact | Bytes | Cases | SHA256 |
|---|---:|---:|---|
| `/home/juper007/projects/microduck-connectome-thor/evidence/p8-r2-rgb-resolution/internal-a2b8f7e-20260925-1/rgb-path-recert.json` | 142104 | 8 | `aa23e1b3e997ee3e9f7abf9abc1d84a3625f5c819354729404568604716db632` |

Reproduce after fetching the frozen source and ensuring the pinned graph-v2
artifact named by `data/manifests/controller-graph-v2.json` is present on Thor:

```sh
PYTHONPATH=/home/juper007/projects/microduck-connectome-thor/p8-r2-rgb-recert \
python3 /home/juper007/projects/microduck-connectome-thor/p8-r2-rgb-recert/scripts/recertify_p8_r2_rgb_path.py \
  --output /home/juper007/projects/microduck-connectome-thor/evidence/p8-r2-rgb-resolution/repeat/rgb-path-recert.json
```

## Official moving-body comparison

**FAIL.** The official six-row development comparison has now been run twice
under versioned, precommitted source/protocol combinations. These are
development observations, never P8-02 final trials. The visual candidate
remained 129×65 and the graph, sensory mapping, decoder threshold, 0.25 m
boundary, physical trajectory and official robotd authority stayed fixed.
The code used the safe high-level stop latch from **draft, unmerged FAIL PR
#67** as a declared dependency. Its inclusion does not make P8-R1 pass.

| Batch | Source | Thor protocol SHA256 | Started/completed | Candidate early healthy stops | Result | Raw manifest SHA256 |
|---|---|---|---:|---:|---|---|
| v2 | `72330fb336b9494b65bffa24a9ca2946c3881686` | `43bf56843f10d2867b65a1a44232eeb7e99745bb15d2ed90b03e9ca1e8ca09ad` | 6/3 | 0/2 evaluable | FAIL; indices 3–5 rejected before neural arm | `8630989092dedabb59014cb4387504d6a75dd076bf15a174ab97566e65a8c68d` |
| v3 | `bda1a751c131ef959c521b0c740b68ba4dd42deb` | `75a2b6f771decf6704c6f911ca44622f7875ec151e51a761eb854ab47e89ae2c` | 6/6 | **0/3** | **FAIL** | `75e5b035a2eb717551af84c4ea013926e494739565b77833f5bf80adfe233663` |

The v2 batch summary SHA256 is
`de024fe3e1a0ba883cada6adae39a985836ec28915f6d58a8c6fd043d614c2c1`;
the v3 summary SHA256 is
`f701608c338d39c54028f7f69c3440d96b457275641d67b91a7111de9404f1b6`.
Both batch summaries record a successful final official simulator shutdown.
All 47 v2 and 62 v3 indexed raw files were rehashed and their byte counts and
line/record counts verified against the retained manifests. The two raw roots
are, respectively:

```text
/home/juper007/projects/microduck-connectome-thor/evidence/p8-r2-rgb-resolution/official-72330fb-20260925-1/
/home/juper007/projects/microduck-connectome-thor/evidence/p8-r2-rgb-resolution/official-bda1a75-20260925-1/
```

In the full v3 matrix all six robot bodies were moving before neural arm;
command refresh gaps were 24–35 ms and safety-limit violations were zero.
No row reached the frozen healthy stop trigger during its observation window.
Candidate peak DNp01 readout was 0.0, 0.2 and 0.4, below the unchanged 0.5
EscapeDecoder threshold. Baseline peak DNp01 was 0.0, 0.2 and 0.2. The trial
fixture recorded a no-stop deadline error for each row, so it did not complete
normal pose-stop or scheduler-stop scoring; null scheduler counts must not be
treated as zero healthy scheduler exceptions. No candidate trial may be
promoted to a P8-02 success. The v2 parser defect was fixed only in a new
version with new seeds and a complete rerun; v2 rows were not combined with
v3 to improve the rate.

Reproduce v3 only at the frozen source in a **new unused** raw directory on
Thor Python 3.12. The official `microduck` and `microduck_rl` checkouts must
match the pinned repository hashes:

```sh
PYTHONPATH=$PWD python3 -m unittest tests.test_p8_r2_rgb_v2 tests.test_neural_stop_latch tests.test_fault_stop tests.test_escape_decoder tests.test_safety_clamp tests.test_watchdog tests.test_g8_r5d_fixture -q
PYTHONPATH=$PWD python3 scripts/p8_r2_rgb_batch.py --root "$PWD" --microduck /home/juper007/projects/microduck-connectome-thor/microduck --microduck-rl /home/juper007/projects/microduck-connectome-thor/microduck_rl --output /home/juper007/projects/microduck-connectome-thor/evidence/p8-r2-rgb-resolution/repeat-new-directory --sim-state /tmp/p8-r2-render-state --body-port 7900
```

The unchanged 129×65 candidate failed the preboundary neural trigger screen.
A new, separately frozen sensory encoding hypothesis is required before any
P8-v2 final protocol. No gain/filter/graph/decoder threshold was changed in
this P8-R2 comparison.
