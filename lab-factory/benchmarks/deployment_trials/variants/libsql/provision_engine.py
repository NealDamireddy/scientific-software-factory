"""Extract the pinned Apple Silicon libSQL release to a disposable directory."""

import argparse
import hashlib
import os
import platform
import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path


TARGET = "libsql-server-aarch64-apple-darwin"
RELEASE = "https://github.com/tursodatabase/libsql/releases/download/libsql-server-v0.24.32"
ARCHIVE_SHA256 = "ced2a9d65a5d4b6bd72c67e98ad6c63139e2a139d91769f07fdd15be935381dd"
BINARY_SHA256 = "cc075b5bf145e5e750afd2941f390b46dbfe9ae47158d95ab637a00559681054"


def verify(path, expected):
    with path.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != expected:
        raise SystemExit(f"SHA256 mismatch for {path.name}: {actual}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path, help="directory for the verified sqld executable")
    parser.add_argument("--archive", type=Path, help="read a cached release archive instead of downloading")
    args = parser.parse_args()
    if (platform.system(), platform.machine()) != ("Darwin", "arm64"):
        parser.error("this reproducer pins the Apple Silicon release used for the trial")

    destination = args.destination.resolve()
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    binary = destination / "sqld"
    if binary.exists():
        verify(binary, BINARY_SHA256)
    else:
        with tempfile.TemporaryDirectory(dir=destination) as scratch:
            archive = args.archive
            if archive is None:
                archive = Path(scratch) / f"{TARGET}.tar.xz"
                with urllib.request.urlopen(f"{RELEASE}/{archive.name}", timeout=60) as src:
                    with archive.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
            verify(archive, ARCHIVE_SHA256)
            extracted = Path(scratch) / "sqld"
            with tarfile.open(archive, "r:xz") as bundle:
                with bundle.extractfile(f"{TARGET}/sqld") as src, extracted.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
            verify(extracted, BINARY_SHA256)
            extracted.chmod(0o700)
            os.link(extracted, binary)
    print(binary)


if __name__ == "__main__":
    main()
