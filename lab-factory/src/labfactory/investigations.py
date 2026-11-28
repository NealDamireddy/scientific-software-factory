"""Resolve an investigation against the selected project's registered records."""
from dataclasses import replace
import json
import re
from uuid import UUID

from . import analysis_requests, briefing, experiment_catalog, first_draft, procedure_drafts, research_experiments, tabular_service
from . import library as texts
from .context import ContextError, Experiment, Lab, canonical_digest, canonical_json, to_dict
from .store import NotFound
from .artifacts import render_artifact
from .workorders import WorkOrderError, WorkOrders

# A registered experiment supplies the project's durable context. Each procedure investigation
# gets its own objective and revision history while retaining its relationship to this root.
_MEMBERS = "(SELECT ? UNION SELECT context_id FROM research_investigations WHERE project_id=?)"


def projects(store):
    children = {r["context_id"] for r in store.connection.execute(
        "SELECT context_id FROM research_investigations WHERE context_id IS NOT NULL")}
    recent = store.connection.execute("""
        SELECT i.id, i.project_id, l.experiment_id, json_extract(i.result,'$.objective') AS objective
          FROM research_investigations i JOIN research_experiment_requests l ON l.request_id=i.id ORDER BY i.rowid DESC
    """)
    # Directory reads need names only. Avoid one remote round trip per project
    # or downloading large lab documents for the sidebar.
    lab_names = {row["id"]: row["name"] for row in store.connection.execute("""
        SELECT r.id,json_extract(r.body,'$.name') AS name FROM records r
        JOIN (SELECT id,MAX(number) AS latest FROM records WHERE kind='lab' GROUP BY id) h
        ON h.id=r.id AND h.latest=r.number WHERE r.kind='lab'
    """)}
    hypotheses = {row["project_id"]: row["hypothesis"] for row in store.connection.execute(
        "SELECT project_id,hypothesis FROM research_project_info")}
    summaries = []
    internal_labs = set()
    project_labs = set()
    for row in experiment_catalog.summary_rows(store):
        lab_id = row["lab_id"]
        if experiment_catalog.is_generated(row["id"], lab_id):
            internal_labs.add(lab_id)
        elif row["id"] not in children:
            summaries.append(dict(row, lab_name=lab_names[lab_id], hypothesis=hypotheses.get(row["id"], "")))
            project_labs.add(lab_id)
    # A newly registered lab is selectable even before it owns a project.
    # Keep labs used only for generated uploads and demos out of the picker.
    labs = {key: name for key, name in lab_names.items() if key not in internal_labs or key in project_labs}
    if not labs:
        labs[_WORKSPACE_LAB.id] = _WORKSPACE_LAB.name
    return {"projects": summaries, "labs": [{"id": key, "name": name} for key, name in labs.items()],
            "experiments": research_experiments.summaries(store.connection),
            "investigations": [dict(r) for r in recent]}


def library(store, field):
    if field not in ("documents", "instruments"):
        raise ContextError("Choose documents or instruments.")
    rows = store.connection.execute("""
        SELECT r.kind,r.id,r.number,json_extract(r.body,'$.name') AS name,json_extract(r.body,'$.title') AS title,
               json_extract(r.body, ?) AS items
          FROM records r JOIN (SELECT kind,id,MAX(number) AS head FROM records GROUP BY kind,id) h
            ON h.kind=r.kind AND h.id=r.id AND h.head=r.number
         WHERE r.kind IN ('lab','experiment') ORDER BY r.kind,r.id
    """, ("$." + field,))
    return {"records": [{"owner": row["name"] or row["title"], "owner_id": row["id"], "revision": row["number"],
                         **entry} for row in rows for entry in json.loads(row["items"] or "[]")]}


_WORKSPACE_LAB = Lab("research-workspace", "Research workspace", (), ())


