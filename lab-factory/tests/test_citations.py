from copy import deepcopy

from labfactory.cli import main
from labfactory.context import experiment_from_dict, lab_from_dict
from labfactory.store import Store
from labfactory.workorders import WorkOrders


def test_cli_reads_pinned_documents_from_instrumentless_order_after_reopen(
    tmp_path, capsys, uvvis_lab_dict, b12_experiment_dict,
):
    db = tmp_path / "factory.db"
    lab_data, experiment_data = uvvis_lab_dict, b12_experiment_dict
    lab_data["instruments"] = []
    experiment_data["instrument_ids"] = []
    lab_doc, = lab_data["documents"]
    exp_doc, = experiment_data["documents"]
    lab_doc["text"] = "First line\n\n  Indented line\nLast line without a newline"
    exp_doc["text"] = "Reference μ\nSecond paragraph\n\n"

    with Store(db) as store:
        store.put_lab(lab_from_dict({**lab_data, "documents": []}))
        store.put_lab(lab_from_dict(lab_data))
        store.put_experiment(experiment_from_dict(experiment_data, allow_unassigned=True), allow_unassigned=True)
        orders = WorkOrders(store)
        order = orders.create(experiment_data["id"], "procedure", "Read the references")
        orders.claim(order.id, "worker")
        submission = orders.submit(order.id, "worker", {
            "steps": [{"text": "Read the references.", "citations": [exp_doc["id"]]}],
        })
        assert submission.passed
        before = (orders.get(order.id), orders.history(order.id), orders.submissions(order.id))

        newer_lab, newer_experiment = deepcopy(lab_data), deepcopy(experiment_data)
        newer_lab["documents"][0]["text"] = "New lab text"
        newer_experiment["documents"][0]["text"] = "New experiment text"
        newer_experiment["documents"].append({**lab_doc, "id": "new-document"})
        newer_experiment["documents"].append(lab_doc)
        store.put_lab(lab_from_dict(newer_lab))
        store.put_experiment(experiment_from_dict(newer_experiment, allow_unassigned=True), allow_unassigned=True)

    for origin, record_id, revision, document in (
        ("lab", lab_data["id"], 2, lab_doc),
        ("experiment", experiment_data["id"], 1, exp_doc),
    ):
        assert main(["--db", str(db), "wo", "citation", order.id, document["id"]]) == 0
        output = capsys.readouterr()
        assert output.err == ""
        assert output.out == (
            f"{origin} {record_id} revision {revision}\n"
            f"document: {document['id']}\nkind: {document['kind']}\n"
            f"title: {document['title']}\nsource: {document['source']}\n\n{document['text']}"
        )

    assert main(["--db", str(db), "wo", "citation", order.id, "new-document"]) == 1
    assert capsys.readouterr().err == "error: unknown document new-document\n"
    with Store(db) as store:
        orders = WorkOrders(store)
        assert (orders.get(order.id), orders.history(order.id), orders.submissions(order.id)) == before


def test_cli_rejects_colliding_citation_and_missing_order(tmp_path, capsys, uvvis_lab_dict, b12_experiment_dict):
    db = tmp_path / "factory.db"
    document, = uvvis_lab_dict["documents"]
    b12_experiment_dict["documents"].append(document)
    with Store(db) as store:
        store.put_lab(lab_from_dict(uvvis_lab_dict))
        store.put_experiment(experiment_from_dict(b12_experiment_dict))
        order = WorkOrders(store).create(b12_experiment_dict["id"], "procedure", "Read the references")

    for order_id, error in (
        (order.id, f"ambiguous document {document['id']} in pinned context"),
        ("WO-404", "unknown work order WO-404"),
    ):
        assert main(["--db", str(db), "wo", "citation", order_id, document["id"]]) == 1
        output = capsys.readouterr()
        assert output.out == ""
        assert output.err == f"error: {error}\n"
