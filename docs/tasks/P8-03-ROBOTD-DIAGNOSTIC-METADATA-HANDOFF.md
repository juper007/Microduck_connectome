# P8-03 robotd diagnostic metadata handoff

Task: `P8-03-ROBOTD-DIAGNOSTIC-METADATA` only. The architecture decision is PR #94 at `66754b489f526a2f3f62eef50c3c3c7f4884a395`; connectome `origin/main` base is `57161251c63be912a002d236d18e7c13cd48b1cc`. Upstream MicroDuck source remains pinned in `config/versions.json` at `344925c9f8fa031f85428a305b1e8ec2eaae29c1` until an upstream build and integration review accept the candidate.

## Candidate

Local upstream candidate commit: `c47085a57770c52ed4cd00d5960b17598df2d7af`, based directly on the pinned source. [Patch](../../patches/microduck/p8-03-robotd-diagnostic-metadata.patch) SHA-256: `828ff2619ee378d4fe49fe358944dcc9b5aa9b6583e7aef1afe43a353411655a`. Apply the patch to a clean checkout of the pinned commit.

The patch adds a writer-serialized, process-wide twist generation while keeping control-loop reads lock-free. Request-form `robot.move` returns `accepted_move_generation`; notifications and `robot.stop` also advance the same generation. Every published `robot.state` carries the generation read by its tick and a strictly increasing `control_tick_sequence`. API version becomes 32. `t_ns` remains the last successful sensor-read `CLOCK_MONOTONIC` timestamp, including during coast. Existing intent-result and state deserializers can ignore/default the additive fields; diagnostic consumers must require them.

The project client now reuses its subscription. `diagnostic_state()` uses robotd's unrestricted `robot.subscribe` (`{}`), checks tick and generation continuity plus source timestamp freshness, and rejects reconnect or rate changes. `RobotdDiagnosticRecorder` starts a dedicated connection before acquisition, syncs every raw state wire line and parsed frame to a new JSONL file, retains raw move request/ACK lines with their recorded times, and writes a terminal failure record if the stream fails. It does not send motion. A later prospective precondition harness must call the recorder's request/ACK methods on the exact bytes it sends and receives, check recorder health through arm, and apply the unchanged frozen moving-body gate. No current P8 trial harness is modified here.

## Exact source identity

SHA-256 values below are over Git blob bytes (not Windows working-tree line endings):

| Upstream path | Pinned `344925c9` | Candidate `c47085a` |
| --- | --- | --- |
| `duck-ipc-proto/src/lib.rs` | `2d0f2a224e14f79099a2440e3497370836a75fd24b2b196b14fcdadf1e287a6b` | `da02f4734cdb3d69962ebc7c17995d98c42276024424e14b3d40314df85d39ee` |
| `robotd/src/intents.rs` | `1deeaa99378ab562aa9938f0f2c8d3073205668fea76033070ced66a2b50dce1` | `1e02a13b2fda02e0cecf615091b91960862c598d651ab24ed55785d90b222c8f` |
| `robotd/src/main.rs` | `ac4fdbd41471829f9e17b539a0013c38d9edc237515a2559cd046ba462a39c8d` | `57a9d8ac0a24b150f695a8784e20866ba950006cf2e7fbfe53e2cb551f4171d7` |
| `robotctl/src/monitor.rs` | `c1646e91004f4f5511881af14c0a16ea2be7fa3a32924d36fb80f2bcf8fd544d` | `87877ef9fde9c9252ca0fe9fd2d1f9c9e967d21ab852dcf1e9a6450cc9e8bc73` |

## Validation and integration boundary

The patch reverse-applies cleanly to the local candidate and `git diff --check` passes in both repositories. Python source and tests compile; standard-library smoke checks of subscription reuse, tick-gap rejection, raw frame capture, ledger sync, and failure latching pass. The targeted Python CI job passed. Full pytest and Cargo/Rust are unavailable in the current Windows environment. The dedicated CI workflow applies this patch to the pinned source and runs `cargo fmt --all --check` and `cargo test -p duck-ipc-proto -p robotd -p robotctl`; confirm its final run on the draft PR before integration. Re-review the exact candidate head and integrate the upstream commit/pin before any causal precondition or timing work. Do not treat this handoff as P8 behavioral evidence.

No P8 probe, final ID, Thor timing run, P8-04 work, or reclassification of historical `TPR2A-001` was performed.
