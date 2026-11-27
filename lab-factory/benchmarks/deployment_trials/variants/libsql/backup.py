"""Copy and verify a stopped sqld data directory inside the caller's private scratch."""

import hashlib
from pathlib import Path
import shutil
from time import perf_counter


def _manifest(root):
    directories = []
    files = {}
    for entry in sorted(root.rglob("*")):
        name = entry.relative_to(root).as_posix()
        if entry.is_symlink():
            raise ValueError("A cold SQL image must not include symbolic links")
        if entry.is_dir():
            directories.append(name)
        elif entry.is_file():
            with entry.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            files[name] = {"bytes": entry.stat().st_size, "sha256": digest}
        else:
            raise ValueError("Unexpected non-regular entry in SQL image")
    return {"directories": directories, "files": files}


def cold_backup(source_dir, target_backup_dir, empty_restore_dir):
    """After clean sqld shutdown, copy source to backup, then backup to restore."""
    total_start = perf_counter()
    paths = [Path(p) for p in (source_dir, target_backup_dir, empty_restore_dir)]
    if any(p.is_symlink() for p in paths):
        raise ValueError("Pass data directories directly")
    source, backup, restored = [p.resolve() for p in paths]
    resolved = (source, backup, restored)
    if any(a.is_relative_to(b) for i, a in enumerate(resolved)
           for j, b in enumerate(resolved) if i != j):
        raise ValueError("Source, backup, and restore directories must be disjoint")
    for target in (backup, restored):
        if target.exists() and (not target.is_dir() or any(target.iterdir())):
            raise ValueError("Backup and restore targets must be new or empty")
    if not source.is_dir():
        raise ValueError("Source SQL image directory does not exist")

    timings = {}
    def milliseconds(start):
        return round((perf_counter() - start) * 1000, 3)

    start = perf_counter()
    source_manifest = _manifest(source)
    if not source_manifest["files"]:
        raise ValueError("Empty SQL image")
    timings["source_manifest_ms"] = milliseconds(start)
    for label, original, copied in (("backup", source, backup), ("restore", backup, restored)):
        start = perf_counter()
        shutil.copytree(original, copied, dirs_exist_ok=True, symlinks=True)
        timings[f"{label}_copy_ms"] = milliseconds(start)
        start = perf_counter()
        if _manifest(copied) != source_manifest:
            raise RuntimeError(f"SQL {label} file or directory manifest differs from the source")
        timings[f"{label}_verification_ms"] = milliseconds(start)
    timings["copy_and_verification_total_ms"] = milliseconds(total_start)
    return {"status": "pass", "method": "quiesced complete sqld directory copy",
            "scope": "same host and filesystem; caller stopped sqld before copying",
            "limitations": ["Requires SQL downtime for a stable source image.",
                            "Off-host disaster recovery and online backup were untested."],
            "image_manifest": source_manifest, "file_count": len(source_manifest["files"]),
            "image_bytes": sum(entry["bytes"] for entry in source_manifest["files"].values()),
            "backup_manifest_matches_source": True, "restore_manifest_matches_source": True,
            "timings_ms": timings}
