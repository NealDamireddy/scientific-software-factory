"""Recalculate the answer key from the exact CSVs supplied to the reviewers."""
import csv
from collections import defaultdict
from pathlib import Path
from statistics import mean

def read(name):
    with (Path(__file__).resolve().parents[1] / "packet" / (name + ".csv")).open() as f:
        return list(csv.DictReader(f))

standards = read("Formaldehyde")
x = [float(r["carb"]) for r in standards]
y = [float(r["optden"]) for r in standards]
sxy = sum((a-mean(x))*(b-mean(y)) for a,b in zip(x,y))
r2 = sxy**2 / (sum((a-mean(x))**2 for a in x) * sum((b-mean(y))**2 for b in y))
print("Formaldehyde: n, R², response interval, volume interval", len(x), r2, (min(y), max(y)), (min(x), max(x)))

chicks = [r for r in read("ChickWeight") if r["Diet"]=="1"]
def endpoint(day):
    pairs = [(r["Chick"], int(r["weight"])) for r in chicks if r["Time"]==day]
    assert len(dict(pairs)) == len(pairs)
    return dict(pairs)
birth, end = endpoint("0"), endpoint("21")
paired = birth.keys() & end.keys()
print("ChickWeight: birth, day 21, missing IDs", len(birth), len(end), sorted(map(int, birth.keys()-end.keys())))
print("Endpoint means, marginal difference, within-chick mean gain",mean(birth.values()),mean(end.values()),mean(end.values())-mean(birth.values()),mean(end[k]-birth[k] for k in paired))

rows = read("attenu")
events = defaultdict(list)
for r in rows:
    events[r["event"]].append(float(r["accel"]))
print("attenu: rows, events, station IDs missing",len(rows),len(events),sum(not r["station"] for r in rows))
print("Record mean, equal-event mean",mean(float(r["accel"]) for r in rows),mean(mean(v) for v in events.values()))
