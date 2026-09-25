# P8-R3 internal development comparison — FAIL

This is a deterministic synthetic RGB → graph-v2 screen, not a moving-body or robotd result. The full 54-case raw record is [`internal-development-raw-v1.json`](internal-development-raw-v1.json), 1,120,178 bytes, SHA256 `7d88b0a8607a55bea7ee5c2316b43924088c591e7e83a0eaf972cac533cfb969`. It was generated from frozen source/protocol commit `1e6f0abf47ebd97683bdcae403eb2200f2d7c290` after the documented pre-result harness failure in `internal-attempt-1-infrastructure-failure.md`.

The pinned graph-v2 JSON matched SHA256 `c4160c42941163079b6b569d117bf67afcf8b45eaa128c444f7c96c2567593cc`. The unchanged scenario, graph, neural model, sensory mapping, decoder threshold 0.5, safety settings, and 0.25 m boundary were used. Development seeds were 885301–885303; no final P8 seed was used. All candidate outputs were examined only after the freeze.

| Candidate | 65×33 approaches | 129×65 approaches | Static/receding stops | Paired resolution gate | Decision |
| --- | ---: | ---: | ---: | --- | --- |
| A log area | 3/3 preboundary stops | 3/3 preboundary stops | 0/12 | 2/3 pairs | FAIL |
| B relative radius | 3/3 | 3/3 | 0/12 | 2/3 pairs | FAIL |
| C 200 ms log area regression | 3/3 | 3/3 | 0/12 | 2/3 pairs | FAIL |

The failing pair is seed 885302 for **every** candidate. First positive looming was at 2.9 s at 65×33 and 2.7 s at 129×65; first DNp01 ≥0.5 and healthy stop were at 2.96 s and 2.76 s respectively. Both timing differences are 200 ms against the prospectively frozen maximum of one 10 Hz frame (100 ms). Peak LPLC2 was 1.0 at both resolutions (ratio 1.0). Seeds 885301 and 885303 met the timing and ratio criteria. The smallest first-stop boundary margin among all approaches was 0.06595 m. Every recorded neural step was runtime healthy. All three candidates saturated at peak looming 1.0 and DN peak 1.0, so this screen does not distinguish their amplitude behavior away from saturation.

No candidate meets all selection gates. Per the protocol, none is selected or promoted to official Thor recertification. The retained result is a negative development result; a separately versioned V2.1 hypothesis with new development seeds is required before another candidate screen.

## Observed cause of the 885302 skew

At 65×33, the first three RGB frames at 2.6, 2.7, and 2.8 s have identical pixel SHA256 (`d7249bcc64a3…`) and detected target area `0.06946387`; the first changed frame and positive looming occur at 2.9 s. At 129×65, these three frames have distinct hashes (`16a5ad145671…`, `a4c66c6afb03…`, `35acb8be64e0…`) and areas `0.06308885`, `0.07310674`, `0.08455575`. The binary low-resolution renderer quantizes this physical approach into an unchanged image for two frame intervals. After an estimator reset at arm, an area-only causal method cannot distinguish those frames from a static target before 2.9 s. All A/B/C peak at the output clamp of 1.0 once growth becomes visible.

This supports a new, separately versioned **RGB representation** hypothesis: fractional pixel coverage and an intensity-weighted target-area detector could retain subpixel expansion at 65×33. It would require new preregistration and development seeds, and cannot be treated as a parameter adjustment to these frozen A/B/C results.
