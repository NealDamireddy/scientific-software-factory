"""Synthetic trace oracle. Positive peak areas follow triangle geometry, independent of quadrature."""

from math import isclose


def _triangle(t, start, apex, end, height):
    if t <= start or t >= end:
        return 0.0
    if t <= apex:
        return height * (t - start) / (apex - start)
    return height * (end - t) / (end - apex)


def _synthetic(times, peaks, offset=0.0, drift=0.0):
    return [offset + drift * t + sum(_triangle(t, *peak) for peak in peaks) for t in times]


def _request(times, signals, left, right):
    return {"times": list(times), "signals": list(signals), "window": [left, right]}


def _cases():
    uniform = list(range(11))
    single = [(2, 4, 8, 5)]
    irregular = [-0.5, 0.5, 1.25, 1.4, 1.875, 2.5, 2.625, 3.0, 4.5, 5.25, 6.75]
    odd_peak = [(1.25, 2.5, 5.25, 3.75)]
    neighbor = [(1, 2, 5, 4), (6, 8, 10, 30)]
    two_peaks = [(1, 3, 6, 8), (4, 7, 9, 6)]
    vertical = _synthetic(uniform, single, offset=9)
    return [
        ("single_peak", _request(uniform, vertical, 2, 8), 15.0),
        ("sloping_baseline", _request(uniform, _synthetic(uniform, single, -2.5, 0.625), 2, 8), 15.0),
        ("irregular_times", _request(irregular, _synthetic(irregular, odd_peak, 9.0, -0.75), 1.25, 5.25), 7.5),
        ("neighbor_outside_window", _request(uniform, _synthetic(uniform, neighbor, 1, 0.25), 1, 5), 8.0),
        ("shallow_peak_on_large_background",
         _request(uniform, _synthetic(uniform, [(1, 6, 9, 0.03125)], 1000, 13), 1, 9), 0.125),
        ("overlapping_peaks", _request(uniform, _synthetic(uniform, two_peaks, 3, -0.2), 1, 9), None),
        ("flat_trace", _request(uniform, [2.5] * len(uniform), 2, 8), None),
        ("linear_background_without_peak", _request(uniform, _synthetic(uniform, [], 22, 1.625), 2, 8), None),
        ("window_partly_unobserved", _request(uniform, vertical, -1, 8), None),
        ("off_grid_boundary", _request(uniform, vertical, 2.25, 8), None),
        ("reversed_time_axis", _request(reversed(uniform), reversed(vertical), 2, 8), None),
        ("duplicate_timestamp", _request([0, 1, 2, 2, 3, 4], [0, 1, 2, 2, 1, 0], 0, 4), None),
        ("mismatched_columns", _request(uniform, vertical[:-1], 2, 8), None),
    ]


def grade(candidate):
    solve = getattr(candidate, "solve", candidate)
    results = []
    for name, payload, expected in _cases():
        try:
            reply = solve(payload)
            area = reply["area"]
            if expected is None:
                passed = reply.get("status") == "needs_input" and area is None
                detail = f"Expected needs_input and no area; received {reply!r}"
            else:
                passed = (
                    reply.get("status") == "ok" and type(area) in (float, int)
                    and isclose(area, expected, rel_tol=1e-6, abs_tol=1e-8)
                )
                detail = f"Expected area {expected:g} (rtol 1e-6, atol 1e-8); received {reply!r}"
        except Exception as exc:
            passed, detail = False, f"{type(exc).__name__}: {exc}"
        results.append((name, passed, detail))
    return results
