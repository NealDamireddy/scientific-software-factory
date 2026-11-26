"""Tests for the analysis and simulation code that runs in the browser."""
import math
import unittest

from analysis import analyze
from simulation import simulate


def _mulberry32(seed):
    state = seed & 0xFFFFFFFF

    def imul(a, b):
        return (a * b) & 0xFFFFFFFF

    def draw():
        nonlocal state
        state = (state + 0x6D2B79F5) & 0xFFFFFFFF
        t = imul(state ^ (state >> 15), 1 | state)
        t = ((t + imul(t ^ (t >> 7), 61 | t)) & 0xFFFFFFFF) ^ t
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296

    return draw


def synthetic_readings(k, a0, a_end, noise, seed, step_s=10, duration_s=600):
    """Mirrors syntheticReadings in lib/readings.ts."""
    rand = _mulberry32(seed)
    count = int(math.floor(duration_s / step_s + 1e-9)) + 1
    time_s, absorbance = [], []
    for i in range(count):
        t = i * step_s
        value = a_end + (a0 - a_end) * math.exp(-k * t) + noise * (2 * rand() - 1)
        time_s.append(round(t, 4))
        absorbance.append(round(value, 4))
    return {"time_s": time_s, "absorbance": absorbance}


class AnalyzeTest(unittest.TestCase):
    def test_clean_decay_recovers_the_rate_within_1_percent(self):
        result = analyze(synthetic_readings(k=0.01, a0=0.8, a_end=0.05, noise=0, seed=1))
        self.assertTrue(result["decay"])
        self.assertAlmostEqual(result["rate_constant_per_s"] / 0.01, 1, delta=0.01)

    def test_noisy_decay_recovers_the_rate_within_5_percent(self):
        result = analyze(synthetic_readings(k=0.01, a0=0.8, a_end=0.05, noise=0.005, seed=3))
        self.assertTrue(result["decay"])
        self.assertAlmostEqual(result["rate_constant_per_s"] / 0.01, 1, delta=0.05)

    def test_time_offsets_preserve_the_fit(self):
        times = list(range(0, 601, 10))
        values = [0.05 + 0.75 * math.exp(-0.0085 * t) for t in times]
        for origin in (-3600, 0, 3600, 1_700_000_000):
            with self.subTest(origin=origin):
                result = analyze({"time_s": [origin + t for t in times], "absorbance": values})
                self.assertEqual(result["time_origin_s"], origin)
                self.assertAlmostEqual(result["half_life_s"], math.log(2) / 0.0085)
                self.assertAlmostEqual(result["a0"], values[0])
                self.assertAlmostEqual(result["rms_error"], 0)

    def test_extending_the_plateau_preserves_a_fast_rate(self):
        for duration in (120, 600):
            with self.subTest(duration=duration):
                times = list(range(duration + 1))
                values = [0.05 + 0.75 * math.exp(-0.2 * t) for t in times]
                result = analyze({"time_s": times, "absorbance": values})
                self.assertAlmostEqual(result["rate_constant_per_s"], 0.2)

    def test_unresolved_fits_report_why_a_half_life_cannot_be_given(self):
        times = [0, 1, 2, 3, 4]
        for values in ([5, 4, 3, 2, 1], [1, 0, 0, 0, 0]):
            with self.subTest(values=values), self.assertRaisesRegex(ValueError, "do not resolve a half-life"):
                analyze({"time_s": times, "absorbance": values})
        with self.assertRaisesRegex(ValueError, "three or more different times"):
            analyze({"time_s": [0, 0, 0, 1, 1], "absorbance": [1, 1, 1, 0.5, 0.5]})

    def test_flat_readings_show_no_decay(self):
        result = analyze(synthetic_readings(k=0, a0=0.5, a_end=0.5, noise=0.002, seed=5))
        self.assertFalse(result["decay"])

    def test_four_readings_are_too_few(self):
        readings = {"time_s": [0, 10, 20, 30], "absorbance": [0.8, 0.7, 0.6, 0.5]}
        with self.assertRaises(ValueError) as caught:
            analyze(readings)
        self.assertEqual(str(caught.exception), "The analysis needs at least 5 readings.")


class SimulateTest(unittest.TestCase):
    def test_default_simulation_has_three_series_of_61_points(self):
        result = simulate()
        self.assertEqual(len(result["series"]), 3)
        for series in result["series"]:
            self.assertEqual(len(series["points"]), 61)
        self.assertEqual([s["label"] for s in result["series"]], ["0.5 mM", "1.0 mM", "2.0 mM"])

    def test_simulation_uses_the_same_decay_model(self):
        points = simulate(amounts_mM=(1.0,))["series"][0]["points"]
        self.assertEqual(points[0][0], 0)
        self.assertAlmostEqual(points[0][1], 0.8, places=9)
        t, a = points[30]
        self.assertEqual(t, 300)
        self.assertAlmostEqual(a, 0.05 + 0.75 * math.exp(-0.004 * t), places=9)


if __name__ == "__main__":
    unittest.main()
