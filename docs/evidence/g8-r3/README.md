# G8-R3 graph-v2 sensory recertification

Thor Python 3.12 loaded the immutable graph-v2 artifact
`c4160c42941163079b6b569d117bf67afcf8b45eaa128c444f7c96c2567593cc`
and the unchanged P4 sensory and P3 neural configs. The workload code commit
is `845714f41bbc7d734f3f935733ea94a436acf284`.

| Frozen sensory population | Configured / present in graph v2 |
| --- | ---: |
| LC10a left / right | 135/135; 140/140 |
| LPLC2 left / right | 94/94; 91/91 |

A fresh frame with `target_x=-0.5`, `target_area=0.4`, `confidence=0.9`, and
`looming=0.8` yielded the frozen lateral LC10a amplitudes 0.27/0.09 and equal
bilateral LPLC2 amplitudes 0.8/0.8. All 460 configured sensory IDs appeared
in external injection. All 185 LPLC2 graph-v2 runtime nodes received current
in the first step and spiked on the second repeated step. No DN or robot
behavior is inferred from that injection.

At 101 ms age (frozen TTL 100 ms) and for `valid=false`, the mapper emitted
empty neutral injection. A new valid timestamp/frame restored the same
mapping. This tests P4 input freshness; G8-R4 will separately test neural
escape/readout behavior.

`sensory-v2.json` SHA256:
`b2a02d19d7fc96fc342102a26bead535bd841898322ef710d5673ec825ad8892`.
The 43 directly affected P4 looming/compositor/sensory and P3 runtime tests
passed on Thor. The historical graph-v1 P4/G7 evidence remains unchanged.
