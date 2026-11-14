"""Run one project-scoped engineering task and preserve a self-contained evidence directory."""
from datetime import datetime, timezone
import io
import csv
import importlib.metadata
import math
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import uuid

from .agent import generate
from .context import ROOT, check, digest, dump, preflight, read_json, resolve
from .fixtures import specimen
from .evolution import EXTENSION, check_fit_quality, covers_behavior, noisy_series
from .sandbox import execute


def evaluate(output, expected, project, rows):
    details = []
    for key, target in expected.items():
        measured = output.get(key)
        tolerance = 0.002 if project == "linewidth" else (1e-6 if key == "coefficient_au_K" else 1e-8)
        passed = type(measured) in (int, float) and math.isfinite(measured) and abs(measured-target) <= tolerance
        details.append({"field":key, "expected":target, "actual":measured, "tolerance":tolerance, "pass":passed})
    if project == "curie":
        for key, target in (("predicted_au",[r[1] for r in rows]), ("residual_au",[0.0]*len(rows))):
            actual = output.get(key)
            passed = isinstance(actual,list) and len(actual)==len(target) and all(
                type(y) in (float,int) and math.isfinite(y) and abs(y-v)<=1e-8 for y,v in zip(actual,target))
            details.append({"field":key,"expected":target,"actual":actual,"tolerance":1e-8,"pass":passed})
    else:
        for key, sign in (("peak_mT",-1),("trough_mT",1)):
            target = expected["center_mT"] + sign*expected["linewidth_mT"]/2
            value = output.get(key)
            details.append({"field":key,"expected":target,"actual":value,"tolerance":0.002,
                            "pass":type(value) in (float,int) and abs(value-target)<=0.002})
    return details


def numbers(data):
    return [list(map(float,row)) for row in list(csv.reader(io.StringIO(data.decode())))[1:]]


def reference_suite(source, project, metadata, quality=False):
    cases = [(f"analytic-{i+1}", *specimen(project,i), metadata) for i in range(3)]
    if project == "linewidth":
        data, expected = specimen(project)
        gauss = "field_G,signal_au\n" + "".join(f"{x*10:.9f},{y:.14g}\n" for x,y in numbers(data))
        cases.append(("declared-gauss",gauss.encode(),expected,dict(metadata,units={"field":"G","signal":"a.u."})))
    results = []
    for name, data, expected, meta in cases:
        actual, _ = execute(source,data,meta)
        metrics = evaluate(actual,expected,project,numbers(data))
        if quality:
            metrics.append(check_fit_quality(actual,numbers(data)))
        results.append({"case":name,"input_sha256":digest(data),"metrics":metrics,"pass":all(m["pass"] for m in metrics)})
    if quality:
        data = noisy_series()
        actual, _ = execute(source,data,metadata)
        metric = check_fit_quality(actual,numbers(data))
        results.append({"case":"noisy-fit-quality","input_sha256":digest(data),"metrics":[metric],"pass":metric["pass"]})
    return results


def verify_files(folder):
    report = read_json(folder/"report.json")
    required = {"input.csv","context.json","metadata.json","work-order.json","uv.lock"}
    if report["status"] in ("verified", "review"):
        required |= {"analysis.py","output.json","generation.json","agent-prompt.txt"}
    if not required <= report["artifacts"].keys():
        raise ValueError("Evidence manifest missing required artifacts")
    if report["source_revision"] and report["artifacts"].get("analysis.py",{}).get("sha256") != report["source_revision"]:
        raise ValueError("Source revision differs from the artifact manifest")
    for name, entry in report["artifacts"].items():
        path = folder / name
        if Path(name).name != name or path.is_symlink() or not path.is_file() or digest(path.read_bytes()) != entry["sha256"]:
            raise ValueError("Artifact hash mismatch: " + name)
    return report


