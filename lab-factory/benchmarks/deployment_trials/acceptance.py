"""Run the pinned deployment workload over HTTP in an isolated, disposable lab."""

import argparse
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
import secrets
import stat
import sys
import threading
from urllib.parse import urlsplit

import httpx

from labfactory.hosted_auth import SESSION_COOKIE, password_hash, token_digest


FIXTURES = Path(__file__).resolve().with_name("fixtures")
TOOLS = {"claim_work_order", "get_work_order_context", "list_work_orders", "submit_artifact"}
WORKERS = ("agent-a", "agent-b")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def workload():
    manifest = json.loads((FIXTURES / "manifest.json").read_bytes())
    raw = (FIXTURES / "workload.json").read_bytes()
    require(sha(raw) == manifest["workload_sha256"], "Pinned workload digest mismatch")
    data = json.loads(raw)
    for name, artifact in data["artifacts"].items():
        require(sha(canonical(artifact)) == manifest["artifact_sha256"][name], "Pinned artifact digest mismatch")
    return manifest, data


def read_origin(raw, allow_remote):
    url = urlsplit(raw)
    host = url.hostname or ""
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host == "localhost"
    require(url.scheme in ("https", "http") and bool(host) and not url.username and not url.password
            and url.path in ("", "/") and not url.query and not url.fragment, "Supply an HTTP service origin")
    require(loopback or (allow_remote and url.scheme == "https"), "Remote requires an isolated HTTPS origin and --allow-isolated-remote")
    require(not host.lower().startswith("neal-lab-factory"), "The existing shared production project is excluded")
    return f"{url.scheme}://{url.netloc}", loopback


def blank_credentials():
    return {"password": secrets.token_urlsafe(30), "session_key": secrets.token_urlsafe(36),
            "salt": secrets.token_hex(16), "tokens": {worker: secrets.token_urlsafe(32) for worker in WORKERS}}


def new_credentials(path):
    require(path is not None, "Use --credentials FILE")
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(blank_credentials(), stream)
    print("Created disposable credentials with mode 0600.")


def load_credentials(path, loopback):
    if path is None:
        require(loopback, "Remote trials require a freshly generated --credentials FILE")
        return {"password": "disposable-password", "session_key": "a-disposable-session-key-for-testing",
                "salt": "00"*16, "tokens": dict(zip(WORKERS, ("example-token-A", "example-token-B")))}
    require(stat.S_IMODE(path.stat().st_mode) == 0o600, "Trial credential file must have mode 0600")
    return json.loads(path.read_text())


def configuration(base, credentials, public):
    return {"LABFACTORY_PUBLIC_ORIGIN": base, "LABFACTORY_PUBLIC_REVIEW": "1" if public else "0",
            "LABFACTORY_SESSION_KEY": credentials["session_key"],
            "LABFACTORY_REVIEWERS": json.dumps({"Reviewer": password_hash(credentials["password"], bytes.fromhex(credentials["salt"]))}),
            "LABFACTORY_AGENTS": json.dumps({k: token_digest(v) for k, v in credentials["tokens"].items()})}


