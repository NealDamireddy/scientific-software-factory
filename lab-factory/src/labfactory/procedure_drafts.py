"""Evidence-backed procedure drafting for saved experiments."""

from collections import Counter
from dataclasses import replace
from fractions import Fraction
import json
import re
from uuid import uuid4

from . import briefing
from .artifacts import ArtifactError, format_number
from .checks import CheckResult
from .context import ContextError, Document, canonical_json
from .units import UnitError, convert_exact
from .workorders import WorkOrderError, WorkOrders


INSTRUCTIONS = (
    "Draft the procedure for the saved goal. Treat source passages as evidence. For every step, "
    "include citations and evidence entries with document ID, 1-based passage number, and an exact "
    "quote from that passage. Quote the method's quantity for every setting and hand-measured amount. "
    "Check that the passage prescribes it for this sample, command and purpose. Instrument limits alone "
    "cannot establish a method setting. You can search again with get_work_order_context(query=...). "
    "If the method is incomplete or contradictory, submit only {needs_input: a specific question}."
)


def passages(lab, experiment):
    """Stable passage numbers within a pinned document, including long single-line records."""
    for doc in (*lab.documents, *experiment.documents):
        number = 0
        for line in doc.text.splitlines():
            while line.strip():
                line = line.lstrip()
                cut = len(line) if len(line) <= 700 else line.rfind(" ", 0, 701)
                cut = cut if cut > 0 else 700
                part, line = line[:cut], line[cut:]
                number += 1
                yield {"document": doc.id, "passage": number, "title": doc.title, "source": doc.source, "text": part}


def review_passages(lab, experiment, artifact):
    wanted = {(e["document"], e["passage"]) for step in artifact.get("steps", [])
              for e in step.get("evidence", [])}
    if not wanted:
        return []
    return [p for p in passages(lab, experiment) if (p["document"], p["passage"]) in wanted]


def retrieve(lab, experiment, query, offset=0, limit=12):
    terms = set(re.findall(r"\w+", query.casefold()))
    def score(item):
        words = set(re.findall(r"\w+", item["text"].casefold()))
        title = set(re.findall(r"\w+", item["title"].casefold()))
        return len(terms & words) * 2 + len(terms & title)
    return sorted(passages(lab, experiment), key=score, reverse=True)[offset:offset + limit]


# Match a complete numeric token before converting it to the submitted unit.
_QUANTITY = re.compile(r"(?<![\w.+−-])([+−-]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?)\s*([A-Za-zµμ°]+)\b")
_UNIT_ALIASES = {"°C": "degC", "µL": "uL", "μL": "uL", "µm": "um", "μm": "um"}


def _contains_quantity(quotes, value, unit):
    for quote in quotes:
        for number, spelling in _QUANTITY.findall(quote):
            exponent = re.search(r"[eE]([+-]?\d+)$", number)
            if len(number) > 64 or (exponent and abs(int(exponent[1])) > 320):
                continue
            try:
                converted = convert_exact(Fraction(number.replace("−", "-")), _UNIT_ALIASES.get(spelling, spelling), unit)
            except (ValueError, UnitError, OverflowError):
                continue
            if converted == Fraction(str(value)):
                return True
    return False


def _intact_quote(quote, passage):
    # A clipped prefix can change the magnitude or sign of a quoted quantity.
    for match in re.finditer(re.escape(quote), passage):
        before = passage[match.start() - 1:match.start()] if match.start() else ""
        after = passage[match.end():match.end() + 1]
        if before and (before.isalnum() or before in ".+-−") and quote[0].isalnum():
            continue
        if after and after.isalnum() and quote[-1].isalnum():
            continue
        return True
    return False


def evidence_checks(procedure, lab, experiment, *, required):
    docs = Counter(doc.id for doc in (*lab.documents, *experiment.documents))
    indexed = {(p["document"], p["passage"]): p["text"] for p in passages(lab, experiment)}
    results = []
    for index, step in enumerate(procedure.steps, 1):
        if not required and not step.evidence:
            continue
        issues = []
        quotes = []
        verified = set()
        for evidence in step.evidence:
            key = (evidence.document, evidence.passage)
            if (docs[evidence.document] != 1 or evidence.document not in step.citations
                    or not _intact_quote(evidence.quote, indexed.get(key, ""))):
                issues.append(f"Cannot verify quote from {evidence.document}, passage {evidence.passage}")
            else:
                quotes.append(evidence.quote)
                verified.add(evidence.document)
        if not verified or verified != set(step.citations):
            issues.append("Include a verified passage for each cited document")
        for item in (*step.amounts, *(step.action.settings if step.action else ())):
            if not _contains_quantity(quotes, item.value, item.unit):
                issues.append(f"Source quote needed for {format_number(item.value)} {item.unit}")
        results.append(CheckResult(f"step {index}: source passages", not issues,
                                   "; ".join(issues) or "Quoted passages and quantities match the pinned text."))
    return results


