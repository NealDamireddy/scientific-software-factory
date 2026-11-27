"""Recompute the paired-context numeric key directly from the frozen CSVs."""
import csv
from pathlib import Path
from statistics import linear_regression, mean
from collections import defaultdict

root = Path(__file__).resolve().parents[1] / "shared"

def records(filename):
    with (root / filename).open() as stream:
        return list(csv.DictReader(stream))

standards = records("Formaldehyde.csv")
slope, intercept = linear_regression([float(r["carb"]) for r in standards],
                                     [float(r["optden"]) for r in standards])
def volume(od):
    return (od - intercept) / slope

error = 100 * abs(volume(.460) - .5000) / .5000
print("U17 volume, Q17 volume, Q17 absolute error (%)", volume(.538), volume(.460), error)
assert 2 < error <= 5

birds = [r for r in records("ChickWeight.csv") if r["Diet"] == "1"]
def endpoint(day):
    subset = [r for r in birds if r["Time"] == day]
    by_bird = {r["Chick"]: int(r["weight"]) for r in subset}
    assert len(by_bird) == len(subset)
    return by_bird
birth, end = endpoint("0"), endpoint("21")
paired = birth.keys() & end.keys()
print("N at birth, end, paired", len(birth), len(end), len(paired))
print("Paired gain and difference of observed means", mean(end[k]-birth[k] for k in paired),
      mean(end.values()) - mean(birth.values()))

quakes = records("attenu.csv")
by_event = defaultdict(list)
for row in quakes:
    by_event[row["event"]].append(float(row["accel"]))
print("Reading-weighted and event-weighted means",
      mean(float(r["accel"]) for r in quakes), mean(mean(v) for v in by_event.values()))
print("Source line 80", quakes[78])
