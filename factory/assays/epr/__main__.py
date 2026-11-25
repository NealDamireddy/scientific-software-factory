import argparse
import json
from pathlib import Path
import sys
from factory.context import ROOT, read_json
from factory.assays.epr.pipeline import run, verify_files
from factory.assays.epr.upstream import from_export


def main():
    parser = argparse.ArgumentParser(description="Scientific Software Factory")
    commands = parser.add_subparsers(dest="command",required=True)
    build = commands.add_parser("run")
    build.add_argument("order",type=Path)
    build.add_argument("--mode",choices=["generate","replay"],default="replay")
    build.add_argument("--previous",type=Path,help="Verified same-project run to evolve or replay")
    build.add_argument("--store",type=Path,default=ROOT/"runs")
    verify = commands.add_parser("verify")
    verify.add_argument("folder",type=Path)
    verify.add_argument("--any-status",action="store_true",
                        help="Audit intact evidence of any status; exit 0 unless the evidence is inconsistent")
    adapter = commands.add_parser("import-8090")
    adapter.add_argument("csv",type=Path)
    adapter.add_argument("id")
    adapter.add_argument("template",type=Path)
    args = parser.parse_args()
    try:
        if args.command=="import-8090":
            print(json.dumps(from_export(args.csv,args.id,args.template),indent=2))
            return 0
        if args.command=="verify":
            result=verify_files(args.folder)
            status=result["status"]
            print(f"{status.upper()} {args.folder}: evidence intact, {len(result['artifacts'])} artifact digests "
                  f"match and the recorded status agrees with its checks.")
            return 0 if status=="verified" or args.any_status else 2
        path=run(read_json(args.order),args.store,args.mode,args.previous)
        report=read_json(path/"report.json")
        print(report["status"].upper(),path/"report.json")
        for c in report["checks"]:
            print(f"  {c['status']:<9} {c['name']:<22} {c['detail']}")
        return 0 if report["status"]=="verified" else 2
    except (ValueError,OSError,KeyError) as exc:
        print(str(exc),file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
