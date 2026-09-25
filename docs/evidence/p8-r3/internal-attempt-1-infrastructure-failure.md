# P8-R3 internal attempt 1 — harness failure before candidate output

- Frozen source/protocol commit: `44361afc2c8ab29b2e2219d8231465b9418c03ab`.
- Pinned graph-v2 SHA256 verified: `c4160c42941163079b6b569d117bf67afcf8b45eaa128c444f7c96c2567593cc`.
- Command: `python -m scripts.p8_r3_internal_compare --graph-artifact C:\Users\juper\AppData\Local\Temp\p8-r3-graph-v2\c4160c42941163079b6b569d117bf67afcf8b45eaa128c444f7c96c2567593cc.json --output docs/evidence/p8-r3/internal-development-raw-v1.json`.
- Result: exit 1, no output JSON written. `render_pixels` raised `LoomingScenarioError("virtual camera entered sphere")` during the 3.0 s arm case because the harness observed for a fixed two seconds after arm, beyond the virtual sphere surface.
- No candidate metrics were read or used to change A/B/C formulas, parameters, seeds, graph, decoder, or safety settings.
- Correction before rerun: retain the same arm times and use common elapsed end 4.0 s, giving 2.0, 1.4, and 1.0 s observation windows. Refreeze source and protocol before looking at candidate output.
