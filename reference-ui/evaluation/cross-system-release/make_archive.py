"""Create three independent, fictional water-lab exports for the retrieval evaluation."""
import argparse
import csv
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3

def write_json(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n")

def digest(label):
    return hashlib.sha256(label.encode()).hexdigest()

def create(dest):
    nb, ins, reg = (dest / s for s in ("notebook", "instrument", "registry"))
    for folder in (nb, ins, reg):
        folder.mkdir(parents=True, exist_ok=True)
    common, legacy, latest = map(digest, ["cond-core-1.8", "cond-core-1.6", "cond-core-1.9"])
    # Program binaries can legitimately be shared by different controlled procedures.
    (reg / "catalog.md").write_text("""Controlled library export. All effective dates are UTC. Applicability follows the acquisition timestamp, instrument serial, program SHA-256 and deployment interval. A signed run-specific variance takes precedence for the named fields only. Library publication time is distinct from deployment. Certificate targets belong to a particular lot. The system retains historical and withdrawn records.\n""")
    def doc(rev, low, high, units, publish):
        return dict(document="EC-41",revision=rev,published=publish,
                    reporting_units="uS/cm",control_units=units,required_controls=["L","H"],
                    acceptance=f"Each signed control must have absolute percentage error at most its level limit, using its assigned lot target. Compare before rounding. Limits: L {low}%, H {high}%.",
                    batch_disposition="Reporting requires a signed accepted disposition and both passing signed controls in this instrument batch. A recorded disposition cannot waive a failed limit.")
    for no,low,high,date in [(5,4,4,"2025-08-01"),(6,3,3,"2025-12-20"),(7,2,2,"2026-03-21"),(8,1,1,"2026-04-14")]:
        write_json(reg / f"EC-41.r{no}.json",doc(no,low,high,"uS/cm",date))
    deps=[]
    def dep(key,serial,sha,rev,start,end):
        deps.append(dict(id=key,serial=serial,program=sha,procedure=f"EC-41:r{rev}",start_utc=start,end_exclusive_utc=end,signature="registry-QA"))
    dep("DP-55","CX-04",legacy,5,"2025-08-01T00:00Z","2026-01-01T00:00Z")
    dep("DP-62","CX-04",common,6,"2026-01-01T00:00Z","2026-04-16T21:00Z")
    dep("DP-77","CX-04",common,7,"2026-04-16T21:00Z","2026-05-01T00:00Z")
    dep("DP-80","CX-04",latest,8,"2026-05-01T00:00Z","")
    dep("DP-49","CX-09",common,6,"2026-01-01T00:00Z","2026-05-01T00:00Z")
    write_json(reg/"deployment-history.json",deps)
    write_json(reg/"variances.json",[
        dict(id="VR-29",run="AQ-509",field="H limit",value="1.50%",signed="QA-A",recorded="2026-04-16T18:32Z",reason="project-specific precision agreement; all other fields inherit"),
        dict(id="VR-30",run="AQ-512",field="H limit",value="3.00%",signed=None,recorded="2026-04-16T18:42Z",reason="request only")])
    write_json(reg/"materials.json",[
        dict(lot="T-48",L="100.00",H="200.00",unit="uS/cm"),
        dict(lot="T-49",L="101.00",H="204.00",unit="uS/cm"),
        dict(lot="V-10",L="0.100",H="0.200",unit="mS/cm")])
    (nb/"export-notes.md").write_text("""The journal is append-only. A signed action by the release supervisor supersedes the earlier result selection when it explicitly refers to the same report line. Physical custody is established by a signed barcode transfer with a unique rack and well. A verbal attribution, expected routing, or matching result value is provisional. Times retain the offset of the person making the entry. All four report lines below originate in an environmental water study; all data, identities and signatures are fictional.\n""")
    notes=[]
    def jot(key,time,kind,signature,**values):
        notes.append(dict(entry=key,recorded=time,type=kind,signed_by=signature,**values))
    specs=[("731","AC-83","W-18","D07","L-01","EX-94","412.6"),("744","AC-19","W-44","C02","L-02","EX-81","317.8"),("752","AC-64","W-31","A11","L-03","EX-48","488.2"),("760","AC-11","W-23","B09","L-04","EX-60","390.0")]
    for j,(ident,acc,rack,well,line,receipt,value) in enumerate(specs):
        jot(f"N-{110+j}","2026-04-16T08:15:00-07:00","accession","intake-4",specimen="BW-"+ident,accession=acc)
        if ident!="760":
            jot(f"N-{241+j}","2026-04-16T11:20:00-07:00","scanned transfer","bench-6",accession=acc,rack=rack,well=well,transfer_type="physical seal read")
        else:
            jot("N-244","2026-04-16T11:20:00-07:00","transfer exception","bench-6",accessions=["AC-11","AC-12"],rack=rack,wells=["B09","B10"],details="Both seals lost at unloading; two positions occupied. Assignment to wells unresolved. No rescan logged.")
            jot("N-251","2026-04-16T12:23:00-07:00","routing note",None,accession=acc,rack=rack,well=well,details="Expected routing from worksheet; awaiting confirmation.")
        jot(f"N-{331+j}","2026-04-16T16:30:00-07:00","result selection","release-supervisor",line=line,accession=acc,receipt=receipt,value=value,unit="uS/cm")
    jot("N-404","2026-04-16T16:55:00-07:00","result selection amendment","release-supervisor",line="L-01",supersedes="N-331",receipt="EX-95",value="412.6",unit="uS/cm",reason="Authorized remeasurement; preserve the first acquisition.")
    jot("N-413","2026-04-16T17:05:00-07:00","handoff",None,line="L-01",receipt="EX-94",details="Bench copy from early printout.")
    for n in range(34):
        jot("N-"+str(800+n),"2026-04-16T15:10:00-07:00","scanned transfer","bench-2",accession=f"AC-X{n:02}",rack="U-16",well=f"D{n%12+1:02}")
    (nb/"journal.jsonl").write_text("".join(json.dumps(r)+"\n" for r in notes))
    with (nb/"report-lines.csv").open("w") as f:
        w=csv.writer(f,lineterminator="\n");w.writerow(["project","specimen","line","label"])
        w.writerows([["Watershed-B","BW-"+s[0],s[4],"Conductivity"] for s in specs])
    (ins/"archive-notes.md").write_text("""All times in the archive are UTC. Acquisitions are immutable. A control belongs to (serial, batch_uid), not to a display label or an entire instrument-day. Use the latest signed event per serial/batch/control level by its posted time at the requested cutoff. Only a signed batch disposition is authoritative. Receipt rows are exported results; identical numbers or display labels can occur in independent acquisitions.\n""")
    db=sqlite3.connect(ins/"acquisitions.sqlite")
    db.executescript("""
        CREATE TABLE runs(run TEXT PRIMARY KEY, serial TEXT, batch_uid TEXT, batch_label TEXT, acquired_utc TEXT, program_sha256 TEXT, rack TEXT, well TEXT, receipt TEXT UNIQUE, value_us_cm TEXT);
        CREATE TABLE controls(event TEXT PRIMARY KEY, serial TEXT, batch_uid TEXT, level TEXT, lot TEXT, observed TEXT, unit TEXT, posted_utc TEXT, signed_by TEXT, supersedes TEXT);
        CREATE TABLE dispositions(event TEXT PRIMARY KEY,serial TEXT,batch_uid TEXT,status TEXT,posted_utc TEXT,signed_by TEXT);
    """)
    runs=[
        ("AQ-501","CX-04","B-04","LOT-26","2026-04-16T20:15Z",common,"W-18","D07","EX-94","412.6"),
        ("AQ-509","CX-04","B-17","LOT-26","2026-04-16T21:04Z",common,"W-18","D07","EX-95","412.6"),
        ("AQ-512","CX-04","B-22","LOT-27","2026-04-16T21:16Z",common,"W-44","C02","EX-81","317.8"),
        ("AQ-518","CX-09","B-22","LOT-27","2026-04-16T21:32Z",common,"W-31","A11","EX-48","488.2"),
        ("AQ-526","CX-09","B-30","LOT-28","2026-04-16T21:59Z",common,"W-23","B09","EX-60","390.0"),
        ("AQ-527","CX-09","B-30","LOT-28","2026-04-16T22:02Z",common,"W-23","B10","EX-61","390.0")]
    base=datetime(2026,4,15,15,tzinfo=timezone.utc)
    for j in range(48):
        runs.append((f"AQ-{601+j}","CX-09",f"Y-{j//4:02}","LOT-26",(base+timedelta(minutes=7*j)).strftime("%Y-%m-%dT%H:%MZ"),common,"U-16",f"D{j%12+1:02}",f"EX-Y{j:02}",str(380+j)))
    db.executemany("INSERT INTO runs VALUES(?,?,?,?,?,?,?,?,?,?)",runs)
    early="2026-04-16T22:32Z"
    controls=[
        ("Q-12","CX-04","B-04","L","T-48","99","uS/cm",early,"qa-3",None),("Q-13","CX-04","B-04","H","T-48","211","uS/cm",early,"qa-3",None),
        ("Q-21","CX-04","B-17","L","V-10","100.8","uS/cm",early,"qa-5",None),("Q-22","CX-04","B-17","H","V-10","203.0","uS/cm",early,"qa-5",None),
        ("Q-31","CX-04","B-22","L","T-48","100.8","uS/cm",early,"qa-5",None),("Q-32","CX-04","B-22","H","T-48","204.006","uS/cm",early,"qa-5",None),
        ("Q-36","CX-04","B-22","H","T-48","203.96","uS/cm","2026-04-17T10:30Z","qa-5","Q-32"),
        ("Q-40","CX-09","B-22","L","T-49","101.60","uS/cm",early,"qa-3",None),("Q-41","CX-09","B-22","H","T-49","204.80","uS/cm",early,None,None),
        ("Q-51","CX-09","B-30","L","T-48","99.4","uS/cm",early,"qa-3",None),("Q-52","CX-09","B-30","H","T-48","202.4","uS/cm",early,"qa-3",None)]
    db.executemany("INSERT INTO controls VALUES(?,?,?,?,?,?,?,?,?,?)",controls)
    db.executemany("INSERT INTO dispositions VALUES(?,?,?,?,?,?)",[
        ("D-05","CX-04","B-04","reject",early,"qa-3"),("D-17","CX-04","B-17","accept",early,"qa-5"),
        ("D-22","CX-04","B-22","accept",early,"qa-5"),("D-35","CX-04","B-22","accept","2026-04-17T11:15Z","qa-5"),
        ("D-24","CX-09","B-22","accept",early,"qa-3"),("D-30","CX-09","B-30","accept",early,"qa-3")])
    db.commit();db.close()

if __name__=="__main__":
    args=argparse.ArgumentParser(description=__doc__)
    args.add_argument("dest",type=Path)
    create(args.parse_args().dest)
