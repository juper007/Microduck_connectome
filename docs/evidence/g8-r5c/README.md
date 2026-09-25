# G8-R5c frozen v1 final evidence — FAIL

The first and only started final trial on Thor **failed** the preregistered actual-stop-onset check. The three-trial batch stopped without replacement; seeds `80111` and `80121` were **not started**. This is a FAIL for G8-R5c v1, not a completed three-trial demonstration. The frozen config and fixture were not adjusted after this result. Historical G8-R5 PR #60 and G8-R5b PR #61 remain separate, unmerged FAIL evidence.

## Immutable identity

- Execution: Thor, official MicroDuck `robotd` and MuJoCo, pinned walking policy, graph-v2 full chain.
- Frozen source head: `05bb8fbbb087542c9d35b95b9f8a3030fca41954`.
- Frozen protocol: `config/g8_r5c_neural_stop_v1.json`, SHA256 `1f14ccacd68e6e30df0db53f51d93c9843659bad014636bebd17301b654e0d74`.
- Artifact directory: `/home/juper007/projects/microduck-connectome-thor/evidence/g8-r5c/final-20260925T171056Z-v1/`.
- Batch UTC interval: `2026-09-25T17:10:56Z` to `2026-09-25T17:11:10Z`. The trial summary has no separate UTC start/end fields; trial timing is recorded in monotonic nanoseconds.
- Planned seeds: `80101`, `80111`, `80121`; started: `80101` only.
- The first trial's raw telemetry and failure summary are retained. Official `duck-sim down` finished with exit code 0.

| Artifact | Records / bytes | SHA256 |
|---|---:|---|
| `batch-summary.json` | 14,974 bytes | `e5f417a4d9ffc2eb246f7fb21357dd2bd6f527ee478e9107233ef5aa90442df0` |
| `trial-01-80101/summary.json` | 11,514 bytes | `e81b9d8d82e4f69d8ebbc3bffd4eae9b9eaebd75b36d4627808b2e9c0e1c9e18` |
| `trial-01-80101/events.jsonl` | 168 records / 123,329 bytes | `c97ce30222dcdb6176a28358e8a81cb61e27be14c7f137134213b2a7c22467a3` |
| `trial-01-80101/trace.jsonl` | 1 record / 3,144 bytes | `6adc4fb63676bb19ee03efa1e2872d004f116d7f3a59b017e7daff5ec25094c5` |
| `trial-01-80101/neural-ledger.jsonl` | 17 records / 11,718 bytes | `082bbc1877734758e577bb5008c87fe1c65ef58d121d9b91b4b1eafe108ddb87` |
| `trial-01-80101/trial.log` | SHA256 retained | `04921c85cb331cfc8fd170f480567ed7b4eaa18f5c8f3a50e21a9174b912eca9` |
| `final-down.log` | exit 0 | `d3f4afe57114c117d294acd158e7e26c1e0555df5b2145a4933c323f20891b7c` |

## Frozen checks and finding

The observed body was moving before the first healthy neural `robot.stop`: fresh pose speed was `0.0823 m/s`, robot.state applied vx was `0.07 m/s`, and last positive `robot.move` call-start to stop ACK was `335.477 ms`, leaving a `164.523 ms` margin before the old 500 ms deadman timeout. Applied-vx reduction and near-zero applied-vx were observed.

The **first pose-speed sample below the frozen stopped threshold** occurred at monotonic `1797789847610681 ns`. The conservative refreshed deadman deadline was `1797789843563941 ns`: the first stopped sample was **4.046740 ms late**. A `limited_by=deadman` state was observed at `1797789847110320 ns`, before that first stopped sample. Therefore the evidence cannot attribute actual body cessation solely to the neural `robot.stop`. Sustained cessation was not confirmed under the frozen rules, and `MOTION_STOPPED` and `COMPLETE` were not reached. The failed checks were `actual_stop_onset_before_refreshed_deadman`, `actual_stopped_before_shutdown`, `state_machine_complete`, and `timing_reconstructible`; the fixture error was `RuntimeError: first actual pose-stop sample followed refreshed deadman deadline`.

The fixture suppressed 15 exact-neutral outputs, and sent zero further robot-facing commands before the failed completion. Safety-limit violations, scheduler exceptions, stale events, and missed neural/perception/watchdog deadlines were all zero. The minimum virtual sphere surface clearance was `0.1254591969703183 m`; maximum observed forward displacement was `0.012094059088949324 m`. These healthy checks do not override the failed causal stopping criterion. The same v1 trial must not be replaced, rerun, or reclassified. Any remediation requires a separately scoped protocol/version and a new fully preregistered batch. This isolated fixture provides no P8 continuous-approach boundary-success claim and no topology superiority claim.

The pre-freeze probes, including failures and their hashes, remain in [development-probes.md](development-probes.md). Their results are excluded from the final batch decision. Independent exact-head review of this evidence and code is pending.
