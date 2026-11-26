"""Create a procedure work order from the exact references a reviewer selected."""

import re

from . import references
from .context import ContextError, Document, Experiment, Instrument, Lab, canonical_digest, canonical_json
from .store import Store
from .workorders import WorkOrderError, WorkOrders


def _snapshot(request: dict) -> dict:
    if not isinstance(request, dict) or set(request) != {"instrument", "q", "catalog_digest", "selections"}:
        raise ContextError("Supply the instrument, objective, catalog digest and selected sources.")
    objective = request["q"]
    if not isinstance(objective, str) or not objective.strip():
        raise ContextError("Enter an experiment objective before creating an order.")
    if not isinstance(request["catalog_digest"], str) or not re.fullmatch(r"[0-9a-f]{64}", request["catalog_digest"]):
        raise ContextError("Supply the SHA-256 digest from the catalog.")
    result = references.search(request["instrument"], objective)
    if request["catalog_digest"] != result["catalog_digest"]:
        raise WorkOrderError("The catalog has changed. Search again and review your sources.")
    selections = request["selections"]
    if not isinstance(selections, list) or not selections:
        raise ContextError("Choose at least one source from the search results.")
    matches = {source["id"]: source for source in result["findings"]}
    selected = set()
    for item in selections:
        if not isinstance(item, dict) or set(item) != {"id", "digest"} or not all(
            isinstance(value, str) for value in item.values()
        ):
            raise ContextError("Each selection needs a source ID and its digest.")
        if not re.fullmatch(r"[0-9a-f]{64}", item["digest"]):
            raise ContextError("Supply the SHA-256 digest from each selected source.")
        source_id = item["id"]
        if source_id in selected or source_id not in matches:
            raise ContextError("Choose each source once and only from this search.")
        if item["digest"] != matches[source_id]["digest"]:
            raise WorkOrderError("A selected source has changed. Search again and review it.")
        selected.add(source_id)
    findings = [source for source in result["findings"] if source["id"] in selected]
    overview, brief = references.describe(result["instrument"], result["query"], findings)
    return {
        "instrument": result["instrument"], "query": result["query"], "catalog_digest": result["catalog_digest"],
        "overview": overview, "brief": brief, "findings": findings,
    }


def create_order(store: Store, reviewer: str, request: dict) -> dict:
    snapshot = _snapshot(request)
    selector = snapshot["instrument"]
    objective = snapshot["query"]
    instruments = ()
    if selector["scope"] == "model":
        instruments = (Instrument(
            selector["id"], f'{selector["manufacturer"]} {selector["model"]}', selector["model"],
            "Unverified", (), (), "Catalog model selected for planning. Local configuration is unverified.",
        ),)
    lab = Lab("reference-lab-" + canonical_digest(selector), "Shared reference library", instruments, ())
    documents = tuple(
        Document(
            source["id"], "note" if source["kind"] == "procedure" else source["kind"],
            source["title"], source["url"],
            f'Externally published {source["kind"]}. {source["publisher"]}. {source["version"]}. {source["locator"]}\n'
            f'{source["summary"]}\nApplicability: {source["scope"]}\nCatalog record SHA-256: {source["digest"]}',
        )
        for source in snapshot["findings"]
    )
    experiment = Experiment(
        "reference-experiment-" + canonical_digest(snapshot), lab.id, objective, objective,
        tuple(instrument.id for instrument in instruments), documents,
    )
    with store.transaction() as db:
        store.put_lab(lab)
        store.put_experiment(experiment, allow_unassigned=True)
        order = WorkOrders(store).create(experiment.id, "procedure", objective, actor=reviewer)
        db.execute(
            "INSERT INTO reference_briefs(work_order_id, snapshot) VALUES (?,?)",
            (order.id, canonical_json(snapshot)),
        )
    return {"id": order.id}
