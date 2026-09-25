# P8-R3 V2.1 internal development comparison — PASS

The full 36-case paired raw record is [`v21-internal-development-raw-v1.json`](v21-internal-development-raw-v1.json), 779,698 bytes, SHA256 `55e4f9e2db6fda448e89114d46ebcabae6532fc853e8b7d00e72a482ee3d1050`. It was produced from prospectively frozen source/protocol commit `f96569629200f1bc07defea7ed860861ce297011` with development-only seeds 885401–885403, 10 Hz RGB and 50 Hz neural updates. It is a fixed-pose virtual-obstacle RGB → graph-v2 result; no moving body, robotd transport, or official stop is established.

The fractional V2.1 renderer/detector plus the unchanged V2 A log-area estimator **passes the preregistered internal gate**: at each of 65×33 and 129×65, all 3/3 approaches reached healthy DNp01 ≥0.5 and EscapeDecoder stop at positive 0.25 m boundary margin; 0/6 static/receding controls stopped. Every recorded neural step was runtime healthy. The paired binary renderer/detector plus the same A estimator ran on the same seeds and geometry as descriptive baseline and retained its 200 ms resolution skew at seed 885402.

| Representation | Seed | First looming 65×33 / 129×65 (s) | First DN ≥0.5, both resolutions (s) | Pair timing difference (ms) | LPLC2 peak ratio | First-stop margins 65×33 / 129×65 (m) | Gate |
| --- | ---: | --- | --- | ---: | ---: | --- | --- |
| Fractional V2.1 | 885401 | 2.1 / 2.1 | 2.16 | 0 | 1.0 | 0.2603 / 0.2603 | PASS |
| Fractional V2.1 | 885402 | 2.7 / 2.7 | 2.76 | 0 | 1.0 | 0.1410 / 0.1410 | PASS |
| Fractional V2.1 | 885403 | 3.1 / 3.1 | 3.16 | 0 | 1.0 | 0.0678 / 0.0678 | PASS |
| Binary baseline | 885401 | 2.2 / 2.1 | 2.26 / 2.16 | 100 | 1.0 | 0.2403 / 0.2603 | PASS |
| Binary baseline | 885402 | 2.9 / 2.7 | 2.96 / 2.76 | 200 | 1.0 | 0.1010 / 0.1410 | FAIL |
| Binary baseline | 885403 | 3.1 / 3.1 | 3.16 | 0 | 1.0 | 0.0678 / 0.0678 | PASS |

The fractional signal's first positive time and first threshold time differed by 0 ms across resolutions in each seed, within the ≤100 ms paired tolerance; every LPLC2 peak ratio was 1.0, within [0.75, 1.333]. The smallest first-stop margin was 0.0678 m. Both representations saturated at peak looming/LPLC2 1.0; this screen establishes early timing and neural threshold in the frozen synthetic scenario, not graded-response calibration across unsaturated scenes.

Per protocol, the next development step is a **separate** 10/20/25 Hz sampling comparison of this fixed fractional representation, estimator and controls. The official Thor three-reset recertification and P8-02 final trials have not run.
