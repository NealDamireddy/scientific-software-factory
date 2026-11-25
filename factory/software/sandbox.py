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


def command(source):
    python = Path(sys.executable).resolve()
    flags = ["-I", "-S", "-B", str(source)]
    if platform.system() == "Darwin" and shutil.which("sandbox-exec"):
        base = str(Path(sys.base_prefix).resolve())
        path = json.dumps(str(source))
        # macOS framework launchers may re-exec Python.app inside the same distribution.
        profile = f"""(version 1)
(deny default)
(allow process-exec (literal {json.dumps(str(python))}) (subpath {json.dumps(base + '/Resources/Python.app')}))
(allow file-read-metadata)
(allow file-read* (literal "/") (subpath "/System/Library") (subpath "/usr/lib") (subpath "/usr/share/locale")
    (subpath {json.dumps(base)}) (literal {path}) (literal "/dev/null") (literal "/dev/urandom"))
(allow sysctl-read)
(allow mach-lookup (global-name "com.apple.system.logger"))
(allow signal (target self))
"""
        return ["sandbox-exec", "-p", profile, str(python), *flags], "macOS Seatbelt"
    if platform.system() == "Linux" and shutil.which("bwrap"):
        args = ["bwrap","--unshare-all","--die-with-parent","--new-session","--cap-drop","ALL","--clearenv",
                "--ro-bind","/usr","/usr","--dev","/dev","--proc","/proc","--tmpfs","/tmp"]
        for folder in ("/lib","/lib64", "/etc/ld.so.cache"):
            if Path(folder).exists():
                args += ["--ro-bind",folder,folder]
        base = Path(sys.base_prefix).resolve()
        if not base.is_relative_to("/usr"):
            args += ["--ro-bind",str(base),str(base)]
        return args + ["--ro-bind",str(source),"/analysis.py","--chdir","/tmp",
                       str(python),"-I","-S","-B","/analysis.py"], "Linux bubblewrap"
    raise RuntimeError("Execution needs macOS sandbox-exec or Linux bubblewrap")


def limits():
    resource.setrlimit(resource.RLIMIT_CPU, (3, 3))
    resource.setrlimit(resource.RLIMIT_FSIZE, (65536, 65536))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
    if sys.platform.startswith("linux"):
        resource.setrlimit(resource.RLIMIT_AS, (256 << 20, 256 << 20))
        resource.setrlimit(resource.RLIMIT_NPROC, (32, 32))


def execute(source, data, metadata=None):
    args, name = command(source.resolve())
    if metadata is not None:
        args.append(json.dumps(metadata, allow_nan=False))
    with tempfile.TemporaryDirectory() as cwd, tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=out, stderr=err, cwd=cwd,
                                env={"LC_ALL":"C","PATH":"/usr/bin:/bin"}, start_new_session=True, preexec_fn=limits)
        try:
            proc.communicate(data, timeout=6)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate()
            raise RuntimeError("Scientific application exceeded six-second limit") from None
        if proc.returncode:
            err.seek(0)
            raise RuntimeError(f"{name} exit {proc.returncode}: " + err.read(1600).decode(errors="replace"))
        out.seek(0)
        output = json.load(out)
        if not isinstance(output, dict):
            raise ValueError("Application output must be one JSON object")
        return output, name