def register(store, title, lab_id=None, hypothesis=None):
    title = research_experiments.text(title, "project name", 250)
    if lab_id is not None and (not isinstance(lab_id, str) or not lab_id):
        raise ContextError("Choose a registered lab.")
    # Older clients retry with only the project title. Retain that identity
    # for legacy projects and for projects created in the default workspace.
    key = "workspace-" + canonical_digest(title)
    with store.transaction() as db:
        existing_lab = db.execute("""SELECT json_extract(body,'$.lab_id') AS lab_id FROM records
            WHERE kind='experiment' AND id=? ORDER BY number DESC LIMIT 1""", (key,)).fetchone()
        if lab_id and lab_id != _WORKSPACE_LAB.id and (not existing_lab or existing_lab["lab_id"] != lab_id):
            key = "workspace-" + canonical_digest([lab_id, title])
        if lab_id == _WORKSPACE_LAB.id and existing_lab and existing_lab["lab_id"] != lab_id:
            key = "workspace-" + canonical_digest([lab_id, title])
        try:
            existing, _ = store.get_experiment(key)
        except NotFound:
            lab_id = lab_id or _WORKSPACE_LAB.id
            if lab_id == _WORKSPACE_LAB.id:
                if not db.execute("SELECT 1 FROM records WHERE kind='lab' AND id=?", (lab_id,)).fetchone():
                    store.put_lab(_WORKSPACE_LAB)
            else:
                store.get_lab(lab_id)
            store.put_experiment(Experiment(key, lab_id, title, title, (), ()), allow_unassigned=True)
            if hypothesis is not None:
                research_experiments.set_hypothesis(store, key, hypothesis)
        else:
            if existing.title != title:
                raise WorkOrderError("This project ID is already in use.")
            lab_id = existing.lab_id
        lab, _ = store.get_lab(lab_id)
        return {"id": key, "title": title, "lab_id": lab_id, "lab_name": lab.name,
                "hypothesis": research_experiments.hypothesis(store, key)}


_APP_OWNER = """COALESCE((SELECT project_id FROM research_app_projects WHERE app_id=drift_requests.id),
                  CASE WHEN json_array_length(contexts)=1 THEN json_extract(contexts,'$[0].experiment.id') END)"""
_TABULAR_OWNER = """COALESCE(json_extract(i.profile,'$.project.id'),json_extract(i.profile,'$.research_context.experiment.id'),
                      p.experiment_id,(SELECT project_id FROM research_app_projects WHERE app_id=i.work_order_id))"""


def app_project(store, key):
    if key.startswith(analysis_requests.PREFIXES):
        row = store.connection.execute(f"SELECT {_APP_OWNER} AS owner FROM drift_requests WHERE id=?", (key,)).fetchone()
    else:
        row = store.connection.execute(f"""SELECT {_TABULAR_OWNER} AS owner FROM tabular_intakes i
            LEFT JOIN work_orders p ON p.id=json_extract(i.profile,'$.procedure.order_id') WHERE i.work_order_id=?""",
            (key,)).fetchone()
    if row is None:
        raise NotFound("Unknown project analysis app.")
    owner = row["owner"]
    if owner is None:
        return None
    parent = store.connection.execute("SELECT project_id FROM research_investigations WHERE context_id=?", (owner,)).fetchone()
    return parent["project_id"] if parent else owner


def attach_app(store, project, key):
    if not isinstance(project, str) or not isinstance(key, str):
        raise ContextError("Select an analysis and a registered project.")
    with store.transaction() as db:
        store.get_experiment(project)
        owner = app_project(store, key)
        if owner and owner != project:
            raise WorkOrderError("This analysis belongs to another project.")
        if not owner:
            db.execute("INSERT INTO research_app_projects VALUES (?,?)", (key, project))
    return {"id": key, "project_id": project}


def _current_project_resources(items):
    seen = set()
    result = []
    for item in items:
        if item.get("next_order"):
            continue
        if item["kind"] == "data":
            identity = (item["title"], item["digest"])
            if identity in seen:
                continue
            seen.add(identity)
        result.append(item)
    return result


