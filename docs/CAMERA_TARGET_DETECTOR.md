# Camera Target Detector

Task: **P4-01**

The MVP camera target detector is deliberately a deterministic high-contrast RGB marker detector for synthetic/simulator fixtures. General object recognition is outside the MVP scope.

## Contract

- input: rectangular RGB integer frame plus monotonic `timestamp_ns` and `frame_id`;
- configured RGB marker, channel tolerance and minimum matched-pixel count;
- `target_x=-1` at the first image column, `0` at center and `+1` at the last column;
- `target_area` is matched pixels divided by total pixels;
- detected marker confidence is 1.0; no-target confidence is 0.0;
- a valid frame with no target emits neutral target features;
- an invalid/missing source emits a fully neutral frame with `valid=false` and never replays an earlier target.

All outputs are produced through the frozen perception-frame validator and stay inside the documented ranges.

This module does not perform neural mapping, behavior decoding, robot commands or servo access.
