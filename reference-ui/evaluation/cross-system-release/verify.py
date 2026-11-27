"""Verify exported identity, method, and batch evidence for the frozen case using exact decimals."""
import argparse
import csv
import re
from datetime import datetime
from decimal import Decimal as D
from pathlib import Path
import json
import sqlite3

def stamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))

def verify(root):
    nb = root / "notebook"
    reg = root / "registry"
    journal = [json.loads(line) for line in (nb / "journal.jsonl").read_text().splitlines()]
    with (nb / "report-lines.csv").open(newline="") as f:
        reports = list(csv.DictReader(f))
    deployments = json.loads((reg / "deployment-history.json").read_text())
    lots = {r["lot"]:r for r in json.loads((reg / "materials.json").read_text())}
    exceptions = json.loads((reg / "variances.json").read_text())
    db = sqlite3.connect((root / "instrument/acquisitions.sqlite").resolve().as_uri()+"?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    scale = {"mS/cm":D(1000), "uS/cm":D(1)}
    results=[]
    for cut in ("2026-04-17T00:15Z","2026-04-17T18:00Z"):
        entries = sorted((j for j in journal if j["signed_by"] and stamp(j["recorded"]) <= stamp(cut)),
                         key=lambda j:stamp(j["recorded"]))
        for record in reports:
            specimen=record["specimen"]
            acc, = [j["accession"] for j in entries if j["type"]=="accession" and j["specimen"]==specimen]
            selection=[j for j in entries if j["type"].startswith("result selection") and
                       j["signed_by"]=="release-supervisor" and j["line"]==record["line"]][-1]
            run, = db.execute("SELECT * FROM runs WHERE receipt=?", (selection["receipt"],)).fetchall()
            custody=any(j["type"]=="scanned transfer" and (j["accession"],j["rack"],j["well"])==(acc,run["rack"],run["well"]) for j in entries)
            dep, = [p for p in deployments if p["serial"]==run["serial"] and p["program"]==run["program_sha256"] and
                    stamp(p["start_utc"]) <= stamp(run["acquired_utc"]) and (not p["end_exclusive_utc"] or stamp(run["acquired_utc"])<stamp(p["end_exclusive_utc"]))]
            rev=dep["procedure"].split(":r")[1]
            rule=json.loads((reg/f"EC-41.r{rev}.json").read_text())
            bounds={k:D(v) for k,v in re.findall(r"([LH]) (\d+(?:\.\d+)?)%",rule["acceptance"])}
            for var in exceptions:
                if var["run"]==run["run"] and var["signed"] and stamp(var["recorded"]) <= stamp(cut):
                    bounds[var["field"][0]]=D(var["value"].rstrip("%"))
            levels={}
            for row in db.execute("SELECT * FROM controls WHERE serial=? AND batch_uid=? AND signed_by IS NOT NULL ORDER BY posted_utc",
                                  (run["serial"],run["batch_uid"])):
                if stamp(row["posted_utc"]) <= stamp(cut):
                    levels[row["level"]]=row
            errors={}
            for level, row in levels.items():
                lot=lots[row["lot"]]
                target = D(lot[level])*scale[lot["unit"]]
                errors[level]=abs(D(row["observed"])*scale[row["unit"]]-target)*100/target
            disp=[d["status"] for d in db.execute("SELECT * FROM dispositions WHERE serial=? AND batch_uid=? AND signed_by IS NOT NULL ORDER BY posted_utc",
                                                   (run["serial"],run["batch_uid"])) if stamp(d["posted_utc"])<=stamp(cut)][-1]
            if not custody:
                decision="identity unresolved"
            elif set(errors)!=set(rule["required_controls"]):
                decision="QC unverified"
            elif any(e>bounds[k] for k,e in errors.items()) or disp!="accept":
                decision="withhold"
            else:
                decision="release"
            results.append(decision)
            print(cut,specimen,acc,run["receipt"],run["run"],dep["procedure"],run["serial"],run["batch_uid"],{k:str(v.quantize(D(".001"))) for k,v in errors.items()},disp,decision)
    db.close()
    assert results == ["release","withhold","QC unverified","identity unresolved","release","release","QC unverified","identity unresolved"]

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs",type=Path)
    verify(parser.parse_args().inputs)
