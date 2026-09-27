# P8-02-R1 Durable Evidence v1

## Status

P8-02-R1 gate: **VERIFIED PASS** (pending independent review)

## Archive

| Field | Value |
|-------|-------|
| Archive path | `/tmp/p8-02-r1-evidence-v1.tar.gz` |
| Archive SHA256 | `744a785f366417243e3715736c33c6903e75ead2ca0a371c277f83fbefbdbb3a` |
| Archive bytes | 893,054 |
| Source directories | `p8-02-r1-development-v1/`, `p8-02-r1-approach-v1/`, `p8-02-r1-no-seed-gate-v1/` |
| Source root | `/home/juper007/projects/microduck-connectome-thor/evidence/p8-v2-final/` |

## Source / Config / Upstream Hashes

| Item | Value |
|------|-------|
| Source HEAD (p8-02-r1-source) | `4fc5a818249ee1fae4a603fa770beffd825fe967` |
| MicroDuck commit | `344925c9f8fa031f85428a305b1e8ec2eaae29c1` |
| microduck_rl commit | `cb70b792312d559a4da09064d92009079671815f` |
| Protocol config (B) | `config/p8_02_r1_b_execution_v1.json` |
| Protocol config (D) | `config/p8_02_r1_d_execution_v1.json` |
| R1 protocol | `config/p8_02_r1_protocol_v1.json` |

## D Stage (Development Gate)

| Field | Value |
|-------|-------|
| Result | PASS |
| Successes | 3/3 |
| Zero safety-limit violations | true |
| All raw accounted | true |
| Confirmed preboundary stops | 2 |
| Seeds | D00=886020, D01=886021, D02=886022 |

## B Stage (Final Approach Gate)

| Field | Value |
|-------|-------|
| Result | PASS |
| Successes | 19/20 |
| Zero safety-limit violations | true |
| All raw accounted | true |
| Confirmed preboundary stops | 12 |
| Single failure | B16 (seed 880036) — `raw_deadman_limiter` |
| Seeds | B00=880020 … B19=880039 |

## No-Seed Gate

| Field | Value |
|-------|-------|
| Result | PASS |
| Cases | 4/4 PASS (wrong_operator_path, wrong_audit_path, sigint_checkpoint, sigkill_audit_only) |
| Gate artifact SHA256 | `ac4a1efd2e04c086dfb7d3e0a60b644943339b14dc8e9165af9f0ac80f35b071` |
| Host | jetsonthor01 |
| Python | 3.12.3 |

## Final Simulator Down / Port Probe

| Field | Value |
|-------|-------|
| Result | PASS |
| Phase | final_down |
| Body port 7893 | not connectable |
| Robotd socket | `/tmp/p8-02-r1-state/duck-a.sock` not connectable |
| State probe SHA256 | `4202e8ec552354c906693dd3ad5c724917a45c20e68e7a707337ac5841323a4a` |
| Timestamp | 2026-09-26T01:49:28Z |

## Independent Re-Scoring

- D: `p8_02_r1_score.py` → PASS, 3/3, zero safety, all raw accounted
- B: `p8_02_r1_score.py` → PASS, 19/20, zero safety, all raw accounted
- B16 failure cause: `raw_deadman_limiter` (matches original score.json)

## Manifest Verification

- D raw-manifest.json: all 39 file SHA256/bytes/record_count verified against actual files
- B raw-manifest.json: B00/B16/B19 spot-check SHA256 verified; all 20 B IDs present
- No-seed gate: 4 log SHA256s verified against gate.json

## Prohibitions Observed

- No D/B seed re-run
- No replacement seed
- No raw modification
- No missing result creation
- No threshold change
- No evidence reclassification to fit PASS