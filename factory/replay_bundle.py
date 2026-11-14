"""Re-execute both recorded B12 acquisitions from a downloaded EVOLVE package."""
import argparse
import json
from pathlib import Path
import tempfile

from . import b12_build
from .context import read_json
from .followup import replay_acquisition


def replay_package(bundle):
    if bundle.get("profile") != "research-reproducibility@1":
        raise ValueError("Unsupported evidence profile")
    direct, child = bundle["direct"], bundle["followup"]
    if child["parent_id"] != direct["id"] or child["parent_revision"] != direct["revision"]:
        raise ValueError("Broken source lineage")
    calibration = bundle["initial"]["calibration"]
    results = []
    with tempfile.TemporaryDirectory() as temporary:
        for task, measurement in [(direct, bundle["initial"]), (child, child["measurement"])]:
            identifier = task["id"]
            if not isinstance(identifier, str) or len(identifier) != 32 or any(c not in "0123456789abcdef" for c in identifier):
                raise ValueError("Invalid task ID in package")
            folder = Path(temporary) / identifier
            folder.mkdir()
            files = bundle["sources"][identifier]["files"]
            if set(files) != set(b12_build.FILES):
                raise ValueError("Unexpected package artifacts")
            for name in b12_build.FILES:
                (folder/name).write_text(files[name])
            (folder/"task.json").write_text(json.dumps(task, allow_nan=False))
            actual = replay_acquisition(folder, measurement, calibration)
            if actual != task["result"]:
                raise ValueError("Rerun differs from the saved result")
            results.append({"task": identifier, "revision": task["revision"], "result": actual})
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    args = parser.parse_args()
    print(json.dumps(replay_package(read_json(args.package)), indent=2))
