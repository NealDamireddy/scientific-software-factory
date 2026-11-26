// The Python the sample analysis app and simulation run. Each constant equals its file in python/
// byte for byte (lib/sample/code.test.ts checks this); edit the .py file and copy it here.

export const ANALYSIS_CODE = `"""Rate of colour loss from absorbance readings (standard library only)."""
import math


def _fit(t, a, k):
    e = [math.exp(-k * x) for x in t]
    n, se, see = len(t), sum(e), sum(x * x for x in e)
    sa, sea = sum(a), sum(x * y for x, y in zip(e, a))
    det = n * see - se * se
    if abs(det) < 1e-12:
        return None
    a_end = (see * sa - se * sea) / det
    amp = (n * sea - se * sa) / det
    sse = sum((y - a_end - amp * x) ** 2 for x, y in zip(e, a))
    return sse, a_end, amp


def analyze(readings):
    t = [float(x) for x in readings["time_s"]]
    a = [float(y) for y in readings["absorbance"]]
    if len(t) != len(a) or len(t) < 5:
        raise ValueError("The analysis needs at least 5 readings.")
    span = max(t) - min(t)
    if span <= 0:
        raise ValueError("time_s must increase.")
    mean = sum(a) / len(a)
    flat_sse = sum((y - mean) ** 2 for y in a)
    lo, hi = math.log(0.01 / span), math.log(50 / span)
    grid = [math.exp(lo + (hi - lo) * i / 400) for i in range(401)]
    fits = [(f, k) for k in grid if (f := _fit(t, a, k)) is not None]
    i = min(range(len(fits)), key=lambda j: fits[j][0][0])
    left = fits[max(i - 1, 0)][1]
    right = fits[min(i + 1, len(fits) - 1)][1]
    for _ in range(60):
        m1, m2 = left + (right - left) / 3, right - (right - left) / 3
        if _fit(t, a, m1)[0] < _fit(t, a, m2)[0]:
            right = m2
        else:
            left = m1
    k = (left + right) / 2
    sse, a_end, amp = _fit(t, a, k)
    rms = math.sqrt(sse / len(t))
    if amp <= 0 or flat_sse == 0 or sse >= 0.9 * flat_sse:
        return {"decay": False, "rms_error": math.sqrt(flat_sse / len(t))}
    return {"decay": True, "rate_constant_per_s": k, "half_life_s": math.log(2) / k,
            "a0": a_end + amp, "a_end": a_end, "rms_error": rms}
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
