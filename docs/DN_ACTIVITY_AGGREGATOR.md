# DN Activity Aggregator

Task: **P5-01**

The aggregator wraps the frozen P3 `PopulationReadout` without changing its spike-window semantics.

Pinned Phase-2 identities:

- steering-left: DNa02 body 523769 (source soma side L);
- steering-right: DNa02 body 10360 (source soma side R);
- escape candidate: bilateral DNp01/GF bodies 10001 and 10010.

DNp01 is an evidence-gated urgent-escape candidate. Mapping its activity to a robot stop is still a project engineering hypothesis and is not a claim of biological equivalence.

P3 readout uses a 100 ms / five-step rolling spike-count window. P5-01 divides each P3 population value by five, yielding normalized activities in [0,1]. A runtime-unhealthy sample resets rolling history and emits zero activities with `runtime_healthy=false`.

The module validates strictly increasing monotonic timestamp/sequence metadata and does not mutate neural runtime state or issue robot commands.
