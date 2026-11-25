"""Resource limits and output parsing at the generated-program boundary."""
import platform
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from factory.software import sandbox
from factory.software.sandbox import execute, sbpl_string

LINUX_BWRAP = platform.system() == "Linux" and shutil.which("bwrap")
MACOS = platform.system() == "Darwin" and shutil.which("sandbox-exec")


class SandboxLimitTests(unittest.TestCase):
    def program(self, text):
        folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
        app = folder / "analysis.py"
        app.write_text(text)
        return app

    def test_non_finite_output_is_rejected_at_the_boundary(self):
        for literal in ("NaN", "Infinity", "-Infinity"):
            app = self.program(f"print('{{\"estimate\": {literal}}}')")
            with self.assertRaisesRegex(ValueError, "non-finite"):
                execute(app, b"")
        self.assertEqual(execute(self.program("print('{\"estimate\": 1.5}')"), b"")[0], {"estimate": 1.5})

    @unittest.skipUnless(LINUX_BWRAP, "needs Linux bubblewrap")
    def test_bubblewrap_scratch_is_size_capped_and_the_rest_is_read_only(self):
        app = self.program("""import json, os
written = 0
try:
    for n in range(10000):
        with open(f"/tmp/f{n}", "wb") as f:
            f.write(b"x" * 60000)
        written += 60000
except OSError:
    pass
denied = []
for path in ("/escape", "/dev/escape"):
    try:
        open(path, "w").close()
    except OSError:
        denied.append(path)
print(json.dumps({"written": written, "denied": denied}))
""")
        output = execute(app, b"")[0]
        self.assertLessEqual(output["written"], sandbox.TMP_LIMIT)
        self.assertGreater(output["written"], 0)  # Scratch space still works.
        self.assertEqual(output["denied"], ["/escape", "/dev/escape"])

    @unittest.skipUnless(MACOS, "needs macOS Seatbelt")
    def test_macos_watchdog_stops_runaway_memory(self):
        app = self.program("import time\nblock = b'x' * (600 << 20)\ntime.sleep(5)\nprint('{}')")
        with self.assertRaisesRegex(RuntimeError, "memory limit"):
            execute(app, b"")

    def test_memory_watchdog_kills_process_group_and_keeps_normal_io(self):
        # Exercise the watchdog loop on any host by running the program unsandboxed
        # with no rlimits, so only the watchdog can stop it.
        plain = lambda source: ([sys.executable, "-I", "-S", "-B", str(source)], "test")
        with mock.patch.object(sandbox, "command", plain), \
                mock.patch.object(sandbox, "limits", lambda: None), \
                mock.patch.object(sandbox, "watch_memory", lambda: True), \
                mock.patch.object(sandbox, "MEMORY_LIMIT", 64 << 20):
            hog = self.program("import time\nblock = b'x' * (200 << 20)\ntime.sleep(5)\nprint('{}')")
            with self.assertRaisesRegex(RuntimeError, "64 MiB memory limit"):
                execute(hog, b"")
            # Input larger than a pipe buffer, read only after several watchdog polls,
            # still arrives whole when communicate() is retried.
            echo = self.program("import json, sys, time\ntime.sleep(.3)\n"
                                "print(json.dumps({'n': len(sys.stdin.buffer.read())}))")
            self.assertEqual(execute(echo, b"y" * (1 << 20))[0], {"n": 1 << 20})


class SeatbeltQuotingTests(unittest.TestCase):
    def test_paths_keep_utf8_and_escape_only_quotes_and_backslashes(self):
        self.assertEqual(sbpl_string("/Users/zoë/Documents"), '"/Users/zoë/Documents"')
        self.assertEqual(sbpl_string('/a"b\\c'), '"/a\\"b\\\\c"')
        for bad in ("/a\nb", "/a\x00b", "/a\x7fb"):
            with self.assertRaises(RuntimeError):
                sbpl_string(bad)

    def test_profile_names_accented_source_literally(self):
        with mock.patch.object(sandbox.platform, "system", lambda: "Darwin"), \
                mock.patch.object(sandbox.shutil, "which", lambda name: "/usr/bin/" + name):
            args, name = sandbox.command(Path("/Users/zoë/Café/analysis.py"))
        self.assertEqual(name, "macOS Seatbelt")
        self.assertIn('(literal "/Users/zoë/Café/analysis.py")', args[2])
        self.assertNotIn("\\u", args[2])


if __name__ == "__main__":
    unittest.main()
