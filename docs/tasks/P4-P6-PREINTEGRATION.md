# P4→P6 Pre-integration Remediation Task Packet

```yaml
task_id: P4-P6-PREINTEGRATION
phase: 4-remediation
title: Compose real P4 sensor outputs into one frozen perception frame
owner_skill: perception-sensory-encoder
reviewer_skill: independent-phase-reviewer

base:
  repo_commit: bfe45de506381f2e9016a05c55805a849df46126

goal: >-
  Close the G4 residual integration gap by composing actual camera-target, looming,
  and ToF outputs into one validated canonical perception frame, then prove the
  frame drives the existing SensoryMapper and StimulusTrace without stale replay.

read_first:
  - microduck_connectome/perception_frame.py
  - microduck_connectome/camera_target.py
  - microduck_connectome/looming.py
  - microduck_connectome/tof.py
  - microduck_connectome/sensory_mapping.py
  - microduck_connectome/stimulus_visualizer.py
  - config/sensory_mapping_v1.json

do_not_preload:
  - Phase 6 robotd/simulator integration
  - physical hardware
  - Phase 7+ experiments

outputs:
  - microduck_connectome/perception_compositor.py
  - tests/test_perception_compositor.py
  - tests/test_p4_sensor_pipeline.py
  - docs/PERCEPTION_COMPOSITOR.md
  - machine-validated sensory mapping rule versions

acceptance:
  - actual P4-01/02/03 components are used in the integration fixture
  - compositor output always passes make_perception_frame()
  - camera is the visual frame identity; looming must match that camera timestamp/frame_id
  - ToF uses independent frame identity and is joined by timestamp coherence/freshness, not numeric frame-id equality
  - all required sources use the frozen 100 ms TTL; exactly 100 ms fresh, +1 ns stale
  - invalid/stale/incoherent camera or ToF produces a fully neutral valid=false frame
  - valid no-target camera remains a valid neutral target observation
  - no-target/invalid/stale visual observations reset looming so old looming cannot replay
  - invalid/stale composed frames yield empty SensoryMapper external injection
  - left/center/right and looming mappings remain unchanged
  - StimulusTrace shows no resurrection of prior channels after sensor loss
  - sensory mapping rule metadata is executable-version validated, with no eval
  - no robot/control integration is introduced
  - supported Python 3.12 focused tests pass

context_budget: "<40K input tokens target"
reasoning_effort: high
```
