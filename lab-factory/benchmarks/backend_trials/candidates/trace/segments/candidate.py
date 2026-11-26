"""Segment an isolated peak in a sampled optical trace."""

from bisect import bisect_left
import math


def _numbers(values):
    if not isinstance(values, (list, tuple)):
        return None
    if any(type(value) not in (int, float) for value in values):
        return None
    try:
        numbers = [float(value) for value in values]
    except OverflowError:
        return None
    return numbers if all(map(math.isfinite, numbers)) else None


def _rising_arm(heights, indices, tolerance):
    # Times are strictly ordered, so the sign of a height difference gives
    # the sign of its segment derivative in the direction of traversal.
    crest = 0.0
    for i in indices:
        height = heights[i]
        if crest - height > tolerance:
            # This crest has a separating valley before the main summit.
            return False
        crest = max(crest, height)
    return True


def solve(request):
    abstain = {"status": "needs_input", "area": None}
    if not isinstance(request, dict):
        return abstain
    times = _numbers(request.get("times"))
    signals = _numbers(request.get("signals"))
    window = _numbers(request.get("window"))
    if times is None or signals is None or window is None or len(window) != 2:
        return abstain
    if len(times) != len(signals) or any(b <= a for a, b in zip(times, times[1:])):
        return abstain

    lo, hi = window
    span = hi - lo
    if span <= 0 or not math.isfinite(span):
        return abstain
    first = bisect_left(times, lo)
    last = bisect_left(times, hi)
    if last >= len(times) or last - first < 2 or times[first] != lo or times[last] != hi:
        return abstain
    t = times[first:last + 1]
    y = signals[first:last + 1]

    # Remove the endpoint chord before examining slopes. A steep baseline
    # can hide the falling arm entirely in the raw signal.
    drift = y[-1] - y[0]
    if not math.isfinite(drift):
        return abstain
    tolerance = 4 * math.ulp(max(map(abs, y)))
    heights = [0.0]
    for time, signal in zip(t[1:-1], y[1:-1]):
        if time - lo <= hi - time:
            height = (signal - y[0]) - ((time - lo) / span) * drift
        else:
            height = (signal - y[-1]) + ((hi - time) / span) * drift
        if not math.isfinite(height) or height < -tolerance:
            return abstain
        heights.append(height if height > tolerance else 0.0)
    heights.append(0.0)

    peak = max(heights)
    if peak == 0.0 or heights.count(peak) != 1:
        return abstain
    apex = heights.index(peak)
    left = next(i for i, h in enumerate(heights) if h > 0) - 1
    right = next(i for i in range(len(heights) - 1, apex - 1, -1) if heights[i] > 0) + 1
    if not _rising_arm(heights, range(left, apex + 1), tolerance):
        return abstain
    if not _rising_arm(heights, range(right, apex - 1, -1), tolerance):
        return abstain

    try:
        area = math.fsum(
            (heights[i] * 0.5 + heights[i + 1] * 0.5) * (t[i + 1] - t[i])
            for i in range(left, right)
        )
    except OverflowError:
        return abstain
    if not math.isfinite(area) or area <= 0:
        return abstain
    return {"status": "ok", "area": area}