def resources(store, project, *, include_history=False):
    db = store.connection
    args = (project, project)
    result = []
    for r in db.execute(f"""
        SELECT o.id, o.objective,
               CASE WHEN d.work_order_id IS NOT NULL THEN 'superseded'
                    WHEN o.status='in_progress' AND (
                        SELECT json_extract(latest.artifact,'$.needs_input') FROM submissions latest
                        WHERE latest.work_order_id=o.id ORDER BY latest.number DESC LIMIT 1
                    ) IS NOT NULL THEN 'needs_input'
                    ELSE o.status END AS status,
               o.released_submission, s.artifact_digest,
               a.work_order_id AS automatic, d.work_order_id AS next_order FROM work_orders o
        LEFT JOIN automatic_procedures a ON a.work_order_id=o.id
        LEFT JOIN procedure_drafts d ON d.previous_order=o.id
        LEFT JOIN submissions s ON s.work_order_id=o.id AND s.number=o.released_submission
        WHERE o.kind='procedure' AND o.experiment_id IN {_MEMBERS}
        ORDER BY o.rowid DESC""", args):
        result.append(dict(kind="procedure", id=r["id"], title=r["objective"], status=r["status"],
                           automatic=bool(r["automatic"]), submission=r["released_submission"], digest=r["artifact_digest"],
                           **({"next_order": r["next_order"]} if r["next_order"] else {})))
    for r in db.execute(f"""
        SELECT id,objective,status,artifact_digest,json_extract(contexts,'$[0].dataset.columns') AS columns,
               json_extract(contexts,'$[0].procedure.order_id') AS procedure_id,
               json_extract(contexts,'$[0].dataset.digest') AS dataset_digest,
               json_extract(contexts,'$[0].datasets') AS datasets FROM drift_requests
        WHERE {_APP_OWNER} IN {_MEMBERS}
        ORDER BY rowid DESC""", args):
        result.append(dict(kind="app", id=r["id"], title=r["objective"], status=r["status"], digest=r["artifact_digest"],
                           columns=json.loads(r["columns"]) if r["columns"] else None, procedure_id=r["procedure_id"], dataset_digest=r["dataset_digest"],
                           dataset_digests=[d["digest"] for d in json.loads(r["datasets"] or "[]")]))

    linked = f"""FROM tabular_intakes i LEFT JOIN work_orders p ON p.id=json_extract(i.profile,'$.procedure.order_id')
                 JOIN work_orders a ON a.id=i.work_order_id WHERE {_TABULAR_OWNER} IN {_MEMBERS}"""
    def add_file(order, filename, digest, suffix, fields, procedure_id):
        result.append(dict(kind="data", id=order + "/" + suffix, title=filename, digest=digest,
                           path=f"analysis/orders/{order}/{suffix}", columns=json.loads(fields), procedure_id=procedure_id))
    for r in db.execute("""SELECT a.id,a.objective,a.status,a.released_submission,
                        json_extract(i.batch,'$.csv_name') AS filename,json_extract(i.batch,'$.csv_digest') AS digest,
                        json_extract(i.profile,'$.procedure.order_id') AS procedure_id, json_extract(i.profile,'$.mapping') AS fields """ + linked + " ORDER BY a.rowid DESC", args):
        result.append(dict(kind="app", id=r["id"], title=r["objective"], status=r["status"],
                           submission=r["released_submission"], tabular=True, procedure_id=r["procedure_id"]))
        add_file(r["id"], r["filename"], r["digest"], "uploads/readings", r["fields"], r["procedure_id"])
    for r in db.execute(f"""SELECT t.work_order_id,t.id,json_extract(t.receipt,'$.csv_name') AS filename,
                json_extract(t.receipt,'$.csv_digest') AS digest,json_extract(i.profile,'$.procedure.order_id') AS procedure_id, json_extract(i.profile,'$.mapping') AS fields
                FROM tabular_runs t JOIN tabular_intakes i ON t.work_order_id=i.work_order_id
                LEFT JOIN work_orders p ON p.id=json_extract(i.profile,'$.procedure.order_id')
                WHERE {_TABULAR_OWNER} IN {_MEMBERS} ORDER BY t.id DESC""", args):
        add_file(r["work_order_id"], r["filename"], r["digest"], f"runs/{r['id']}/readings", r["fields"], r["procedure_id"])
    return result if include_history else _current_project_resources(result)


