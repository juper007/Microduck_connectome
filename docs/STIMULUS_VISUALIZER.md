# Stimulus Trace Visualizer

Task: **P4-05**

`StimulusTrace` records the frozen perception frame together with the four P4-04 named neural stimulus channels:

- `lc10a_left`
- `lc10a_right`
- `lplc2_left`
- `lplc2_right`

Every sample is range-validated and requires strictly increasing monotonic timestamps and frame IDs.

## Outputs

### JSONL

`to_jsonl()` produces deterministic canonical JSON objects containing the complete perception frame and stimulus channels. This is intended for machine inspection, replay/debugging and evidence capture.

### SVG

`to_svg()` produces a dependency-free SVG with four horizontal amplitude lanes over the recorded monotonic time range. Each lane is 0..1 and uses a distinct line/dash pattern with textual labels. The SVG is diagnostic only; it is not a controller input.

Tests include an integration fixture that passes real P4-04 `SensoryMapper` outputs into the visualizer.

This module has no neural-state mutation, behavior decoder, robotd call or actuator access.
