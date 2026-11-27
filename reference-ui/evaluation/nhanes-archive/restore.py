"""Restore the exact public CDC archive used in this evaluation to a new directory."""
import argparse
import csv
import hashlib
import json
import re
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from shutil import copyfileobj

def stable_notice_digest(data):
    # CDC's ASP.NET pages mint a new hidden VIEWSTATE value on each request.
    pattern = rb'(<input type="hidden" name="__VIEWSTATE" id="__VIEWSTATE" value=")[^"]*(")'
    cleaned, count = re.subn(pattern, rb"\g<1>\g<2>", data)
    if count != 1:
        return None
    return hashlib.sha256(cleaned).hexdigest()

def matches(path, row, notices):
    data = path.read_bytes()
    if len(data) == int(row["bytes"]) and hashlib.sha256(data).hexdigest() == row["sha256"]:
        return True
    return row["file"] in notices and stable_notice_digest(data) == notices[row["file"]]

def restore(manifest, destination):
    notices = json.loads(manifest.with_name("notice-digests.json").read_text())
    destination.mkdir(parents=True, exist_ok=True)
    with manifest.open(newline="") as stream:
        for row in csv.DictReader(stream):
            url = urlparse(row["url"])
            relative = Path(row["file"])
            if url.scheme != "https" or url.hostname != "wwwn.cdc.gov" or relative.is_absolute() or ".." in relative.parts:
                raise ValueError(f"Unexpected source in manifest: {relative}")
            target = destination / relative
            if target.exists():
                if matches(target, row, notices):
                    continue
                raise ValueError(f"Existing file differs from frozen archive: {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(dir=target.parent, delete=False) as temp:
                temp_path = Path(temp.name)
            try:
                with urlopen(Request(url.geturl(), headers={"User-Agent":"NHANES archive reproducibility audit"}), timeout=45) as response, temp_path.open("wb") as out:
                    copyfileobj(response, out)
                if not matches(temp_path, row, notices):
                    raise ValueError(f"CDC source has changed since collection: {relative}")
                temp_path.replace(target)
            finally:
                temp_path.unlink(missing_ok=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    restore(Path(__file__).with_name("sources.csv"), args.destination)
    print("Archive matches the source manifest.")
