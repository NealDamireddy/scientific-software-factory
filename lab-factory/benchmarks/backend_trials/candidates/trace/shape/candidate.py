"""Fit an isolated triangular feature to simulated optical measurements."""

from bisect import bisect_left
from math import fsum, isfinite, ulp


def _numbers(values):
    if not isinstance(values, (list, tuple)):
        raise ValueError
    if any(type(value) not in (int, float) for value in values):
        raise ValueError
    result = [float(value) for value in values]
    if not all(map(isfinite, result)):
        raise ValueError
    return result


def _fit_line(x, y, first, last):
    """Least-squares arm height in coordinates relative to its first sample."""
    origin = x[first]
    span = x[last] - origin
    if span <= 0:
        raise ValueError
    positions = [(x[i] - origin) / span for i in range(first, last + 1)]
    heights = y[first:last + 1]
    mean_x = fsum(positions) / len(positions)
    mean_y = fsum(heights) / len(heights)
    variance = fsum((u - mean_x) ** 2 for u in positions)
    slope = fsum((u - mean_x) * (v - mean_y)
                 for u, v in zip(positions, heights)) / variance
    return slope, lambda point: mean_y + slope * ((point - origin) / span - mean_x)


def _matches_triangle(x, y, first, last, peak, tolerance):
    # The true apex can fall on the highest sample or in either adjacent gap.
    # Fit each arm on the positive samples so zero-valued tails do not tilt it.
    for left_end, right_start in ((peak, peak), (peak - 1, peak), (peak, peak + 1)):
        if left_end < first or right_start > last:
            continue
        left_start = first - 1 if left_end == first else first
        right_end = last + 1 if right_start == last else last
        rise, left = _fit_line(x, y, left_start, left_end)
        fall, right = _fit_line(x, y, right_start, right_end)
        if rise <= 0 or fall >= 0:
            continue
        for position, observed in zip(x, y):
            predicted = max(0.0, min(left(position), right(position)))
            if abs(predicted - observed) > tolerance:
                break
        else:
            return True
    return False


def _area(request):
    times = _numbers(request["times"])
    signals = _numbers(request["signals"])
    lo, hi = _numbers(request["window"])
    if len(times) != len(signals) or lo >= hi:
        return None
    if any(b <= a for a, b in zip(times, times[1:])):
        return None
    start, end = bisect_left(times, lo), bisect_left(times, hi)
    if end >= len(times) or times[start] != lo or times[end] != hi or end - start < 2:
        return None

    x = times[start:end + 1]
    signal = signals[start:end + 1]
    span = hi - lo
    drift = signal[-1] - signal[0]
    if not isfinite(span) or not isfinite(drift):
        return None
    residuals = [(v - signal[0]) - drift * ((t - lo) / span) for t, v in zip(x, signal)]
    if not all(map(isfinite, residuals)):
        return None
    peak = max(range(len(x)), key=residuals.__getitem__)
    height = residuals[peak]
    roundoff = 8 * ulp(max(map(abs, signal)))
    if height <= roundoff:
        return None
    y = [value / height for value in residuals]
    tolerance = max(1e-8, roundoff / height)
    if min(y) < -tolerance:
        return None
    first = next(i for i, v in enumerate(y) if v > tolerance)
    last = next(i for i in reversed(range(len(y))) if y[i] > tolerance)

    # A second rise after a valley, or a second sample at peak height, makes
    # the position of the measured maximum ambiguous.
    if sum(1 for v in y if 1 - v <= tolerance) != 1:
        return None
    for flank in (y[:peak + 1], y[peak:][::-1]):
        highest = 0.0
        for value in flank:
            if value < highest - tolerance:
                return None
            highest = max(highest, value)
    if not _matches_triangle(x, y, first, last, peak, tolerance):
        return None

    # Integrate the observed piecewise-linear trace at its actual timestamps.
    positive = [max(0.0, v) for v in residuals]
    area = fsum((right - left) * (0.5 * a + 0.5 * b)
                for left, right, a, b in zip(x, x[1:], positive, positive[1:]))
    return area if isfinite(area) and area > 0 else None


def solve(request):
    """Return the sampled area above the endpoint line, or request more input."""
    try:
        area = _area(request)
    except (KeyError, TypeError, ValueError, OverflowError):
        area = None
    if area is None:
        return {"status": "needs_input", "area": None}
    return {"status": "ok", "area": area}
