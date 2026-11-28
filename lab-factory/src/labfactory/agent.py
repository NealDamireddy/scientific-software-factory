"""The four operations available to a connected coding agent."""

from copy import deepcopy
from dataclasses import asdict
from functools import wraps

from . import analysis_requests, offline_app, stage_plot
from .artifacts import ARTIFACT_EXAMPLES, ArtifactError
from .context import to_dict
from .store import NotFound, Store
from .workorders import WorkOrderError, WorkOrders


INSTRUCTIONS = (
    "Build the artifact from the pinned lab and experiment context only. Use only commands "
    "the instrument lists, with every required setting, each in a supported unit and within "
    "its limits. In procedures, put instrument values in the step's action and hand-measured "
    "values in amounts; never write numbers with units in the text. Every procedure step "
    "must cite a document id from the lab or experiment. If previous_rejection is present, "
    "address its reason. Submit; if checks fail, read each failing result, fix the artifact, "
    "and resubmit. A person reviews and releases passing work."
)

B12_INSTRUCTIONS = (
    "Write Python source for the single function analyze(readings, slope, intercept). "
    "The three readings are already simulated absorbances at 550 nm. Compute their arithmetic mean, "
    "subtract the calibration intercept, then divide by slope to obtain mg/L. Read the pinned calibration "
    "document. Use the supplied slope and intercept. The host owns the range gate for each replicate. "
    "The arithmetic runner supports local assignments, return, +, -, *, /, readings[0..2], "
    "sum(readings) and len(readings). Submit an object with the single field source. Independent "
    "reference tests run on the submitted source. Read any failure or previous rejection and revise. "
    "A reviewer approves the numbered source before a result can be saved."
)


def _return_domain_errors(method):
    @wraps(method)
    def call(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except (NotFound, WorkOrderError, ArtifactError) as exc:
            return {"error": str(exc)}
    return call


class AgentTools:
    def __init__(self, store: Store):
        self._store = store
        self._orders = WorkOrders(store)

    @_return_domain_errors
    def list_work_orders(self, status: str = "open") -> list[dict] | dict:
        return [asdict(order) for order in self._orders.list(status)] + analysis_requests.listing(self._store, status)

    @_return_domain_errors
    def get_work_order_context(self, work_order_id: str, query: str = "", offset: int = 0) -> dict:
        if work_order_id.startswith(analysis_requests.PREFIXES):
            request = analysis_requests.detail(self._store, work_order_id)
            kind = analysis_requests.kind(work_order_id)
            return {"work_order": {**{k: request[k] for k in ("id", "status", "worker")}, "claim_id": request["turn"]},
                    kind: {k: request[k] for k in ("objective", "contexts", "turn", "history")},
                    "instructions": offline_app.INSTRUCTIONS if kind == "offline_app" else stage_plot.INSTRUCTIONS}
        # Read status, pins, and rejection history at the same point in time.
        with self._store.read_transaction():
            order = self._orders.get(work_order_id)
            lab, experiment = self._orders.pinned_context(work_order_id)
            context = {
                "work_order": {**asdict(order), "claim_id": self._orders.active_claim_id(order)},
                "lab": to_dict(lab),
                "experiment": to_dict(experiment),
                "artifact_example": deepcopy(ARTIFACT_EXAMPLES[order.kind]),
                "instructions": B12_INSTRUCTIONS if order.kind == "analysis_app" else INSTRUCTIONS,
                "previous_rejection": self._orders.latest_rejection(work_order_id),
            }
            brief = self._store.reference_brief(work_order_id)
            if brief is not None:
                context["reference_brief"] = brief
            from . import honey_service

            from . import tabular_service

            if tabular_service.is_order(order):
                from .tabular_analysis import author_instructions

                context["analysis"] = tabular_service.public_context(self._store, order)
                context["artifact_example"] = {"source": "", "explanation": "", "tests": []}
                languages = context["analysis"].get("allowed_languages")
                if languages:
                    context["artifact_example"]["language"] = languages[0]
                context["instructions"] = author_instructions(languages) + (
                    " The public protocol and standards in analysis describe this experiment. "
                    "If required information is missing, submit a single field needs_input with a concise "
                    "question instead of fabricating an answer. The assigned control is held by the reviewer."
                )
                if "research_context" in context["analysis"]:
                    context["instructions"] += (
                        " Ground the calculation in research_context: identify the assigned instrument, "
                        "its export units and firmware behavior, and the project's reporting goal and method. "
                        "A capability or setting limit does not establish the setting actually used. Explain "
                        "which instrument or document supports each consequential conversion or correction. "
                        "When a missing or conflicting fact changes the result, ask a focused question."
                    )
                if context["previous_rejection"]:
                    # Free-text reviewer feedback can mention the hidden target or reading.
                    context["previous_rejection"]["reason"] = "The reviewer requested a revision."
            elif honey_service.is_honey_order(order):
                honey_service.require_context(lab, experiment, brief)
                context["instructions"] = honey_service.INSTRUCTIONS
                context["artifact_example"] = {"algorithm": [], "table": [], "citations": [], "tests": []}
            elif brief is not None:
                context["instructions"] += (
                    " This is a reference-planning order. Use the selected sources and their stated "
                    "limits to write a cited procedure for review. Identify method transfer and any "
                    "details the lab must establish. No local instrument commands have been registered."
                )
                context["artifact_example"] = {"steps": [{
                    "text": "Review the cited source and record which conditions apply to the sample.",
                    "citations": [brief["findings"][0]["id"]],
                }]}
            if order.kind == "procedure":
                from . import procedure_drafts
                draft = procedure_drafts.info(self._store, order.id)
                if draft:
                    if not isinstance(query, str) or type(offset) is not int or offset < 0:
                        raise WorkOrderError("Provide a text query and a nonnegative passage offset.")
                    context["draft"] = draft
                    context["instructions"] += " " + procedure_drafts.INSTRUCTIONS
                    context["passages"] = procedure_drafts.retrieve(lab, experiment, query or order.objective, offset)
                    for record in (context["experiment"], context["lab"]):
                        for doc in record["documents"]:
                            del doc["text"]
                    context["artifact_example"] = {"steps": [{"text": "<instruction>", "citations": ["<id>"],
                        "evidence": [{"document": "<id>", "passage": 1, "quote": "<exact passage excerpt>"}]}]}
            return context

    @_return_domain_errors
    def claim_work_order(self, work_order_id: str, worker: str, untagged_artifact: dict | None = None) -> dict:
        if work_order_id.startswith(analysis_requests.PREFIXES):
            if untagged_artifact is not None:
                raise WorkOrderError("Start the analysis request before authoring its artifact.")
            return analysis_requests.claim(self._store, work_order_id, worker)
        with self._store.transaction():
            order = self._orders.claim(work_order_id, worker, untagged_artifact=untagged_artifact)
            return {**asdict(order), "claim_id": self._orders.active_claim_id(order)}

    @_return_domain_errors
    def submit_artifact(self, work_order_id: str, worker: str, artifact: dict, claim_id: int | None = None) -> dict:
        if work_order_id.startswith(analysis_requests.PREFIXES):
            if type(claim_id) != int or claim_id != artifact.get("turn"):
                raise WorkOrderError("Supply the claim ID for this analysis turn.")
            return analysis_requests.submit(self._store, work_order_id, worker, artifact)
        submission = self._orders.submit(work_order_id, worker, artifact, claim_id)
        return {
            "status": "in_review" if submission.passed else "in_progress",
            "passed": submission.passed,
            "results": [asdict(check) for check in submission.results],
            "submission": submission.number,
            "artifact_digest": submission.artifact_digest,
        }
