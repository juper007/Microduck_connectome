# Completion Criteria / Definition of Done

## Universal task Definition of Done

A task is `DONE` only if:

- implementation/document is committed,
- tests or evidence are attached,
- configuration/version is recorded,
- known limitations are documented,
- no unresolved P0 defect exists,
- reviewer confirms the task-specific criterion.

“Code written” is not sufficient.

---

## Phase gates

### Gate G0 — Reproducibility ready

Pass only if:
- pinned dataset and repository SHAs exist,
- fresh setup succeeds,
- smoke test is automated,
- no hidden local file is required.

### Gate G1 — Connectome data trusted

Pass only if:
- IDs/types/sides are reproducible,
- graph extraction is tested,
- data provenance is embedded,
- chosen graph can be rebuilt from pinned source.

### Gate G2 — Biological mappings reviewable

Pass only if every neural mapping states:
- source,
- evidence strength,
- MaleCNS IDs,
- uncertainty,
- robot-engineering interpretation.

### Gate G3 — Neural runtime stable

Pass only if:
- deterministic replay passes,
- zero-input stability passes,
- no NaN/Inf in soak test,
- latency/memory benchmark exists.

### Gate G4 — Sensor encoding valid

Pass only if:
- coordinate convention is tested,
- signal range is bounded,
- sensor loss is safe,
- approach/looming fixture behaves monotonically.

### Gate G5 — Decoder safe

Pass only if:
- output clamps pass,
- stale timeout passes,
- process-crash test passes,
- invalid neural output cannot reach robot as unbounded command.

### Gate G6 — Closed-loop simulation safe

Pass only if:
- controller uses supported high-level MicroDuck interface,
- autonomous 10-minute soak passes,
- stop works,
- restart/dropout tests pass,
- telemetry is sufficient to reconstruct behavior.

### Gate G7 — Steering behavior demonstrated

Target acceptance:
- correct-direction steering on ≥90% of valid target trials,
- no-target false-turn rate below pre-registered threshold,
- zero safety-limit violations.

### Gate G8 — Looming behavior demonstrated

Target acceptance:
- ≥95% valid looming trials trigger before defined boundary,
- false-positive rate below pre-registered threshold,
- sensor-loss tests lead to neutral/stop.

### Gate G9 — Scientific comparison complete

Pass only if:
- real, shuffled, random, and conventional baseline receive equivalent inputs,
- same safety envelope is used,
- same trial seeds are used,
- raw results are retained,
- uncertainty is reported,
- negative findings are not filtered.

### Gate G10 — Hardware eligible

Physical autonomous tests are allowed only if:
- G5 and G6 pass,
- human E-stop has been tested,
- low-speed hardware profile exists,
- first tests are physically restrained/supported,
- logger is active.

---

# Project Definition of Done

The project reaches v1 completion only when all are true:

1. camera/ToF observations causally affect robot motion;
2. MaleCNS-derived activity lies on the action-selection path;
3. bypass/ablation of the connectome causes the predicted behavioral change;
4. safety remains independent and authoritative;
5. at least steering and looming/avoidance scenarios pass;
6. reproducible baseline comparison is complete;
7. final report states the result without overclaiming biological equivalence;
8. physical robot testing, if performed, passes the hardware safety gate;
9. tagged release contains configuration, source manifest, raw/processed results, and reproduction commands.