class Wire:
    def __init__(self, base, creds, loopback):
        headers = {"Origin": base, "Accept": "application/json, text/event-stream"}
        bypass = os.environ.get("LAB_TRIAL_PROTECTION_BYPASS")
        if bypass and not loopback:
            headers["x-vercel-protection-bypass"] = bypass
        self.client = httpx.Client(base_url=base, headers=headers, follow_redirects=False, timeout=45, trust_env=False)
        self.tokens = creds["tokens"]
        self.session = self.client.get("/api/session").raise_for_status().json()
        self.public = self.session.get("access_mode") == "public"
        self.reviewer = "Public reviewer" if self.public else "Reviewer"
        if not self.public:
            r = self.client.post("/api/login", json={"name": "Reviewer", "password": creds["password"]})
            require(r.status_code == 200 and r.json()["reviewer"] == "Reviewer", "Disposable reviewer login failed")
            if base.startswith("http://") and loopback:
                # The real API correctly sets Secure. This explicit cookie is only for
                # our own loopback HTTP server; all remote targets require HTTPS.
                self.client.headers["Cookie"] = f"{SESSION_COOKIE}={r.cookies[SESSION_COOKIE]}"
        self.transcript = []

    def exchange(self, path, payload=None, status=200):
        body = canonical(payload) if payload is not None else b""
        method = "POST" if payload is not None else "GET"
        self.transcript.append([method, path, sha(body)])
        response = self.client.request(method, path, content=body, headers={"Content-Type": "application/json"})
        require(response.status_code == status, f"{method} {path} expected {status}, got {response.status_code}")
        return response

    def rpc(self, worker, method, params, sequence=1, record=True):
        msg = {"jsonrpc": "2.0", "id": sequence, "method": method, "params": params}
        raw = canonical(msg)
        if record:
            self.transcript.append(["MCP", worker, sha(raw)])
        # The stateless MCP transport carries its own authenticated identity. Explicitly
        # exclude private reviewer cookies that httpx would otherwise attach on HTTPS.
        request = self.client.build_request("POST", "/mcp", content=raw, headers={
            "Content-Type": "application/json", "Authorization": "Bearer "+self.tokens[worker]})
        request.headers.pop("cookie", None)
        reply = self.client.send(request).raise_for_status().json()
        require(reply.get("id") == sequence and "result" in reply, f"{worker} {method} returned no result")
        return reply["result"]

    def tool(self, worker, name, arguments, record=True):
        result = self.rpc(worker, "tools/call", {"name": name, "arguments": arguments}, record=record)
        require(not result.get("isError"), f"MCP {name} returned a transport/tool error")
        return json.loads(result["content"][0]["text"])

    def ready(self):
        denied = self.client.post("/mcp", json={"jsonrpc":"2.0", "id":1, "method":"tools/list"})
        require(denied.status_code == 401, "MCP allowed a caller without an agent token")
        for worker in WORKERS:
            init = self.rpc(worker, "initialize", {"protocolVersion":"2025-03-26","capabilities":{},
                                                   "clientInfo":{"name":"lab-deployment-trial","version":"1"}})
            require("capabilities" in init, "MCP initialization failed")
            listing = self.rpc(worker, "tools/list", {})
            require({t["name"] for t in listing["tools"]} == TOOLS, "MCP tool catalog changed")


def submit(wire, worker, order, item):
    return wire.tool(worker, "submit_artifact", {"work_order_id":order, "worker":worker, "artifact":item})


def claim(wire, worker, order):
    return wire.tool(worker, "claim_work_order", {"work_order_id":order, "worker":worker})


def race(wire, order):
    gate = threading.Barrier(2)
    def run(worker):
        gate.wait(timeout=10)
        return wire.tool(worker, "claim_work_order", {"work_order_id":order, "worker":worker}, record=False)
    # Record this pair in fixed identity order. Arrival at the server is intentionally concurrent.
    for worker in WORKERS:
        args = {"work_order_id":order,"worker":worker}
        wire.transcript.append(["MCP race",worker,sha(canonical({"jsonrpc":"2.0","id":1,"method":"tools/call",
                                            "params":{"name":"claim_work_order","arguments":args}}))])
    with ThreadPoolExecutor(max_workers=2) as pool:
        answers = list(pool.map(run, WORKERS))
    require(sum("error" in a for a in answers) == 1 and sum(a.get("status") == "in_progress" for a in answers) == 1,
            "Simultaneous claims did not produce exactly one winner")


def exercise(wire, fixture):
    require(wire.exchange("/api/orders").json()["orders"] == [], "A new workload requires an empty isolated database")
    ids = {}
    a = fixture["artifacts"]
    for name in ("caffeine", "density"):
        example = fixture["examples"][name]
        order = wire.exchange("/api/analysis/orders", example, 201).json()["id"]
        ids[name] = order
        path = "/api/analysis/orders/"+order
        decision = "/api/orders/"+order+"/approve"
        args = {"work_order_id":order}
        require(claim(wire, WORKERS[0], order).get("status") == "in_progress", "Exclusive initial claim failed")
        author = wire.tool(WORKERS[0], "get_work_order_context", args)
        require(author["analysis"]["protocol"] == example["protocol"] and "control_expected" not in canonical(author).decode(),
                "Author context omitted the protocol or disclosed the control field")
        if name == "caffeine":
            rejected = submit(wire, WORKERS[0], order, a["wrong"])
            require(rejected["submission"] == 1 and rejected["passed"] is False, "Bad analysis passed")
            wire.exchange(decision, {"submission":1}, 409)
            wire.exchange(path+"/runs", {"submission":1}, 409)
            renewable = submit(wire, WORKERS[0], order, a[name])
            require("fresh" in renewable.get("error","").lower(), "A used blind control was reused")
            wire.exchange(path+"/control", fixture["fresh_control"], 201)
        number = 2 if name == "caffeine" else 1
        passed = submit(wire, WORKERS[0], order, a[name])
        require(passed["passed"] is True and passed["submission"] == number, "Fixed analysis failed verification")
        if number == 2:
            wire.exchange(decision, {"submission":1}, 409)
        wire.exchange(decision, {"submission":number})
        wire.exchange(path+"/runs", {"submission":number}, 201)
    ids["race"] = wire.exchange("/api/example", {}, 201).json()["id"]
    race(wire, ids["race"])
    return ids


