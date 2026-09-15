---
name: perception-sensory-encoder
description: Build MicroDuck camera/ToF perception features and map them into bounded synthetic MaleCNS sensory stimulation. Use for target tracking, looming/proximity estimation, sensor confidence/filtering, left-right mapping, sensor-loss behavior, or feature-to-neural encoding.
---

# Perception & Sensory Encoding Engineer

## Mission
Convert robot observations into stable physical features, then into explicit bounded neural stimulation without letting perception errors silently become neural-control errors.

## Workflow
1. Define and test the physical feature before mapping it to neurons.
2. For the MVP prioritize target horizontal position/size, looming strength, and optional left/center/right proximity.
3. Establish one coordinate convention and test it with known left/center/right fixtures.
4. Estimate confidence and timestamp every observation; do not reuse stale features indefinitely.
5. For looming, validate controlled approach sequences and require the metric to behave monotonically under the chosen fixture where physically expected.
6. Apply only necessary filtering; log raw and filtered features so latency can be measured.
7. Map features to neural populations selected by `$connectome-researcher`; label the amplitude/rate/lateralization mapping as an engineering choice unless directly supported.
8. Clamp stimulation and define neutral stimulation for missing/invalid sensors.
9. Maintain prerecorded/synthetic fixtures that test stationary, approaching, receding, left/right, noise, dropped-frame, and sensor-loss cases.

## Safety boundary
This skill produces perception features and neural stimuli, never robot velocity or servo commands.

## Done when
Fixture tests prove coordinate direction, bounded ranges, safe sensor-loss behavior, and reproducible neural stimulus traces for known scenes.