def inventory(store, project):
    root, revision = research_experiments.check_project(store, project)
    lab, lab_revision = store.get_lab(root.lab_id)
    assets = resources(store, project, include_history=True)
    records, requests = research_experiments.project_records(store, project, assets)
    return {"id": project, "title": root.title, "resources": _current_project_resources(assets),
            "lab_id": lab.id, "lab_name": lab.name, "hypothesis": research_experiments.hypothesis(store, project),
            "experiments": records, "context": {"experiment": to_dict(root), "lab": to_dict(lab),
                        "experiment_revision": revision.number, "lab_revision": lab_revision.number},
            "investigations": requests}


_APP = r"\b(analy[sz](?:e|ing|is)|apps?|plot|graph|chart|visuali[sz]e|fit|process|calculate|summari[sz]e)\b"
_PROC = r"\b(procedures?|protocols?|sop|plan|collect|acquire|prepare|measure|instructions|how (?:do|should|can) (?:i|we))\b"
_STOP = set("""the a an i we my our this that it of for in on and or to at with from by into me please would like want
    use using existing saved project reusable build make create draft generate new request write give need help download
    procedure procedures protocol protocols sop method app apps application analysis analyze analyse plot graph compare
    readings reading data dataset datasets file files csv results measurement measurements recorded estimate calculate
    plan collect prepare run show inspect check offline software steps according through how do should can
    is are have already taking take some as""".split())


def _terms(text):
    return {w.removesuffix("s") for w in re.findall(r"[^\W_]+", text.casefold()) if w not in _STOP and len(w) > 1}


def _library_entries(store, lab_id, brief, objective, taken=frozenset()):
    """Entries to pin: visible text for the matched catalog findings, then the lab's own contributed titles."""
    try:
        ids = [row["id"] for row in ((brief or {}).get("reference_library") or {}).get("findings", [])]
        catalog = texts.visible(store, lab_id, ids)
        entries = [catalog[i] for i in ids if i in catalog]
        wanted = _terms(objective)
        ranked = sorted(((len(wanted & _terms(e["title"])), e) for e in texts.visible(store, lab_id).values()
                         if e["source_id"].startswith("contributed-")), key=lambda p: (-p[0], p[1]["title"]))
        entries += [e for count, e in ranked if count >= 2][:3]
        chosen, size = [], 0
        for entry in entries:
            # A document id the project already holds is skipped at resolution, so it must not be claimed.
            if entry["document_id"] in taken or size + entry["bytes"] > texts.MAX_PINNED_BYTES:
                continue
            chosen.append(entry)
            size += entry["bytes"]
        return chosen[:texts.MAX_PINNED]
    except Exception:
        if not store.connection.in_transaction:
            raise  # A failed read that ended the transaction must not be hidden.
        return []


def intent(text):
    text = text.casefold()
    # "Analyze ... using the procedure" describes one action with a reference.
    main = re.split(r"\b(?:using|according to|following|with (?:our|the|my))\b", text)[0]
    app = re.search(_APP, main)
    proc = re.search(_PROC, main)
    if not app and not proc and re.search(r"\b(readings|data|dataset|csv)\b", text) and re.search(
            r"\b(use|compare|estimate|interpret|evaluate|summarize)\b", text):
        return "app"
    if app and proc:
        if re.search(r"\b(?:and|then|both|also)\b", main):
            return "both"
        if re.search(r"\b(?:procedure|protocol|instructions) (?:for|to)\b", main):
            return "procedure"
        return None
    return "app" if app else "procedure" if proc else None


_DAY = r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b"
_FILENAME = r"[\w.-]+\.csv\b"


