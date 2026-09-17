# Looming Estimator

Task: **P4-02**

The Phase 4 looming feature is an engineering approximation built from the rate of increase of detected target area. It is not a claim that camera area-rate reproduces fly LPLC2 physiology.

For two valid consecutive samples:

```text
area_rate = max(0, current_area - previous_area) / delta_time_seconds
looming   = clamp(area_rate / full_scale_area_rate_per_s, 0, 1)
```

Rules:

- stationary and receding targets produce zero;
- first valid sample establishes a baseline and produces zero;
- invalid source resets estimator state and produces zero;
- a gap greater than `max_gap_ms` treats the current sample as a new baseline and produces zero;
- valid timestamps must increase strictly;
- output is always finite in `[0,1]`.

The default freshness gap is 100 ms, matching the frozen perception TTL. The estimator does not select a neural population, generate behavior intent, or issue robot commands.