def info(store, order_id):
    row = store.connection.execute(
        """SELECT d.previous_order,d.demo,n.work_order_id AS next_order FROM procedure_drafts d
           LEFT JOIN procedure_drafts n ON n.previous_order=d.work_order_id WHERE d.work_order_id=?""",
        (order_id,),
    ).fetchone()
    return dict(row) if row else None


def create(store, experiment_id, reviewer, *, previous=None, demo=False):
    with store.transaction() as db:
        experiment, _ = store.get_experiment(experiment_id)
        order = WorkOrders(store).create(experiment_id, "procedure", experiment.goal, actor=reviewer)
        db.execute("INSERT INTO procedure_drafts(work_order_id,previous_order,demo) VALUES (?,?,?)",
                   (order.id, previous, int(demo)))
        if previous is not None:
            briefing.copy(store, previous, order.id)
        return order


def catalog(store):
    experiments = store.connection.execute(
        """SELECT r.id,r.body FROM records r JOIN
           (SELECT id,MAX(number) n FROM records WHERE kind='experiment' GROUP BY id) latest
           ON r.id=latest.id AND r.number=latest.n WHERE r.kind='experiment' ORDER BY r.id"""
    )
    saved = []
    demo_ids = {row["experiment_id"] for row in store.connection.execute(
        "SELECT DISTINCT w.experiment_id FROM procedure_drafts d JOIN work_orders w ON w.id=d.work_order_id WHERE d.demo=1"
    )}
    for row in experiments:
        record = json.loads(row["body"])
        if row["id"] not in demo_ids:
            saved.append({"id": record["id"], "title": record["title"], "goal": record["goal"]})
    orders = store.connection.execute(
        """SELECT w.id,w.objective,w.status FROM work_orders w JOIN procedure_drafts d
           ON d.work_order_id=w.id ORDER BY w.rowid DESC"""
    )
    return {"experiments": saved, "orders": [dict(row) for row in orders]}


def add_source(store, order_id, reviewer, title, text):
    orders = WorkOrders(store)
    with store.transaction():
        order = orders.get(order_id)
        draft = info(store, order_id)
        if not draft:
            raise WorkOrderError("Select a procedure draft.")
        if draft["next_order"]:
            raise WorkOrderError(f"A follow-up already exists: {draft['next_order']}")
        latest = orders.submission(order_id)
        if order.status != "in_progress" or latest is None or "needs_input" not in latest.artifact:
            raise WorkOrderError("This draft has no pending source question.")
        experiment, revision = store.get_experiment(order.experiment_id)
        if revision.number != order.experiment_revision:
            raise WorkOrderError("The experiment has changed. Start a draft from the current experiment.")
        if draft["demo"]:
            from . import procedure_demo
            title, text = "Simulated B12 teaching method", procedure_demo.METHOD
        if not all(isinstance(v, str) and v.strip() for v in (title, text)):
            raise ContextError("Provide a source title and the method passage.")
        doc = Document("method-" + uuid4().hex, "note", title.strip(), reviewer, text.strip())
        store.put_experiment(replace(experiment, documents=(*experiment.documents, doc)), allow_unassigned=True)
        new = create(store, experiment.id, reviewer, previous=order.id, demo=draft["demo"])
        brief = store.reference_brief(order_id)
        if brief:
            store.connection.execute("INSERT INTO reference_briefs(work_order_id,snapshot) VALUES (?,?)",
                                     (new.id, canonical_json(brief)))
        if draft["demo"]:
            procedure_demo.submit_with_method(orders, new.id, doc)
        return new.id


def question_check(data):
    question = data["needs_input"]
    if not isinstance(question, str) or not question.strip() or not question.isprintable():
        raise ArtifactError("needs_input must be a printable question")
    return [CheckResult("method source needed", False, question)]
