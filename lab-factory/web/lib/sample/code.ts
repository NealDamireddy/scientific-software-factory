// The Python the sample analysis app and simulation run. Each constant equals its file in python/
// byte for byte (lib/sample/code.test.ts checks this); edit the .py file and copy it here.

export const ANALYSIS_CODE = `"""Rate of colour loss from absorbance readings (standard library only)."""
import math


def _regress(shape, centered_a, mean_a):
    """Fit an intercept and amplitude to a fixed curve shape."""
    mean_x = sum(shape) / len(shape)
    dx = [x - mean_x for x in shape]
    amplitude = sum(x * y for x, y in zip(dx, centered_a)) / sum(x * x for x in dx)
    sse = sum((y - amplitude * x) ** 2 for x, y in zip(dx, centered_a))
    return sse, mean_a - amplitude * mean_x, amplitude


def analyze(readings):
    t = [float(x) for x in readings["time_s"]]
    a = [float(y) for y in readings["absorbance"]]
    if len(t) != len(a) or len(t) < 5:
        raise ValueError("The analysis needs at least 5 readings.")
    origin = min(t)
    elapsed = [x - origin for x in t]
    span = max(elapsed)
    if span <= 0:
        raise ValueError("time_s must increase.")
    if len(set(elapsed)) < 3:
        raise ValueError("The analysis needs readings at three or more different times to estimate a rate.")
    mean_a = sum(a) / len(a)
    centered_a = [y - mean_a for y in a]
    flat_sse = sum(y * y for y in centered_a)
    no_decay = {"decay": False, "rms_error": math.sqrt(flat_sse / len(a))}
    if flat_sse == 0:
        return no_decay

    def fit(k):
        return _regress([math.exp(-k * x) for x in elapsed], centered_a, mean_a)

    # At the slow limit the trace looks linear. At the fast limit it has
    # reached its plateau before the first positive elapsed time is sampled.
    earliest_interval = min(x for x in elapsed if x > 0)
    lowest, highest = 1e-5 / span, 36 / earliest_interval
    if not (0 < lowest < highest < math.inf):
        raise ValueError("The time range is too large or small to estimate a rate.")
    lo, hi = math.log(lowest), math.log(highest)
    grid = [math.exp(lo + (hi - lo) * i / 200) for i in range(201)]
    i = min(range(len(grid)), key=lambda j: fit(grid[j])[0])
    left, right = grid[max(0, i - 1)], grid[min(len(grid) - 1, i + 1)]
    for _ in range(60):
        m1, m2 = left + (right - left) / 3, right - (right - left) / 3
        if fit(m1)[0] < fit(m2)[0]:
            right = m2
        else:
            left = m1
    k = left + (right - left) / 2
    sse, a_end, amp = fit(k)
    if amp <= 0 or sse >= 0.9 * flat_sse:
        return no_decay

    # A linear fall or an instantaneous drop has no identifiable half-life.
    # Refuse these even when rounding places the minimum inside the grid.
    linear_sse = _regress([x / span for x in elapsed], centered_a, mean_a)[0]
    step_sse = _regress([x == 0 for x in elapsed], centered_a, mean_a)[0]
    if i in (0, len(grid) - 1) or min(linear_sse, step_sse) - sse <= 1e-12 * flat_sse:
        raise ValueError("These readings do not resolve a half-life. Include more readings during the decay.")
    return {"decay": True, "rate_constant_per_s": k, "half_life_s": math.log(2) / k,
            "a0": a_end + amp, "a_end": a_end, "time_origin_s": origin, "rms_error": math.sqrt(sse / len(a))}
`;

export const SIMULATION_CODE = `"""Absorbance over time for several amounts of reagent (standard library only).

Uses the same model as analysis.analyze: a(t) = a_end + (a0 - a_end) * exp(-k * t),
with the rate k proportional to the amount, k = k_per_mM * amount.
"""
import math


def simulate(amounts_mM=(0.5, 1.0, 2.0), k_per_mM=0.004, a0=0.8, a_end=0.05,
             duration_s=600, step_s=10):
    count = int(math.floor(duration_s / step_s + 1e-9)) + 1
    series = []
    for m in amounts_mM:
        k = k_per_mM * m
        points = []
        for i in range(count):
            t = i * step_s
            points.append([t, a_end + (a0 - a_end) * math.exp(-k * t)])
        series.append({"label": f"{float(m)} mM", "points": points})
    return {"series": series}
`;
