"""Resolve document IDs across the lab and experiment pinned to an order."""

from .artifacts import format_citation
from .context import ContextError, Document, Experiment, Lab


class CitationError(ContextError):
    """A citation does not identify exactly one document."""


class CitationIndex:
    def __init__(self, lab: Lab, experiment: Experiment) -> None:
        self._matches: dict[str, list[tuple[str, Document]]] = {}
        for origin, record in (("lab", lab), ("experiment", experiment)):
            for document in record.documents:
                self._matches.setdefault(document.id, []).append((origin, document))

    def resolve(self, document_id: str) -> tuple[str, Document]:
        matches = self._matches.get(document_id)
        if not matches:
            raise CitationError(f"unknown document {format_citation(document_id)}")
        if len(matches) > 1:
            raise CitationError(f"ambiguous document {format_citation(document_id)} in pinned context")
        return matches[0]
