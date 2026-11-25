import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from factory.context import ROOT, dump, read_json, resolve
from factory.assays.epr import __main__ as cli
from factory.assays.epr.pipeline import factory_revision, run, verify_files, evaluate
from factory.assays.epr.upstream import from_export

class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Path(self.temp.name)

    def test_success_and_tamper(self):
        for name, n in (("curie",3),("linewidth",4)):
            path = run(read_json(ROOT/"orders"/(name+".json")),self.store)
            report = verify_files(path)
            self.assertEqual(report["status"],"verified")
            self.assertEqual(len(report["tests"]),n)
            self.assertTrue(all(case["pass"] for case in report["tests"]))
            (path/"analysis.py").write_text("changed")
            with self.assertRaises(ValueError): verify_files(path)

    def test_invalid_order_blocks_generation(self):
        path = run(read_json(ROOT/"orders/invalid-units.json"),self.store,"generate")
        report = verify_files(path)
        self.assertEqual(report["status"],"blocked")
        self.assertFalse((path/"analysis.py").exists())
        self.assertFalse(report["tests"])

    def test_unknown_and_unsupported_block(self):
        for op, state in (("vendor-binary","unknown"),("pulse-acquisition","fail")):
            order = read_json(ROOT/"orders/curie.json")
            order["operations"].append(op)
            report = verify_files(run(order,self.store,"generate"))
            self.assertEqual(report["status"],"blocked")
            self.assertIn((op,state),[(c["name"],c["status"]) for c in report["checks"]])

    def test_unmapped_acceptance_and_bad_reference(self):
        order = read_json(ROOT/"orders/curie.json")
        order["acceptance"].append("validate saturation on hardware")
        report = verify_files(run(order,self.store))
        self.assertEqual(report["status"],"review")
        metrics = evaluate({"center_mT":339,"linewidth_mT":10},{"center_mT":339,"linewidth_mT":0.8},"linewidth",[])
        self.assertFalse(all(c["pass"] for c in metrics))

    def test_scope_of_previous_revision(self):
        base = run(read_json(ROOT/"orders/curie.json"),self.store)
        order = read_json(ROOT/"orders/linewidth.json")
        report = verify_files(run(order,self.store,previous=base))
        self.assertEqual(report["status"],"failed")
        self.assertFalse((base/"analysis.py").is_symlink())

    def test_8090_export(self):
        path=self.store/"orders.csv"
        path.write_text('ID,Name\nWO-2,Generate offline scientific applications\n')
        order=from_export(path,"WO-2",ROOT/"orders/curie.json")
        self.assertEqual(order["upstream_id"],"WO-2")
        self.assertEqual(resolve(order)["project"]["id"],"curie")


class EvidenceStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Path(self.temp.name)

    def verify_cli(self, *args):
        out = io.StringIO()
        with patch.object(sys, "argv", ["factory", "verify", *map(str, args)]), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            return cli.main(), out.getvalue()

    def test_recorded_status_must_agree_with_checks(self):
        blocked = run(read_json(ROOT/"orders/invalid-units.json"), self.store, "generate")
        failed = run(read_json(ROOT/"orders/linewidth.json"), self.store,
                     previous=run(read_json(ROOT/"orders/curie.json"), self.store))
        verified = run(read_json(ROOT/"orders/curie.json"), self.store)
        for folder, edit in ((blocked, lambda r: r.update(status="verified")),
                             (failed, lambda r: r.update(status="verified")),
                             (verified, lambda r: [c.update(status="fail") for c in r["checks"] if c["name"] == "reference"]),
                             (verified, lambda r: r["tests"][0].update({"pass": False})),
                             (verified, lambda r: r.update(tests=[]))):
            report = read_json(folder/"report.json")
            original = json.loads(json.dumps(report))
            edit(report)
            dump(folder/"report.json", report)
            with self.subTest(folder=folder.name), self.assertRaisesRegex(ValueError, "differs from its checks"):
                verify_files(folder)
            dump(folder/"report.json", original)
            verify_files(folder)

    def test_verify_command_reports_run_status_and_exit_code(self):
        blocked = run(read_json(ROOT/"orders/invalid-units.json"), self.store, "generate")
        verified = run(read_json(ROOT/"orders/curie.json"), self.store)
        code, out = self.verify_cli(blocked)
        self.assertEqual(code, 2)
        self.assertTrue(out.startswith("BLOCKED"), out)
        self.assertNotIn("Verified", out)
        self.assertEqual(self.verify_cli("--any-status", blocked)[0], 0)
        code, out = self.verify_cli(verified)
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("VERIFIED"), out)
        report = read_json(blocked/"report.json")
        dump(blocked/"report.json", {**report, "status": "verified"})
        self.assertEqual(self.verify_cli("--any-status", blocked)[0], 1)

    def test_replay_fails_when_baseline_differs_from_registered_revision(self):
        order = read_json(ROOT/"orders/curie.json")
        for pin in ("0"*64, None):
            ctx = resolve(order)
            ctx["project"]["replay_source_revision"] = pin
            with self.subTest(pin=pin), patch("factory.assays.epr.pipeline.resolve", return_value=ctx):
                report = verify_files(run(order, self.store))
            self.assertEqual(report["status"], "failed")
            runtime = [c for c in report["checks"] if c["name"] == "runtime"]
            self.assertIn("replay_source_revision", runtime[0]["detail"])
            self.assertFalse(report["tests"])

    def test_unexpected_generation_error_still_records_a_failed_run(self):
        with patch("factory.assays.epr.pipeline.generate", side_effect=AttributeError("'int' object has no attribute 'strip'")):
            report = verify_files(run(read_json(ROOT/"orders/curie.json"), self.store, "generate"))
        self.assertEqual(report["status"], "failed")
        self.assertIn("AttributeError", [c for c in report["checks"] if c["name"] == "runtime"][0]["detail"])

    def test_factory_revision_covers_subpackages_and_paths(self):
        root = self.store / "factory"
        (root / "software").mkdir(parents=True)
        (root / "software" / "sandbox.py").write_text("x = 1\n")
        before = factory_revision(root)
        (root / "software" / "sandbox.py").write_text("x = 2\n")
        changed = factory_revision(root)
        self.assertNotEqual(before, changed)
        (root / "software" / "sandbox.py").rename(root / "sandbox.py")
        self.assertNotEqual(changed, factory_revision(root))