def request_sequence(ids, fixture):
    """Reconstruct deterministic application requests without contacting the service.

    First compare this list with the live wire hash. Calling again with role aliases
    gives the same request bodies modulo server-assigned work-order IDs.
    """
    encoded = []
    def http(method, path, value=None):
        encoded.append([method, path, sha(canonical(value) if value is not None else b"")])
    def rpc(worker, method, args, label="MCP"):
        encoded.append([label, worker, sha(canonical({"jsonrpc":"2.0","id":1,"method":method,"params":args}))])
    def tool(worker, method, args, label="MCP"):
        rpc(worker,"tools/call",{"name":method,"arguments":args},label)
    for worker in WORKERS:
        rpc(worker,"initialize",{"protocolVersion":"2025-03-26","capabilities":{},
                                  "clientInfo":{"name":"lab-deployment-trial","version":"1"}})
        rpc(worker,"tools/list",{})
    http("GET","/api/orders")
    worker = WORKERS[0]
    for name in ("caffeine","density"):
        key = ids[name]
        args = {"work_order_id":key,"worker":worker}
        path = "/api/analysis/orders/"+key
        decision = "/api/orders/"+key+"/approve"
        http("POST","/api/analysis/orders",fixture["examples"][name])
        tool(worker,"claim_work_order",args)
        tool(worker,"get_work_order_context",{"work_order_id":key})
        if name=="caffeine":
            tool(worker,"submit_artifact",{**args,"artifact":fixture["artifacts"]["wrong"]})
            http("POST",decision,{"submission":1})
            http("POST",path+"/runs",{"submission":1})
            tool(worker,"submit_artifact",{**args,"artifact":fixture["artifacts"][name]})
            http("POST",path+"/control",fixture["fresh_control"])
        n = 2 if name=="caffeine" else 1
        tool(worker,"submit_artifact",{**args,"artifact":fixture["artifacts"][name]})
        if n==2:
            http("POST",decision,{"submission":1})
        http("POST",decision,{"submission":n})
        http("POST",path+"/runs",{"submission":n})
    http("POST","/api/example",{})
    for worker in WORKERS:
        tool(worker,"claim_work_order",{"work_order_id":ids["race"],"worker":worker},"MCP race")
    return encoded


def role_alias(record, field, actual, replacement):
    require(record[field] == actual, f"Broken {field} provenance")
    record[field] = replacement


def omit_time(record, field):
    require(isinstance(record[field],str) and bool(record[field]), f"Missing {field}")
    del record[field]


def evidence_view(data, name, order_id, reviewer):
    """Normalize only assigned identities, timestamps and the nondeterministic race winner."""
    view = deepcopy(data)
    order = view["order"]
    role_alias(order,"id",order_id,"@order/"+name)
    worker = order["worker"]
    if name=="race":
        require(worker in WORKERS, "Unexpected race owner")
        role_alias(order,"worker",worker,"@claim-winner")
    else:
        require(worker==WORKERS[0] and order["experiment_id"].startswith("tabular-"), "Wrong analysis owner or experiment")
        exp_id = order["experiment_id"]
        role_alias(order,"experiment_id",exp_id,"@experiment/"+name)
        for sub in view["submissions"]:
            role_alias(sub,"work_order_id",order_id,"@order/"+name)
            require(sub["worker"]==worker, "Submission has the wrong worker")
            omit_time(sub,"submitted_at")
        for receipt in view["runs"]:
            role_alias(receipt,"work_order_id",order_id,"@order/"+name)
            role_alias(receipt,"experiment_id",exp_id,"@experiment/"+name)
            require(receipt["experiment_revision"]==order["experiment_revision"], "Unpinned receipt revision")
            for field in ("actor","approved_by"):
                role_alias(receipt,field,reviewer,"@reviewer")
            require(type(receipt["id"]) is int and receipt["id"]>0, "Missing persisted run ID")
            receipt["id"] = "@original-run/"+name
            omit_time(receipt,"created_at")
    for event in view["history"]:
        omit_time(event,"at")
        if event["event"] in ("created","approved"):
            role_alias(event,"actor",reviewer,"@reviewer")
        elif event["event"] in ("claimed","submitted"):
            role_alias(event,"actor",worker,"@claim-winner" if name=="race" else worker)
        else:
            raise ValueError("Unexpected event in fixed workload: "+event["event"])
    return view


