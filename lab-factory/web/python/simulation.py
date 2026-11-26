"""Absorbance over time for several amounts of reagent (standard library only).

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
