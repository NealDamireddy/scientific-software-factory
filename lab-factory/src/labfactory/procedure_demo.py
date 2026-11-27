"""Bundled simulated walkthrough for the reviewer portal."""
from uuid import uuid4

from .context import Command, Document, Experiment, Instrument, Lab, Parameter
from .procedure_drafts import create
from .workorders import WorkOrders


METHOD = "For the simulated vial A teaching example, read absorbance at 550 nm."
WORKER = "Bundled teaching example"


def start(store, reviewer):
    unique = uuid4().hex
    lab = Lab("demo-procedure-lab-" + unique, "Teaching lab", (
        Instrument("uvvis-1", "Simulated spectrophotometer", "Teaching UV-Vis", "1",
                   (Parameter("wavelength", "nm", 400, 700),), (Command("read_absorbance", ("wavelength",)),)),
    ), (Document("sop-cuvette", "sop", "Cuvette handling", "Teaching SOP",
                 "Rinse the cuvette and keep the optical faces clean."),))
    experiment = Experiment("demo-procedure-" + unique, lab.id, "Simulated B12 absorbance",
                            "Measure absorbance of the simulated reference solution in vial A.",
                            ("uvvis-1",), (Document("vial-a", "note", "Sample record", "Teaching notebook",
                                                   "Use the labeled reference solution in vial A."),))
    with store.transaction():
        store.put_lab(lab)
        store.put_experiment(experiment)
        order = create(store, experiment.id, reviewer, demo=True)
        orders = WorkOrders(store)
        orders.claim(order.id, WORKER)
        orders.submit(order.id, WORKER, {"needs_input": "Which wavelength does the method specify for vial A?"})
        return order.id


def submit_with_method(orders, order_id, doc):
    steps = [
        {"text": "Prepare the cuvette as directed.", "citations": ["sop-cuvette"],
         "evidence": [{"document": "sop-cuvette", "passage": 1, "quote": "Rinse the cuvette"}]},
        {"text": "Read the absorbance of the reference solution.", "citations": [doc.id],
         "evidence": [{"document": doc.id, "passage": 1, "quote": METHOD}],
         "action": {"instrument_id": "uvvis-1", "command": "read_absorbance",
                    "settings": [{"parameter": "wavelength", "value": 550, "unit": "nm"}]}}
    ]
    orders.claim(order_id, WORKER)
    orders.submit(order_id, WORKER, {"steps": steps})
