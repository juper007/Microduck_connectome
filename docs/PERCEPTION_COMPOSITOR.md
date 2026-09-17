# P4→P6 Perception Compositor

Task: **P4-P6-PREINTEGRATION**

This component closes the Phase-4 residual integration gap before Phase 6 by composing actual P4 camera, looming, and ToF outputs into one frozen `PerceptionFrame`.

## Source identity policy

- Camera is the authoritative visual frame identity.
- Looming is derived from the camera stream and must match the camera `timestamp_ns` and `frame_id` exactly.
- ToF has its own independent frame identity. Its frame ID is not numerically compared with the camera frame ID.
- Camera and ToF timestamps may differ by at most the frozen 100 ms perception coherence bound.
- Output `timestamp_ns` is the newer of camera and ToF timestamps.
- Output `frame_id` is the camera frame ID.

Repeated evaluation of the exact same source sample is allowed. Partial identity changes or metadata regression are fail-closed.

## Freshness

- exactly 100 ms old: fresh
- 100 ms + 1 ns: stale
- repeated evaluation never refreshes source timestamps

## Validity policy

camera invalid OR ToF invalid OR looming association invalid OR required source stale/future/incoherent → fully neutral `valid=false` PerceptionFrame.

A valid camera observation with no target is not a sensor fault. It remains `valid=true` with `target_x=0`, `target_area=0`, `confidence=0`, and `looming=0`.

The real `PerceptionPipeline` resets the stateful `LoomingEstimator` whenever the camera is invalid, stale, or contains no target. Reacquiring a target therefore starts a new baseline.

## Real P4 component path

`CameraTargetDetector → LoomingEstimator + ToFProximityEncoder → PerceptionCompositor → SensoryMapper → StimulusTrace`

The integration fixture does not inject a hand-built full perception frame to bypass P4-01/02/03.

## Sensory mapping identity

`sensory_mapping_v1.json` pins `target-linear-lateral-split-v1` and `bilateral-lplc2-v1`. `SensoryMapper` rejects unknown rule versions or altered mapping metadata. No expression is evaluated.

ToF proximity remains outside biological neural mapping in v1.

## Scope

This remediation adds no robot command, simulator control, yaw calibration, stop transport, neural-runtime change, safety-envelope change, or hardware access.