def _app_terms(text):
    # A shared input is evidence of compatibility, not of what the app does.
    lower = re.sub(_FILENAME, " ", text.casefold())
    terms = _terms(lower)
    terms.update(re.findall(r"\b(?:plot|graph|chart|compare|calculate|estimate)\b", lower))
    return terms


def _mentions(lower, value):
    return re.search(r"(?<!\w)" + re.escape(value.casefold()) + r"(?!\w)", lower)


def _named(lower, pool):
    return [a for a in pool if _mentions(lower, a["id"]) or _mentions(lower, a["title"])]


def _candidates(text, pool, kind):
    lower = text.casefold()
    named = _named(lower, pool)
    if named:
        return named
    extract = _app_terms if kind == "app" else _terms
    terms = extract(text)
    scored = [(len(terms & extract(a["title"])), a) for a in pool]
    best = max((n for n, _ in scored), default=0)
    if kind == "data":
        # A named file or weekday cannot silently resolve to a different acquisition.
        names = re.findall(_FILENAME, lower)
        days = set(re.findall(_DAY, lower))
        if names or days:
            return [a for a in pool if any(n == a["title"].casefold() for n in names) or
                    (not names and days.intersection(_terms(a["title"])))]
    if best:
        return [a for n, a in scored if n == best]
    # A generic reference such as "use our app" has no subject beyond the current project.
    if not terms:
        return pool
    return []


def _question(field, prompt, options):
    return {"question": prompt, "field": field, "options": [{"id": key, "title": title} for key, title in options]}


def _scientific_question(objective):
    lower = objective.strip().casefold()
    if re.match(r"(?:can|could|would|will) you\b|what (?:should|can) (?:i|we) do\b|how (?:do|should|can) (?:i|we)\b", lower):
        return False
    return bool(re.match(r"(?:does|do|did|is|are|was|were|has|have|what|when|where|why|how|which|whether|can|could|will|would)\b", lower))


_RELATIVE_DATA = r"\b(?:this|these|that|those|attached)\s+(?:data(?:sets?)?|files?|readings)\b"


def _dataset_groups(store, project, experiment, objective, pool, all_assets):
    lower = objective.casefold()
    labels = {value.casefold() for item in pool for value in (item["title"], item["id"]) if value.casefold() in lower}
    patterns = [re.escape(label) for label in sorted(labels, key=len, reverse=True)]
    if experiment:
        patterns.append(_RELATIVE_DATA)
    patterns.append(_FILENAME)
    if not labels and not re.search(_FILENAME, lower):
        patterns.append(_DAY)
    references = dict.fromkeys(re.findall(r"(?<!\w)(?:" + "|".join(patterns) + r")(?!\w)", lower))
    groups = []
    for label in references:
        if experiment and re.fullmatch(_RELATIVE_DATA, label):
            records, _ = research_experiments.project_records(store, project, all_assets)
            record = next(r for r in records if r["id"] == experiment)
            candidates = _current_project_resources([r for r in record["resources"] if r["kind"] == "data"])
            if not candidates and len(references) == 1:
                # With no attached input, a standalone reference retains the project-wide default.
                label, candidates = "", _candidates(objective, pool, "data")
        elif label in labels:
            candidates = [r for r in pool if label in (r["title"].casefold(), r["id"].casefold())]
        elif re.fullmatch(_DAY, label):
            candidates = [r for r in pool if label in _terms(r["title"])]
        else:
            candidates = []
        groups.append((label, candidates))
    return groups or [("", _candidates(objective, pool, "data"))]


