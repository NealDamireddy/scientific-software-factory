import tempfile
import unittest
from pathlib import Path
from factory.context import ROOT, read_json, resolve
from factory.pipeline import run, verify_files, evaluate
from factory.upstream import from_export

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
