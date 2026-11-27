"""Summarize both blind score matrices and the exploratory paired votes."""
import csv
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SKILLS = {"15", "34", "79"}
BASELINE = {"21", "68", "87"}
OPTIONAL = {"43", "56"}

def records(name):
    with (ROOT / name).open(newline="") as f:
        return list(csv.DictReader(f))

for name in ("grader1.csv", "grader2.csv"):
    reviews = records(name)
    for group, ids in (("baseline", BASELINE), ("skills", SKILLS), ("optional", OPTIONAL)):
        marks = [r[c] for r in reviews if r["id"].strip() in ids for c in "ABCD"]
        assert len(marks) == len(ids)*4 and all(len(m) == 3 and set(m) <= set("01") for m in marks)
        print(name, group, "decisions", sum(int(m[0]) for m in marks), "/", len(marks),
              "evidence", sum(int(x) for m in marks for x in m[1:]), "/", len(marks)*2)

pairs = records("pairs.csv")
assert len(pairs) == 12
def translate(pair, side):
    if side == "T":
        return "tie"
    assert side in ("L","R")
    who = pair["left" if side == "L" else "right"]
    return "skills" if who in SKILLS else "baseline"

votes = []
for name in ("preference1.csv", "preference2.csv"):
    raw = {r["comparison"].zfill(2):r["choice"].strip().upper() for r in records(name)}
    assert set(raw) == {p["comparison"] for p in pairs}
    decoded = [translate(p, raw[p["comparison"]]) for p in pairs]
    votes.append(decoded)
    print(name, dict(Counter(decoded)))
for pair, a, b in zip(pairs, *votes):
    print(pair["comparison"], pair["case"], a, b)
print("consensus", dict(Counter(a if a == b else "disagree" for a,b in zip(*votes))))
