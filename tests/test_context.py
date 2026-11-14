import copy
import unittest
from factory.context import ROOT, preflight, read_json, resolve

class ContextTests(unittest.TestCase):
    def setUp(self):
        self.order = read_json(ROOT / "orders/curie.json")
        self.context = resolve(self.order)
        self.meta = read_json(ROOT / "fixtures/temperature/metadata.json")
        self.data = (ROOT / "fixtures/temperature/input.csv").read_bytes()

    def checks(self):
        return {c["name"]:c["status"] for c in preflight(self.order,self.context,self.meta,self.data)}

    def test_shared_lab_isolated_projects(self):
        cw = resolve(read_json(ROOT / "orders/linewidth.json"))
        self.assertEqual(cw["lab"],self.context["lab"])
        self.assertEqual(cw["instrument"],self.context["instrument"])
        self.assertNotEqual(cw["project"]["dataset"],self.context["project"]["dataset"])
        self.order["input"]["dataset"] = "gaussian"
        with self.assertRaises(ValueError): resolve(self.order)

    def test_three_capability_states(self):
        self.order["operations"] += ["pulse-acquisition", "undocumented"]
        states = self.checks()
        self.assertEqual([states[k] for k in ["read-export","pulse-acquisition","undocumented"]],["pass","fail","unknown"])

    def test_invalid_units_and_missing_metadata(self):
        self.order["input"]["units"]["temperature"] = "°C"
        del self.meta["frequency_GHz"]
        self.assertEqual(self.checks()["units"],"fail")
        self.assertEqual(self.checks()["metadata"],"fail")

    def test_reject_invalid_grid(self):
        self.data = b"temperature_K,intensity_au\n0,2\n1,4\n2,nan\n"
        self.assertEqual(self.checks()["schema"], "fail")

    def test_reject_foreign_project_and_traversal(self):
        for value in ("../curie", "unknown"):
            order = copy.deepcopy(self.order)
            order["project"] = value
            with self.assertRaises(ValueError): resolve(order)
