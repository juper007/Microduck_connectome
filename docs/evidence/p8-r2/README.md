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

Pending the separate P8-R1 stop-latch remediation. The historical PR #66
fixture has known post-latch and stop-attribution hazards and is not used as
production stop-transport evidence. The six official rows in the frozen
`config/p8_r2_rgb_resolution_dev_v1.json` remain planned and unstarted.
