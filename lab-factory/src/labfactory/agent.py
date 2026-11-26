"""The four operations available to a connected coding agent."""

from copy import deepcopy
from dataclasses import asdict
from functools import wraps

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
        return [asdict(order) for order in self._orders.list(status)]

    @_return_domain_errors
    def get_work_order_context(self, work_order_id: str) -> dict:
        # Read status, pins, and rejection history at the same point in time.
        with self._store.read_transaction():
            order = self._orders.get(work_order_id)
            lab, experiment = self._orders.pinned_context(work_order_id)
            return {
                "work_order": asdict(order),
                "lab": to_dict(lab),
                "experiment": to_dict(experiment),
                "artifact_example": deepcopy(ARTIFACT_EXAMPLES[order.kind]),
                "instructions": INSTRUCTIONS,
                "previous_rejection": self._orders.latest_rejection(work_order_id),
            }

    @_return_domain_errors
    def claim_work_order(self, work_order_id: str, worker: str) -> dict:
        return asdict(self._orders.claim(work_order_id, worker))

    @_return_domain_errors
    def submit_artifact(self, work_order_id: str, worker: str, artifact: dict) -> dict:
        submission = self._orders.submit(work_order_id, worker, artifact)
        return {
            "status": "in_review" if submission.passed else "in_progress",
            "passed": submission.passed,
            "results": [asdict(check) for check in submission.results],
            "submission": submission.number,
            "artifact_digest": submission.artifact_digest,
        }
