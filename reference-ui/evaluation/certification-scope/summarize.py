"""Join anonymous grades to conditions after scoring, verifying coverage and totals."""
import csv
from collections import Counter
import json
from pathlib import Path

root = Path(__file__).resolve().parent
runs = json.loads((root / "trial/conditions.json").read_text())
expected = {(case, block, arm) for case in ("material", "isotope", "interlab")
            for block in (1, 2) for arm in ("baseline", "old", "revised")}
assert len(runs) == len(expected) and {(r["case"], r["block"], r["arm"]) for r in runs} == expected
by_label = {str(r["label"]): r for r in runs}
assert len(by_label) == len(runs)
for scores in sorted((root / "scoring").glob("grader-*.csv")):
    with scores.open() as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == len(runs) and {row["label"] for row in rows} == by_label.keys()
    totals, details = {}, Counter()
    for row in rows:
        run = by_label[row["label"]]
        assert row["case"] == run["case"]
        points = [int(row[f"i{i}"]) for i in range(1, 6)]
        flags = int(row["overclaim"])
        assert all(i in (0, 1) for i in [*points, flags])
        counts = totals.setdefault(run["arm"], Counter())
        counts.update(points=sum(points), scope=sum(points[:2]), overclaims=flags)
        details[run["case"], run["arm"]] += sum(points)
    print(scores.name)
    for arm in ("baseline", "old", "revised"):
        print(arm, dict(totals[arm]), {case: details[case, arm] for case in sorted({r["case"] for r in runs})})