def _dataset_selection(store, project, experiment, objective, pool, all_assets, choices):
    groups = _dataset_groups(store, project, experiment, objective, pool, all_assets)
    selected = []
    pending = {field: value for field, value in choices.items() if field == "data" or field.startswith("data:")}
    choice_number = 0
    for label, candidates in groups:
        if len(candidates) == 1 and len(groups) > 1:
            selected.append(candidates[0])
            continue
        choice_number += 1
        field = "data" if choice_number == 1 else f"data:{choice_number}"
        choice = pending.pop(field, None)
        if choice == "new":
            continue
        missing = bool(label and not candidates)
        options = pool if missing else candidates
        if choice:
            match = next((r for r in options if r["id"] == choice), None)
            if not match:
                raise WorkOrderError("The selected project record has changed. Submit the request again.")
            selected.append(match)
        elif len(candidates) == 1:
            selected.append(candidates[0])
        elif options or missing:
            subject = f" for ‘{label}’" if label else ""
            prompt = f"Which saved dataset should this investigation use{subject}?"
            if missing:
                prompt = f"The dataset for ‘{label}’ was not found. Which project file would you like to use?"
            answers = [(r["id"], r["title"] + " · " + r["id"]) for r in options]
            answers.append(("new", "Use another file later"))
            return [], _question(field, prompt, answers)
    if choice_number == 0 and "data" in pending:
        # A caller can explicitly opt out even when all references already resolve.
        choice = pending.pop("data")
        if choice == "new":
            selected = []
        elif not any(item["id"] == choice for item in selected):
            raise WorkOrderError("The selected project record has changed. Submit the request again.")
    if pending:
        raise WorkOrderError("The selected project record has changed. Submit the request again.")
    return _current_project_resources(selected), None


