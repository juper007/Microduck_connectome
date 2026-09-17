# Neural Sensory Mapping

Task: **P4-04**

This adapter maps the frozen Phase-4 perception frame into P3 `StimulusInjector` populations.

## Pinned populations

`config/sensory_mapping_v1.json` is generated from committed Phase-2 evidence:

- LC10a soma-side L: 135 bodies;
- LC10a soma-side R: 140 bodies;
- LPLC2 soma-side L: 94 bodies;
- LPLC2 soma-side R: 91 bodies.

Tests compare the committed config against the original P2-05/P2-01 evidence, so identity drift fails validation.

## Engineering mapping

Soma side is **not** claimed to be receptive-field side or robot yaw sign. The initial mapping is an explicit engineering convention:

```text
target_strength = target_area * confidence
lc10a_left      = target_strength * (1 - target_x) / 2
lc10a_right     = target_strength * (1 + target_x) / 2

lplc2_left  = looming
lplc2_right = looming
```

Thus a far-left image target activates only the configured LC10a-L channel, a far-right target only LC10a-R, and a centered target splits equally. This convention may be revised only through normal reviewed change control; it is not a biological receptive-field claim.

ToF proximity channels are deliberately **not** assigned to a neural population in v1 because no Phase-2 evidence freezes such a mapping.

## Freshness

Perception TTL remains the frozen 100 ms. Invalid or stale frames produce zero named channels and an empty P3 external-input mapping. The mapper never writes neural internal state directly and never emits robot commands.
