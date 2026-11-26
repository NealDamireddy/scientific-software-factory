"""Endpoint-corrected trapezoidal integration for a single optical feature."""

import math
from bisect import bisect_left


def _finite_number(value):
    return type(value) is int or (type(value) is float and math.isfinite(value))


def _rises_to_peak(heights, indices, tolerance):
    highest = 0.0
    for index in indices:
        height = heights[index]
        if highest - height > tolerance:
            return False
        highest = max(highest, height)
    return True


def _window_area(times, signals):
    span = times[-1] - times[0]
    drift = signals[-1] - signals[0]
    if not math.isfinite(span) or not math.isfinite(drift):
        return None

    heights = [0.0]
    for time, signal in zip(times[1:-1], signals[1:-1]):
        left = time - times[0]
        right = times[-1] - time
        # Anchor at the nearer endpoint to limit cancellation on steep baselines.
        if left <= right:
            height = (signal - signals[0]) - (left / span) * drift
        else:
            height = (signal - signals[-1]) + (right / span) * drift
        if not math.isfinite(height):
            return None
        heights.append(height)
    heights.append(0.0)

    peak = max(heights)
    input_ulp = max((math.ulp(y) for y in signals if type(y) is float), default=0.0)
    tolerance = 4 * max(input_ulp, math.ulp(drift), math.ulp(peak))
    if peak <= tolerance:
        return None

    # Inspect both flanks toward the apex. A resolved dip followed by a rise
    # indicates another maximum, even when the two peaks have different heights.
    apex = heights.index(peak)
    if not _rises_to_peak(heights, range(apex + 1), tolerance):
        return None
    if not _rises_to_peak(heights, range(len(heights) - 1, apex - 1, -1), tolerance):
        return None

    area = math.fsum(
        (times[i] - times[i - 1])
        * (0.5 * max(0.0, heights[i - 1]) + 0.5 * max(0.0, heights[i]))
        for i in range(1, len(times))
    )
    return area if math.isfinite(area) and area > 0.0 else None


def solve(request):
    needs_input = {"status": "needs_input", "area": None}
    if not isinstance(request, dict):
        return needs_input
    times, signals, window = (request.get(key) for key in ("times", "signals", "window"))
    if not all(isinstance(v, (list, tuple)) for v in (times, signals, window)):
        return needs_input
    if len(times) != len(signals) or len(window) != 2 or not all(map(_finite_number, window)):
        return needs_input
    if not all(map(_finite_number, times)) or any(b <= a for a, b in zip(times, times[1:])):
        return needs_input

    lo, hi = window
    start, stop = bisect_left(times, lo), bisect_left(times, hi)
    if stop - start < 2 or stop == len(times) or times[start] != lo or times[stop] != hi:
        return needs_input
    samples = signals[start : stop + 1]
    if not all(map(_finite_number, samples)):
        return needs_input

    try:
        area = _window_area(times[start : stop + 1], samples)
    except OverflowError:
        return needs_input
    return needs_input if area is None else {"status": "ok", "area": area}
