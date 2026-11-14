import json
import tempfile
import unittest
from pathlib import Path

from factory.sandbox import execute

class SandboxTests(unittest.TestCase):
    def test_allowed_science_and_denied_access(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            secret = folder / "private.txt"
            secret.write_text("test sentinel")
            app = folder / "analysis.py"
            app.write_text("import statistics, json\nprint(json.dumps({'mean':statistics.mean([1,3])}))")
            self.assertEqual(execute(app,b"")[0], {"mean":2})
            for action in (f"open({str(secret)!r}).read()",f"open({str(secret)!r},'w')",
                           "import socket; socket.create_connection(('1.1.1.1', 80), timeout=1)"):
                app.write_text(action + "\nprint('{}')")
                with self.assertRaises(RuntimeError): execute(app,b"")
            self.assertEqual(secret.read_text(), "test sentinel")
