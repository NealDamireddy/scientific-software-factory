"""Independent fixture inputs shared by local and hosted catalog adapter tests."""
from factory.knowledge.catalog_contract import APPROVE, PROPOSE, READ, RECORD_EVIDENCE

LAB = "spectroscopy"
ACTIONS = (READ, PROPOSE, RECORD_EVIDENCE, APPROVE)


class Caller:
    def __init__(self, actor_id="curator", *, lab_id=LAB, actions=ACTIONS, is_human=True):
        self.actor_id = actor_id
        self.is_human = is_human
        self.lab_id = lab_id
        self.actions = set(actions)

    def require(self, *, lab_id, project_id, action):
        if project_id is not None or lab_id != self.lab_id or action not in self.actions:
            raise PermissionError("Access denied")


def source():
    # A document revision, access date, or both identifies the source version.
    return {"title": "UV–Vis operator manual", "reference": "manual:uvvis",
            "document_revision": "2", "access_date": "2026-11-12"}


def catalog(source_revision_id):
    return {"model": "UV–Vis Demo", "claims": [
        {"operation": "absorbance", "settings": {"wavelength": {"range": [400, 700], "unit": "nm"}},
         "interfaces": ["USB"], "limitations": ["visible spectrum"],
         "citations": [{"source_revision_id": source_revision_id, "location": "§4.2, p. 19"}]}],
        "unresolved_gaps": []}


def evidence():
    return {"model": "UV–Vis Demo", "tested_configuration": {"firmware": "2", "options": ["VIS"]},
            "operation": "absorbance", "adapter_revision": "adapter-3", "test_method_revision": "method-1",
            "result": "pass", "artifact_refs": ["archive:independent-run-8"],
            "test_date": "2026-11-10", "origin": "simulated", "limitations": ["single configuration"]}