def resolve(store, actor, data):
    project, objective, choices = data.get("project_id"), data.get("objective"), data.get("choices", {})
    try:
        key = str(UUID(str(data.get("request_id"))))
    except ValueError:
        raise ContextError("Supply an investigation UUID.") from None
    if not isinstance(project, str) or not isinstance(objective, str) or not 0 < len(objective.strip()) <= 4000:
        raise ContextError("Choose a project and supply an objective up to 4000 characters.")
    if not isinstance(choices, dict) or not all(
            isinstance(field, str) and re.fullmatch(r"kind|procedure|app|data(?::(?:[2-9]|[1-9]\d+))?", field)
            and isinstance(value, str) for field, value in choices.items()):
        raise ContextError("Invalid investigation choices.")
    experiment = data.get("experiment_id")
    if ("experiment_id" in data and not isinstance(experiment, str)) or type(data.get("start_experiment", False)) is not bool:
        raise ContextError("Choose an experiment in the selected project.")
    sources = data.get("analysis_sources")
    if sources is not None and (not isinstance(sources, dict) or set(sources) != {
            "experiment_id", "experiment_revision", "lab_revision", "lab_document_ids", "experiment_document_ids"}
            or sources["experiment_id"] != project):
        raise ContextError("Choose analysis sources from the selected project.")
    skills = briefing.pin(data.get("skills"))
    stamp = canonical_digest(data)
    with store.transaction() as db:
        cached = db.execute("SELECT * FROM research_investigations WHERE id=?", (key,)).fetchone()
        if cached:
            if cached["actor"] != actor or cached["request_digest"] != stamp:
                raise WorkOrderError("This investigation ID was already used with different inputs.")
            link = db.execute("SELECT experiment_id FROM research_experiment_requests WHERE request_id=?", (key,)).fetchone()
            return {**json.loads(cached["result"]), "experiment_id": link["experiment_id"]}
        root, rev = research_experiments.check_project(store, project)
        if experiment is not None:
            research_experiments.owned(db, project, experiment)
        existing = db.execute("SELECT actor, request_digest FROM research_experiments WHERE id=?", (key,)).fetchone()
        recorded = {"id": key, "experiment_id": key, "recorded": True, "project_id": project}
        if existing:
            if existing["actor"] == actor and existing["request_digest"] == stamp:
                return recorded
            raise WorkOrderError("This ID was already used for another experiment.")
        all_assets = resources(store, project, include_history=True)
        assets = _current_project_resources(all_assets)
        kind = choices.get("kind") or intent(objective)
        if not kind:
            named_kinds = {"app" if a["kind"] == "data" else a["kind"] for a in _named(objective.casefold(), assets)}
            if len(named_kinds) == 1:
                kind = named_kinds.pop()
        if not kind and data.get("start_experiment") and not experiment and _scientific_question(objective):
            research_experiments.insert(db, key, project, research_experiments.short_title(objective), objective, actor, stamp)
            return recorded
        if not kind:
            return {**_question("kind", "What would you like to do in this project?", [
                ("app", "Analyze readings"), ("procedure", "Plan a measurement"), ("both", "Do both")]),
                "matches": [a for category in ("data", "procedure", "app")
                            for a in _candidates(objective, [a for a in assets if a["kind"] == category], category)]}
        if kind not in ("app", "procedure", "both"):
            raise ContextError("Choose an analysis app or procedure.")
        kinds = ["procedure", "app"] if kind == "both" else [kind]
        worker_draft = kind == "procedure" and re.search(r"\b(?:worker|agent)\b", objective, re.I) and re.search(r"\bdraft\b", objective, re.I)
        picked = {}
        datasets = []
        if "app" in kinds:
            datasets, question = _dataset_selection(store, project, experiment, objective,
                                                   [a for a in assets if a["kind"] == "data"], all_assets, choices)
            if question:
                return question
        categories = ["procedure", "app"] if "app" in kinds else ["procedure"]
        for category in categories:
            reference_only = category == "procedure" and category not in kinds
            pool = [a for a in assets if a["kind"] == category and a["status"] in ("ready", "released")]
            options = _candidates(objective, pool, category)
            if reference_only and not _terms(objective) and not re.search(_PROC, objective, re.I):
                options = []
            methods = {dataset.get("procedure_id") for dataset in datasets}
            source_procedure = next(iter(methods)) if len(methods) == 1 else None
            if reference_only and source_procedure and not options:
                options = [a for a in pool if a["id"] == source_procedure]
            if not options and not reference_only:
                options = [a for a in assets if a["kind"] == category and a["title"].casefold() == objective.casefold()]
            if category == "app" and len(datasets) > 1:
                digests = sorted(d["digest"] for d in datasets)
                options = [a for a in options if not a.get("tabular") and not a.get("dataset_digest")
                           and (not a.get("dataset_digests") or sorted(a["dataset_digests"]) == digests)]
            if category == "app" and len(datasets) == 1:
                dataset = datasets[0]
                applicable = [a for a in pool if (not a.get("tabular") or dataset["id"].startswith(a["id"] + "/"))
                              and not a.get("dataset_digests") and (not a.get("columns") or a["columns"] == dataset["columns"])]
                options = [a for a in options if a in applicable or a["status"] not in ("ready", "released")]
                if not options and not _app_terms(objective):
                    options = [a for a in applicable if dataset["id"].startswith(a["id"] + "/")
                               or a.get("dataset_digest") == dataset["digest"]]
            if category == "app" and "procedure" in picked:
                options = [a for a in options if not a.get("procedure_id") or a["procedure_id"] == picked["procedure"]["id"]]
            if worker_draft and category == "procedure":
                options = []
            if not reference_only and re.search(r"\b(?:brand[- ]new|create a new|build a new|draft a new)\b", objective, re.I):
                options = []
            choice = choices.get(category)
            weak_match = (len(options) == 1 and options[0]["id"] != source_procedure
                          and not _named(objective.casefold(), options)
                          and len(_terms(options[0]["title"]) & _terms(objective)) * 2 < len(_terms(objective)))
            if category == "app" and len(options) == 1:
                app = options[0]
                requested = _app_terms(objective)
                different_input = (len(datasets) == 1 and app.get("dataset_digest")
                                   and app["dataset_digest"] != datasets[0]["digest"])
                same_task = (objective.casefold() == app["title"].casefold()
                             or bool(requested and requested == _app_terms(app["title"])))
                weak_match = not _mentions(objective.casefold(), app["id"]) and (different_input or not same_task)
            if choice == "new":
                continue
            if choice:
                match = next((a for a in options if a["id"] == choice), None)
                if not match:
                    raise WorkOrderError("The selected project record has changed. Submit the request again.")
                picked[category] = match
            elif len(options) == 1 and not weak_match:
                picked[category] = options[0]
            elif options:
                prompt = {"procedure": "Which project procedure fits this request?",
                          "app": "Which project analysis app fits this request?"}[category]
                options = [(a["id"], a["title"] + " · " + a["id"]) for a in options]
                options.append(("new", "Continue without a procedure" if reference_only else "Create a new " + category))
                return _question(category, prompt, options)
        selected = [dict(dataset, reused=True) for dataset in datasets]
        if "procedure" in picked and "procedure" not in kinds:
            selected.append(dict(picked["procedure"], reused=True))
        child = None
        created = None
        for category in kinds:
            if category in picked:
                selected.append(dict(picked[category], reused=True))
                continue
            if created is None:
                lab, lab_revision = store.lab_for_experiment(root)
                created = lab, lab_revision, [lab.instrument(instrument_id) for instrument_id in root.instrument_ids]
            lab, lab_revision, instruments = created
            if category == "procedure":
                child = "investigation-" + key
                store.put_experiment(replace(root, id=child, title=objective, goal=objective), allow_unassigned=True)
                brief = briefing.build("procedure", skills, objective, instruments)
                entries = _library_entries(store, lab.id, brief, objective,
                                           {doc.id for doc in (*lab.documents, *root.documents)})
                if worker_draft:
                    order = procedure_drafts.create(store, child, actor)
                    texts.pin(store, order.id, entries)
                    selected.append(dict(kind=category, id=order.id, title=objective, status=order.status,
                                         automatic=False, reused=False))
                else:
                    draft = first_draft.start(store, actor, {"experiment_id": child, "request_id": "investigation-" + key},
                                              library_entries=entries)
                    selected.append(dict(kind=category, id=draft["order"]["id"], title=objective, status=draft["state"],
                                         automatic=True, reused=False))
                pinned = texts.pinned(store, selected[-1]["id"])
                brief = briefing.mark_pinned(brief, {p["source_id"]: p["document_id"] for p in pinned})
                briefing.save(store, selected[-1]["id"], brief)
                if brief:
                    selected[-1]["briefing"] = briefing.summary(brief)
                if pinned:
                    selected[-1]["library"] = pinned
            else:
                selection = sources if sources is not None else {
                    "experiment_id": project, "experiment_revision": rev.number, "lab_revision": lab_revision.number,
                    "experiment_document_ids": [doc.id for doc in root.documents],
                    "lab_document_ids": [doc.id for doc in lab.documents if _terms(doc.title) & _terms(objective)]}
                req = {"project": selection,
                       "objective": objective, "request_id": key}
                procedure = None
                if picked.get("procedure", {}).get("status") == "released":
                    procedure = tabular_service.procedure_pin(store, picked["procedure"]["id"])
                    release = WorkOrders(store).submission(procedure["order_id"], procedure["submission"])
                    procedure["instructions"] = render_artifact("procedure", release.artifact)
                prefix = (analysis_requests.PLOT_PREFIX if re.search(r"\b(?:stage drift|drift plot)\b", objective, re.I)
                          else analysis_requests.APP_PREFIX)
                brief = briefing.build("app", skills, objective, instruments)
                app = analysis_requests.create(store, actor, req, prefix, datasets=datasets, procedure=procedure, briefing=brief)
                selected.append(dict(kind=category, id=app["id"], title=objective, status="open", reused=False))
                if brief:
                    selected[-1]["briefing"] = briefing.summary(brief)
        if experiment is None:
            experiment = key
            research_experiments.insert(db, key, project, research_experiments.short_title(objective), objective, actor, stamp)
        result = {"id": key, "project_id": project, "experiment_id": experiment, "objective": objective, "resources": selected}
        db.execute("INSERT INTO research_investigations VALUES(?,?,?,?,?,?)",
                   (key, actor, stamp, project, child, canonical_json(result)))
        research_experiments.link_request(db, key, experiment)
        return result
