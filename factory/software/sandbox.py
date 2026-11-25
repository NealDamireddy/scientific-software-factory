"""Restrict reads to the interpreter, OS libraries and one source file. No writes or network."""
import json
import os
from pathlib import Path
import platform
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
import time

# Memory available to one generated program. Linux enforces it with RLIMIT_AS;
# macOS ignores RLIMIT_AS, so a watchdog polls resident memory instead.
MEMORY_LIMIT = 256 << 20
# Writable scratch inside bubblewrap. Each file is also capped by RLIMIT_FSIZE.
TMP_LIMIT = 1 << 20
WALL_LIMIT_S = 6
WATCHDOG_INTERVAL_S = .05


def sbpl_string(text):
    """Quote a path for a Seatbelt profile, keeping UTF-8 as is (json.dumps would emit \\uXXXX)."""
    if any(ord(c) < 0x20 or c == "\x7f" for c in text):
        raise RuntimeError("Sandbox path contains a control character")
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def command(source):
    python = Path(sys.executable).resolve()
    flags = ["-I", "-S", "-B", str(source)]
    if platform.system() == "Darwin" and shutil.which("sandbox-exec"):
        base = str(Path(sys.base_prefix).resolve())
        path = sbpl_string(str(source))
        # macOS framework launchers may re-exec Python.app inside the same distribution.
        profile = f"""(version 1)
(deny default)
(allow process-exec (literal {sbpl_string(str(python))}) (subpath {sbpl_string(base + '/Resources/Python.app')}))
(allow file-read-metadata)
(allow file-read* (literal "/") (subpath "/System/Library") (subpath "/usr/lib") (subpath "/usr/share/locale")
    (subpath {sbpl_string(base)}) (literal {path}) (literal "/dev/null") (literal "/dev/urandom"))
(allow sysctl-read)
(allow mach-lookup (global-name "com.apple.system.logger"))
(allow signal (target self))
"""
        return ["sandbox-exec", "-p", profile, str(python), *flags], "macOS Seatbelt"
    if platform.system() == "Linux" and shutil.which("bwrap"):
        args = ["bwrap","--unshare-all","--die-with-parent","--new-session","--cap-drop","ALL","--clearenv",
                "--ro-bind","/usr","/usr","--dev","/dev","--proc","/proc",
                "--size",str(TMP_LIMIT),"--tmpfs","/tmp"]
        for folder in ("/lib","/lib64", "/etc/ld.so.cache"):
            if Path(folder).exists():
                args += ["--ro-bind",folder,folder]
        base = Path(sys.base_prefix).resolve()
        if not base.is_relative_to("/usr"):
            args += ["--ro-bind",str(base),str(base)]
        # bwrap's root and /dev are uncapped tmpfs mounts (host RAM); make them read-only
        # so the size-capped /tmp is the only writable place.
        return args + ["--ro-bind",str(source),"/analysis.py","--remount-ro","/dev","--remount-ro","/",
                       "--chdir","/tmp",
                       str(python),"-I","-S","-B","/analysis.py"], "Linux bubblewrap"
    raise RuntimeError("Execution needs macOS sandbox-exec or Linux bubblewrap")


def limits():
    resource.setrlimit(resource.RLIMIT_CPU, (3, 3))
    resource.setrlimit(resource.RLIMIT_FSIZE, (65536, 65536))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
    if sys.platform.startswith("linux"):
        resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT, MEMORY_LIMIT))
        resource.setrlimit(resource.RLIMIT_NPROC, (32, 32))


def watch_memory():
    return platform.system() == "Darwin"


def resident_bytes(pid):
    """Resident set size of one process, or None once it has exited."""
    try:
        out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True,
                             timeout=1, env={"LC_ALL": "C", "PATH": "/usr/bin:/bin"}).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return int(out) * 1024 if out.isdigit() else None


def _kill(proc):
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    proc.communicate()


def reject_constant(value):
    raise ValueError(f"Application output contains non-finite number {value}")


def execute(source, data, metadata=None):
    args, name = command(source.resolve())
    if metadata is not None:
        args.append(json.dumps(metadata, allow_nan=False))
    watchdog = watch_memory()
    with tempfile.TemporaryDirectory() as cwd, tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=out, stderr=err, cwd=cwd,
                                env={"LC_ALL":"C","PATH":"/usr/bin:/bin"}, start_new_session=True, preexec_fn=limits)
        deadline = time.monotonic() + WALL_LIMIT_S
        payload = data
        while True:
            # communicate() may be retried after a timeout without losing input or output.
            step = deadline - time.monotonic()
            if watchdog:
                step = min(step, WATCHDOG_INTERVAL_S)
            try:
                proc.communicate(payload, timeout=max(step, 0))
                break
            except subprocess.TimeoutExpired:
                payload = None
            if time.monotonic() >= deadline:
                _kill(proc)
                raise RuntimeError("Scientific application exceeded six-second limit") from None
            rss = resident_bytes(proc.pid) if watchdog else None
            if rss is not None and rss > MEMORY_LIMIT:
                _kill(proc)
                raise RuntimeError(f"Scientific application exceeded {MEMORY_LIMIT >> 20} MiB memory limit")
        if proc.returncode:
            err.seek(0)
            raise RuntimeError(f"{name} exit {proc.returncode}: " + err.read(1600).decode(errors="replace"))
        out.seek(0)
        # NaN and Infinity are not JSON; refuse them here so no consumer has to remember to.
        output = json.load(out, parse_constant=reject_constant)
        if not isinstance(output, dict):
            raise ValueError("Application output must be one JSON object")
        return output, name