def observe(wire, ids, manifest, fixture):
    outcome = {}
    complete = {}
    for name in ("caffeine","density"):
        path = "/api/analysis/orders/"+ids[name]
        data = wire.exchange(path).json()
        complete[name] = evidence_view(data, name, ids[name], wire.reviewer)
        row = data["order"]
        number = 2 if name == "caffeine" else 1
        require(row["status"] == "released" and row["released_submission"] == number, "Wrong released revision")
        files = {}
        for remote, key, file in (("protocol","protocol","protocol.md"),("readings","csv","readings.csv")):
            content = wire.exchange(path+"/uploads/"+remote).content
            digest = sha(content)
            require(content == fixture["examples"][name][key].encode() and
                    digest == manifest["source_file_sha256"][f"examples/tabular/{name}/{file}"], "Upload bytes changed")
            files[key] = digest
        labels = ("wrong",name) if number == 2 else (name,)
        require(len(data["submissions"]) == number and len(data["runs"]) == 1, "Submission or run lost/duplicated")
        report = []
        for n, (sub, label) in enumerate(zip(data["submissions"], labels, strict=True), 1):
            digest = manifest["artifact_sha256"][label]
            require(sub["artifact"] == fixture["artifacts"][label] and sub["number"] == n and
                    sub["artifact_digest"] == digest and sub["control"]["artifact_digest"] == digest,
                    "Submitted artifact changed")
            require(sub["passed"] is (label!="wrong") and sub["control"]["passed"] is (label!="wrong"),
                    "Verification decision changed")
            if label == "wrong":
                require(any(c["name"].startswith("Agent test") for c in sub["results"]) and
                        all(c["passed"] for c in sub["results"] if c["name"].startswith("Agent test")),
                        "Bad candidate failed its own tests instead of the independent control")
            report.append({"number":n,"artifact_sha256":digest,"passed":sub["passed"],
                           "control":{k:sub["control"][k] for k in ("edition","expected","predicted","tolerance","passed")}})
        events = [(r["event"],r["submission"],r["note"]) for r in data["history"]]
        approvals = [r for r in data["history"] if r["event"] == "approved"]
        require(len(approvals) == 1 and approvals[0]["actor"] == wire.reviewer and approvals[0]["submission"] == number and
                approvals[0]["note"] == report[-1]["artifact_sha256"], "Approval association changed")
        receipt, = data["runs"]
        require(receipt["submission"] == number and receipt["approved_by"] == wire.reviewer and
                receipt["worker"] == WORKERS[0] and receipt["artifact_digest"] == report[-1]["artifact_sha256"] and
                receipt["protocol_digest"] == files["protocol"] and receipt["csv_digest"] == files["csv"] and
                receipt["status"] == "estimated" and receipt["control"]["passed"], "Receipt provenance changed")
        values = [r["value"] for r in receipt["results"]]
        expected = [24,45] if name == "caffeine" else [1.08,0.8]
        require(len(values)==2 and all(math.isclose(x,y,rel_tol=1e-12) for x,y in zip(values,expected)) and
                receipt["unit"] == fixture["examples"][name]["unit"], "Wrong analytical result")
        repeat = wire.exchange(path+"/runs", {"submission":number}, 201).json()
        require(repeat == receipt, "Replayed run did not return the saved receipt")
        saved = wire.exchange(f"{path}/runs/{receipt['id']}/readings").content
        require(sha(saved) == files["csv"], "Run's archived original bytes changed")
        outcome[name] = {"uploads":files,"submissions":report, "approval":{"submission":number,"digest":approvals[0]["note"]},
                         "history":events,"unit":receipt["unit"],"values":values,"control_passed":True,
                         "run_batch_digest":receipt["batch_digest"],"replayed_receipt":True}
    race_order = wire.exchange("/api/orders/"+ids["race"]).json()
    claims = [r for r in race_order["history"] if r["event"]=="claimed"]
    require(len(claims)==1 and claims[0]["actor"] in WORKERS and claims[0]["actor"] == race_order["order"]["worker"],
            "Persisted claim event does not match the single winner")
    outcome["race"] = {"winners":len(claims),"claim_events":len(claims),"status":race_order["order"]["status"]}
    complete["race"] = evidence_view(race_order, "race", ids["race"], wire.reviewer)
    return outcome, complete


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode",choices=("credentials","env","run","observe","offline","verify"))
    parser.add_argument("--base-url", default=os.environ.get("BASE_URL"))
    parser.add_argument("--state",type=Path)
    parser.add_argument("--credentials",type=Path)
    parser.add_argument("--private",action="store_true",help="Configure named reviewer access on loopback too")
    parser.add_argument("--allow-isolated-remote",action="store_true",help="Target a dedicated, disposable HTTPS deployment")
    args = parser.parse_args()
    if args.mode == "credentials":
        new_credentials(args.credentials)
        return
    require(bool(args.base_url), "Pass --base-url or BASE_URL")
    base, loopback = read_origin(args.base_url,args.allow_isolated_remote)
    creds = load_credentials(args.credentials,loopback)
    if args.mode=="env":
        print(json.dumps(configuration(base,creds,loopback and not args.private)))
        return
    require(args.state is not None, "Supply --state FILE in a temporary directory")
    manifest, fixture = workload()
    prior = {} if args.mode=="run" else json.loads(args.state.read_text())
    if args.mode=="run":
        require(not args.state.exists(), "Use a new state file per fresh deployment")
    else:
        require(base==prior["base_url"] and prior["workload_sha256"]==manifest["workload_sha256"], "State does not match target/workload")
    if args.mode=="offline":
        try:
            headers = {"x-vercel-protection-bypass":os.environ["LAB_TRIAL_PROTECTION_BYPASS"]} if not loopback and os.environ.get("LAB_TRIAL_PROTECTION_BYPASS") else {}
            response = httpx.get(base+"/api/session",headers=headers,timeout=4,trust_env=False)
            provider_code = response.headers.get("x-vercel-error","")
            deleted = (not loopback and args.allow_isolated_remote and response.status_code==404 and
                       provider_code in ("DEPLOYMENT_NOT_FOUND","DEPLOYMENT_DELETED"))
            require(response.status_code in (502,503,504) or deleted, f"Service was reachable (HTTP {response.status_code})")
            observation = f"gateway HTTP {response.status_code}" if not deleted else f"Vercel 404 {provider_code}"
        except httpx.ConnectError:
            observation = "connection unavailable"
        prior["downtime"] = {"confirmed":True,"observation":observation}
    else:
        wire = Wire(base,creds,loopback)
        try:
            wire.ready()
            if args.mode=="run":
                ids = exercise(wire,fixture)
                seq_hash = sha(canonical(wire.transcript))
                outcome, complete = observe(wire,ids,manifest,fixture)
                prior = {"base_url":base,"access_mode":"public" if wire.public else "private","ids":ids,
                         "workload_sha256":manifest["workload_sha256"], "request_sequence_sha256":seq_hash,
                         "outcome":outcome, "outcome_sha256":sha(canonical(outcome)),
                         "outcome_v2":complete,"outcome_v2_sha256":sha(canonical(complete))}
            else:
                outcome, complete = observe(wire,prior["ids"],manifest,fixture)
                fingerprint = sha(canonical(outcome))
                require(fingerprint==prior["outcome_sha256"] and canonical(prior["outcome"])==canonical(outcome),
                        "Recovered data changed canonical outcome")
                full_digest = sha(canonical(complete))
                if args.mode == "observe":
                    require(not prior.get("downtime"), "Capture full evidence before interrupting the service")
                    prior.pop("verification",None)
                    prior["outcome_v2"] = complete
                    prior["outcome_v2_sha256"] = full_digest
                else:
                    require(full_digest == prior.get("outcome_v2_sha256") and
                            canonical(complete)==canonical(prior.get("outcome_v2")), "Complete recovered evidence changed or missing baseline")
                    prior["verification"] = {"passed":True,"outcome_sha256":fingerprint,"outcome_v2_sha256":full_digest,
                                             "downtime_observed":bool(prior.get("downtime",{}).get("confirmed"))}
            actual_requests = request_sequence(prior["ids"],fixture)
            require(sha(canonical(actual_requests)) == prior["request_sequence_sha256"], "Raw request transcript mismatch")
            aliases = {role:"@order/"+role for role in prior["ids"]}
            prior["logical_request_sequence_sha256"] = sha(canonical(request_sequence(aliases,fixture)))
        finally:
            wire.client.close()
    pending = args.state.with_suffix(".tmp")
    pending.write_text(json.dumps(prior,indent=2,sort_keys=True)+"\n")
    pending.replace(args.state)
    print(json.dumps({"mode":args.mode,"workload_sha256":prior["workload_sha256"],
                      "request_sequence_sha256":prior["request_sequence_sha256"],"outcome_sha256":prior["outcome_sha256"],
                      "outcome_v2_sha256":prior.get("outcome_v2_sha256"),
                      "logical_request_sequence_sha256":prior.get("logical_request_sequence_sha256")}))


if __name__=="__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, httpx.HTTPError) as exc:
        sys.exit(f"Deployment trial failed: {exc}")
