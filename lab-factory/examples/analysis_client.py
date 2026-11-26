"""Use the same reviewer HTTP API for any mapped tabular analysis."""

import argparse
from getpass import getpass
import json
import os
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx


EXAMPLES = Path(__file__).with_name("tabular")


def upload(path):
    # Keep CRLF, BOM and trailing lines for the private original and its digest.
    return Path(path).read_bytes().decode("utf-8")


def read_json(path):
    return json.loads(upload(path))


def create_request(args):
    if args.example:
        entry = next((e for e in read_json(EXAMPLES / "index.json") if e["folder"] == args.example), None)
        if entry is None:
            raise ValueError("Unknown example. Choose a folder listed in examples/tabular/index.json.")
        folder = EXAMPLES / entry["folder"]
        config = {k: entry[k] for k in ("objective", "unit", "mapping", "range_gate")}
        protocol, csv, certificate = folder / "protocol.md", folder / "readings.csv", folder / "control.json"
    else:
        if not all((args.config, args.protocol, args.csv, args.control)):
            raise ValueError("Supply --config, --protocol, --csv and --control, or choose --example.")
        config = read_json(args.config)
        protocol, csv, certificate = args.protocol, args.csv, args.control
    control = read_json(certificate)
    if args.request_id:
        config["request_id"] = args.request_id
    return {**config, "protocol_name": protocol.name, "protocol": upload(protocol), "csv_name": csv.name,
            "csv": upload(csv), "control_expected": control["expected"], "control_tolerance": control["tolerance"]}


def command(args):
    if args.action == "create":
        return "POST", "/api/analysis/orders", create_request(args)
    if args.action == "list":
        return "GET", "/api/analysis", None
    order = quote(args.order, safe="")
    base = f"/api/analysis/orders/{order}"
    if args.action == "show":
        return "GET", base, None
    if args.action == "approve":
        return "POST", f"/api/orders/{order}/approve", {"submission": args.submission}
    if args.action == "control":
        return "POST", base + "/control", read_json(args.file)
    body = {"submission": args.submission}
    if bool(args.csv) != bool(args.control):
        raise ValueError("A new batch requires both --csv and --control.")
    if args.csv:
        certificate = read_json(args.control)
        body.update(csv_name=args.csv.name, csv=upload(args.csv), control_expected=certificate["expected"],
                    control_tolerance=certificate["tolerance"])
    return "POST", base + "/runs", body


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Reviewer service origin for this lab")
    parser.add_argument("--reviewer", default=os.environ.get("LAB_FACTORY_REVIEWER"))
    parser.add_argument("--password-file", type=Path, default=os.environ.get("LAB_FACTORY_REVIEWER_PASSWORD_FILE"))
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("list")
    create = commands.add_parser("create")
    group = create.add_mutually_exclusive_group(required=True)
    group.add_argument("--example", help="Use a teaching dataset, e.g. caffeine or density")
    group.add_argument("--config", type=Path, help="JSON with objective, mapping, unit and range_gate")
    create.add_argument("--request-id", help="Reuse this UUID for retries of the same upload")
    for flag in ("protocol", "csv", "control"):
        create.add_argument("--" + flag, type=Path)
    for name in ("show", "approve", "run", "control"):
        sub = commands.add_parser(name)
        sub.add_argument("order")
        if name in ("approve", "run"):
            sub.add_argument("--submission", required=True, type=int)
        if name == "run":
            sub.add_argument("--csv", type=Path)
            sub.add_argument("--control", type=Path)
        if name == "control":
            sub.add_argument("file", type=Path, help="New private control JSON: signal, factor, expected, tolerance")
    args = parser.parse_args()
    origin = args.url.rstrip("/")
    target = urlsplit(origin)
    if (not target.hostname or target.username or target.password or target.path or target.query or target.fragment
            or not (target.scheme == "https" or target.scheme == "http" and target.hostname in ("localhost", "127.0.0.1"))):
        parser.error("Use an HTTPS origin, or HTTP on loopback.")
    try:
        method, path, body = command(args)
        with httpx.Client(base_url=origin, headers={"Origin": origin}, timeout=60) as client:
            session = client.get("/api/session").raise_for_status().json()
            if not isinstance(session, dict) or "reviewer" not in session:
                raise ValueError("The lab returned an invalid reviewer session.")
            public = session.get("access_mode") == "public"
            if not public:
                name = args.reviewer or input("Reviewer name: ").strip()
                password = args.password_file.read_text().strip() if args.password_file else getpass("Reviewer password: ")
                client.post("/api/login", json={"name": name, "password": password}).raise_for_status()
            try:
                response = client.request(method, path, json=body) if body is not None else client.get(path)
                if response.is_error:
                    raise ValueError(f"HTTP {response.status_code}: {response.json().get('error', 'Request failed')}")
                print(json.dumps(response.json(), indent=2, ensure_ascii=False))
            finally:
                if not public:
                    client.post("/api/logout", json={})
    except (OSError, ValueError, KeyError, httpx.HTTPError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
