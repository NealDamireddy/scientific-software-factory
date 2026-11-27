"""Mutation checks for the deployment comparison's full evidence and digest rules."""

from copy import deepcopy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("deployment_acceptance", Path(__file__).resolve().parents[1] / "acceptance.py")
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)


def reading():
    # The transport workload supplies the real fixtures. This small synthetic
    # detail record isolates projection changes from network or storage effects.
    return {
        "order": {"id":"WO-8","worker":"agent-a","experiment_id":"tabular-small","experiment_revision":2},
        "submissions":[{"work_order_id":"WO-8","worker":"agent-a","number":2,"passed":True,"submitted_at":"today",
                        "results":[{"name":"Blind control","passed":True,"detail":"Within tolerance"}],
                        "artifact_digest":"digest","control":{"expected":0.9,"predicted":0.9,"passed":True}}],
        "history":[{"event":"approved","actor":"Reviewer","at":"today","submission":2,"note":"digest"}],
        "runs":[{"work_order_id":"WO-8","experiment_id":"tabular-small","experiment_revision":2,"id":4,"created_at":"today",
                 "actor":"Reviewer","approved_by":"Reviewer","worker":"agent-a","standards":[[1,2]],
                 "control":{"expected":0.9,"predicted":0.9,"passed":True},
                 "results":[{"id":"Sample A","signal":9,"factor":10,"unit":"g/mL","value":0.9}]}],
    }


def digest(data):
    view = acceptance.evidence_view(data,"density",data["order"]["id"],"Reviewer")
    return acceptance.sha(acceptance.canonical(view))


class EvidenceTest(unittest.TestCase):
    def test_stable_scientific_and_audit_fields_have_effect(self):
        changes = [
            (("runs",0,"results",0,"id"),"Other sample"), (("runs",0,"results",0,"unit"),"mg/L"),
            (("runs",0,"results",0,"signal"),90), (("runs",0,"results",0,"value"),9.0),
            (("runs",0,"standards"),[]), (("runs",0,"control","expected"),2.5),
            (("runs",0,"control","predicted"),2.5), (("submissions",0,"results"),[]),
            (("submissions",0,"results",0,"detail"),"Different"), (("submissions",0,"passed"),False),
            (("submissions",0,"artifact_digest"),"other"), (("history",0,"note"),"other"),
        ]
        baseline = digest(reading())
        for path, value in changes:
            with self.subTest(path=path):
                data = reading()
                node = data
                for key in path[:-1]:
                    node = node[key]
                node[path[-1]] = value
                self.assertNotEqual(digest(data),baseline)

    def test_inconsistent_identity_bindings_fail(self):
        for section, field, wrong in (("submissions","worker","agent-b"),("submissions","work_order_id","WO-5"),
                                     ("runs","actor","other"),("runs","approved_by","agent-a"),
                                     ("runs","experiment_revision",7),("runs","experiment_id","tabular-other")):
            with self.subTest(section=section,field=field):
                data=reading()
                data[section][0][field]=wrong
                with self.assertRaises(ValueError):
                    digest(data)

    def test_consistent_technical_ids_and_timestamps_can_differ(self):
        data=reading()
        changed=deepcopy(data)
        changed["order"]["id"]=changed["submissions"][0]["work_order_id"]=changed["runs"][0]["work_order_id"]="WO-9"
        changed["order"]["experiment_id"]=changed["runs"][0]["experiment_id"]="tabular-new-assigned-id"
        changed["history"][0]["at"]=changed["submissions"][0]["submitted_at"]=changed["runs"][0]["created_at"]="tomorrow"
        changed["runs"][0]["id"]=98
        self.assertEqual(digest(data),digest(changed))

    def test_request_aliases_cover_posted_payloads(self):
        manifest,fixture=acceptance.workload()
        self.assertEqual(manifest["source_commit"],"62badef1d608d94903da475bfd2b689cb80f9c49")
        aliases={k:"@order/"+k for k in ("caffeine","density","race")}
        before=acceptance.request_sequence(aliases,fixture)
        expected="2fff2a02b9d5998848e53e14a6ebf155588b6dede6043bc7f14d8ebf516af942"
        self.assertEqual(len(before),26)
        self.assertEqual(acceptance.sha(acceptance.canonical(before)),expected)
        fixture["examples"]["density"]["csv"]+="\n"
        self.assertNotEqual(acceptance.sha(acceptance.canonical(acceptance.request_sequence(aliases,fixture))),expected)


if __name__=="__main__":
    unittest.main()