def run(order, store, mode="replay", previous=None):
    ctx = resolve(order)
    project = ctx["project"]
    fixture = ROOT / "fixtures" / project["dataset"]
    data = (fixture/"input.csv").read_bytes()
    meta = read_json(fixture/"metadata.json")
    project_store = Path(store) / project["id"]
    project_store.mkdir(parents=True,exist_ok=True)
    when = datetime.now(timezone.utc)
    run_id = when.strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8]
    with tempfile.TemporaryDirectory(prefix=".stage-",dir=project_store) as temp:
        folder = Path(temp)
        for name, value in (("work-order",order),("context",ctx),("metadata",meta)):
            dump(folder/(name+".json"),value)
        (folder/"input.csv").write_bytes(data)
        shutil.copyfile(ROOT/"uv.lock",folder/"uv.lock")
        checks = preflight(order,ctx,meta,data)
        results = []
        source = folder/"analysis.py"
        invalid = any(c["status"] != "pass" for c in checks)
        report = {"format":1,"id":run_id,"created_utc":when.isoformat(),"lab":order["lab"],"project":project["id"],
                  "instrument":order["instrument"],"work_order":order["id"],"origin":order["origin"],
                  "upstream_id":order.get("upstream_id"),"mode":mode,"dataset":project["dataset"],
                  "input_ref":f"fixtures/{project['dataset']}/input.csv","parameters":order["parameters"],
                  "environment":{"python":platform.python_version(),"platform":platform.system(),"machine":platform.machine(),
                                 "jsonschema":importlib.metadata.version("jsonschema"),"application_dependencies":"Python standard library"},
                  "checks":checks,"tests":results,"human_review":list(dict.fromkeys([*order["review"],*ctx["standards"]["human"]])),
                  "status":"blocked" if invalid else "verified","source_revision":None,"parent_source_revision":None,
                  "factory_sha256":digest(b"".join(p.name.encode()+p.read_bytes() for p in sorted((ROOT/"factory").glob("*.py"))))}
        try:
            if not invalid:
                base = None
                if previous:
                    old = verify_files(previous)
                    if old["project"] != project["id"] or old["lab"] != order["lab"] or old["status"] != "verified":
                        raise ValueError("Base run must be verified in the same lab and project")
                    base = (previous/"analysis.py").read_text()
                    report["parent_source_revision"] = old["source_revision"]
                if mode == "generate":
                    generate(order,ctx,folder,base)
                elif mode == "replay":
                    baseline = previous or ROOT/"generated"/project["id"]
                    for name in ("analysis.py","agent-prompt.txt","generation.json"):
                        shutil.copyfile(baseline/name,folder/name)
                else:
                    raise ValueError("Unknown execution mode")
                report["source_revision"] = digest(source.read_bytes())
                output, jail = execute(source,data,meta)
                report["environment"]["sandbox"] = jail
                dump(folder/"output.json",output)
                checks.append(check("execution","pass","Generated application exited successfully and returned JSON.","software"))
                results.extend(reference_suite(source,project["id"],meta, project["id"]=="curie" and EXTENSION in order["acceptance"]))
                passed = all(test["pass"] for test in results)
                checks.append(check("reference","pass" if passed else "fail",
                                    f"{sum(t['pass'] for t in results)} of {len(results)} independent analytic cases passed.","numerical"))
                if not passed: report["status"] = "failed"
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            checks.append(check("runtime","fail",str(exc),"software"))
            report["status"] = "failed"
        if not any(c["name"]=="reference" for c in checks):
            checks.append(check("reference","untested","Generation or execution did not reach the numerical suite.","numerical"))
        if not source.exists():
            checks.append(check("execution","untested","Scientific program did not run.","software"))
        for requested in sorted(set(order["acceptance"]) - {project["reference"],*project.get("extensions",{})} | (set(order["verification"]) - set(ctx["standards"]["checks"]))):
            checks.append(check(requested,"untested","No independent check registered for this requirement.","requirement"))
            if report["status"]=="verified": report["status"]="review"
        if project["reference"] not in order["acceptance"] or not covers_behavior(order, project):
            checks.append(check("behavior coverage","untested","Custom behavior needs a dedicated acceptance test.","requirement"))
            if report["status"]=="verified": report["status"]="review"
        checks.append(check("physical instrument","untested","All inputs are synthetic. No hardware connection was opened.","real instrument"))
        report["artifacts"] = {p.name:{"sha256":digest(p.read_bytes()),"bytes":p.stat().st_size}
                               for p in sorted(folder.iterdir()) if p.is_file()}
        checks.append(check("provenance","pass","Raw input, acquisition metadata, configuration and available artifacts hashed with SHA-256.","reproducibility"))
        report["unresolved"] = [c["name"] for c in checks if c["status"] != "pass"]
        dump(folder/"report.json",report)
        verify_files(folder)
        target = project_store / run_id
        folder.rename(target)
    return target
