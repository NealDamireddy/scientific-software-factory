"""Author-visible evidence from the saved research experiment behind an analysis."""

from .context import ContextError, canonical_json, to_dict


def _documents(record, ids):
    if (not isinstance(ids, list) or any(not isinstance(key, str) for key in ids)
            or len(ids) != len(set(ids))):
        raise ContextError("Select a list of unique document IDs for each context record.")
    documents = {doc.id: doc for doc in record.documents}
    for key in ids:
        if key not in documents:
            raise ContextError(f"Unknown document {key} on {record.id}.")
    return [to_dict(documents[key]) for key in ids]


def snapshot(store, selection, *, include_project_documents=False):
    if (not isinstance(selection, dict) or not isinstance(selection.get("experiment_id"), str)
            or not selection["experiment_id"].strip()
            or set(selection) - {"experiment_id", "lab_revision", "experiment_revision",
                                 "lab_document_ids", "experiment_document_ids"}):
        raise ContextError("Select a saved experiment and optional lab and experiment document IDs.")
    for field in ("lab_revision", "experiment_revision"):
        if field in selection and (type(selection[field]) is not int or selection[field] < 1):
            raise ContextError(f"Select a positive integer for {field}.")
    exp, exp_rev = store.get_experiment(selection["experiment_id"], selection.get("experiment_revision"))
    lab, lab_rev = store.lab_for_experiment(exp, selection.get("lab_revision"))
    default_documents = [doc.id for doc in exp.documents] if include_project_documents else []
    evidence = {
        "lab": {"id": lab.id, "name": lab.name, "revision": lab_rev.number, "digest": lab_rev.digest,
                "instruments": [to_dict(lab.instrument(key)) for key in exp.instrument_ids],
                "documents": _documents(lab, selection.get("lab_document_ids", []))},
        "experiment": {"id": exp.id, "title": exp.title, "goal": exp.goal, "revision": exp_rev.number,
                       "digest": exp_rev.digest,
                       "documents": _documents(exp, selection.get("experiment_document_ids", default_documents))},
    }
    if len(canonical_json(evidence).encode()) > 64 * 1024:
        raise ContextError("Selected research context exceeds 64 KiB. Select shorter source documents.")
    return evidence
