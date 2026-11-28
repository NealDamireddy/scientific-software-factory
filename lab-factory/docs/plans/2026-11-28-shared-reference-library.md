# Shared Reference Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store reference source text once in the application database, pin it to procedure work orders as citable documents, capture it when researchers supply it, and let people add and share it.

**Architecture:** A new `labfactory/library.py` owns three tables: content-addressed text, append-only entries per source and scope, and per-order pins. `WorkOrders._context_for` prepends an order's pinned entries to the experiment's documents, so every existing reader sees ordinary `Document` objects while stored lab and experiment records never change. `investigations.resolve` pins matching text when it creates a procedure; `procedure_drafts.add_source` captures answered text for the lab; `hosted.py` exposes list, read, add and share.

**Tech Stack:** Python 3.11+, SQLite through `labfactory.store.Store`, Starlette routes in `hosted.py`, pytest; Next.js 16 / React 19 / TypeScript in `reference-ui/`; plain ES modules in `lab-factory/public/`.

**Spec:** `lab-factory/docs/specs/2026-11-28-shared-reference-library-design.md`

## Global Constraints

- No new dependencies in `lab-factory/pyproject.toml` or any `package.json`.
- Backend commands run from `lab-factory/`: `uv run --locked pytest tests -q` (498 passed at baseline; every task ends with the whole suite green).
- Workspace commands run from `reference-ui/`: `npm run typecheck` and `node --experimental-strip-types --test app/*.test.mjs app/review-skills/*.test.mjs` (53 passed at baseline).
- No lab or experiment record ever stores library text: never pass a `Document` whose id starts with `library:` to `store.put_lab` or `store.put_experiment`.
- A pin names one immutable entry row. No code updates or deletes rows in `library_texts`, `library_entries` or `work_order_library`.
- One lab's `lab:<id>` entries are never pinned to another lab's order and never returned for another lab or in the shared listing.
- Linking and capture are best-effort: they never raise into `investigations.resolve` or `procedure_drafts.add_source`.
- With no rows in the library tables, every existing request stores and returns exactly what it does today.
- Exact values: document id prefix `library:`; shared scope `shared`; lab scope `lab:<lab id>`; contributed source id `contributed-` + 16 hex characters; text limit 256 KiB of UTF-8 (`MAX_TEXT_BYTES = 256 * 1024`); title limit 250 characters; at most 8 documents pinned per order (`MAX_PINNED = 8`).
- Match the surrounding code: compact modules, module-level functions, `store.connection.execute` for SQL, `ContextError` for bad input, `NotFound` for missing rows.
- End every commit message with these two lines:
  `Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>`
  `Claude-Session: https://claude.ai/code/session_012WxettJr7VWz4Cu9jtMkg1`

## Review Focus

1. A second lab must not receive the first lab's private text. Tests in Task 1 (`test_visible_prefers_the_labs_own_entry_and_hides_other_labs`) and Task 3 (`test_another_labs_private_text_is_not_pinned`).
2. An order released against pinned text must still verify after that source's text is revised or shared. Test in Task 2 (`test_pinned_text_is_unchanged_after_the_source_is_revised`).
3. Answering a worker's question on an order that has pinned documents must still identify the answer as the newest document. Test in Task 2 (`test_answer_document_is_still_last_when_library_documents_are_pinned`).
4. Text over 256 KiB, empty text, or text with a NUL character is rejected when added directly, and silently not captured when it arrives as an answer (the answer itself still succeeds). Tests in Task 1 (`test_add_rejects_bad_text`) and Task 4 (`test_oversized_answer_is_saved_but_not_captured`).
5. A pinned document id that collides with an existing lab or experiment document id must not make citations ambiguous. Test in Task 2 (`test_colliding_document_id_is_skipped`).

---

### Task 1: Library store

**Files:**
- Create: `lab-factory/src/labfactory/library.py`
- Modify: `lab-factory/src/labfactory/store.py` (`_SCHEMA`: three tables, after `work_order_briefings`)
- Test: `lab-factory/tests/test_library.py`

**Interfaces:**
- Consumes: `references.source(id) -> dict` (raises `ContextError("Unknown reference source")`; fields `kind` in `manual|procedure|paper`, `title`, `url`); `labfactory.context.ContextError`, `canonical_digest`; `labfactory.store.NotFound`.
- Produces (all in `labfactory/library.py`):
  - `PREFIX = "library:"`, `SHARED = "shared"`, `MAX_TEXT_BYTES = 256 * 1024`, `MAX_TITLE = 250`
  - `lab_scope(lab_id: str) -> str` returns `"lab:" + lab_id`
  - `add(store, actor: str, text: str, *, source_id: str | None = None, title: str | None = None, lab_id: str | None = None) -> dict`
  - `get(store, entry_id: int) -> dict` (entry plus `"text"`; raises `NotFound`)
  - `latest(store, lab_id: str | None = None) -> list[dict]`
  - `visible(store, lab_id: str | None, source_ids=None) -> dict[str, dict]`
  - `share(store, actor: str, entry_id: int) -> dict`
  - **Entry dict** (returned everywhere): `{"id": int, "source_id": str, "scope": str, "revision": int, "kind": str, "title": str, "origin": str, "digest": str, "bytes": int, "contributed_by": str, "created_at": str, "document_id": "library:" + source_id}`

- [ ] **Step 1: Write the failing tests** in `lab-factory/tests/test_library.py` (use the `store` fixture from `tests/conftest.py`)

- `test_add_shared_text_to_a_catalog_source`: `library.add(store, "Ana", "Set the wavelength to 550 nm.\nZero with the blank.", source_id="agilent-cary-60-user-guide")` returns an entry with `scope == "shared"`, `revision == 1`, `kind == "manual"`, the catalog title, `origin` equal to the catalog `url`, `document_id == "library:agilent-cary-60-user-guide"`, `bytes` equal to the UTF-8 length, `contributed_by == "Ana"`, a 64-hex `digest`; `library.get(store, entry["id"])["text"]` is the text; exactly one row in `library_texts`.
- `test_catalog_procedure_becomes_a_note`: adding text to `ihc-2009-honey-moisture` (a catalog `procedure`) gives `kind == "note"`.
- `test_same_text_is_stored_once_and_is_idempotent`: adding the same text twice to the same source and scope returns the same entry id and leaves one `library_entries` row; adding the same text to a second source leaves one `library_texts` row and two entries.
- `test_new_text_appends_a_revision_and_keeps_the_old_one`: a second, different text for the same source and scope returns `revision == 2`; `library.get` of the first id still returns the first text.
- `test_contributed_source_gets_a_stable_id`: `library.add(store, "Ana", "Weigh the boat.", title="Balance worksheet", lab_id="lab-a")` gives `source_id` matching `contributed-[0-9a-f]{16}`, `scope == "lab:lab-a"`, `kind == "note"`, `origin == "Supplied by Ana"`; adding a different text with the same title and lab (any letter case) revises the same `source_id`; the same title in `lab-b` gets a different `source_id`; passing that `source_id` explicitly with new text and no title revises it and keeps its title.
- `test_add_rejects_bad_text`: `ContextError` for `""`, `"   "`, text containing `"\x00"`, `"x" * (library.MAX_TEXT_BYTES + 1)`, a non-string; for no `source_id` and no title; for a title of 251 characters; for an unknown `source_id` such as `"nope"`. Nothing is stored after each.
- `test_visible_prefers_the_labs_own_entry_and_hides_other_labs`: with shared text S and lab-a text A on the same catalog source, plus lab-b text B on another source: `visible(store, "lab-a")` maps the first source to A's entry and has no key for B's source; `visible(store, "lab-b")` maps the first source to S's entry; `visible(store, None)` contains only shared entries; `visible(store, "lab-a", ["agilent-cary-60-user-guide"])` is limited to that id.
- `test_latest_lists_one_row_per_source_and_scope`: after two revisions of one shared source and one lab-a entry, `latest(store)` returns the newest shared row only; `latest(store, "lab-a")` returns the shared row and the lab-a row, ordered by title then scope; no entry dict has a `"text"` key.
- `test_share_points_at_the_same_text`: sharing a lab-a entry returns a `shared` entry with the same `source_id`, `digest`, `title`, `kind`, `origin`, `contributed_by` equal to the sharer; `library_texts` still has one row; sharing again returns the same shared entry; sharing an entry that is already `shared` returns it unchanged; an unknown id raises `NotFound`.

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd lab-factory && uv run --locked pytest tests/test_library.py -q`
Expected: collection error, `cannot import name 'library'`.

- [ ] **Step 3: Add the tables to `store._SCHEMA`** (keys `library_texts`, `library_entries`, `work_order_library`)

```sql
CREATE TABLE IF NOT EXISTS library_texts (digest TEXT PRIMARY KEY, text TEXT NOT NULL)

CREATE TABLE IF NOT EXISTS library_entries (
    id INTEGER PRIMARY KEY, source_id TEXT NOT NULL, scope TEXT NOT NULL, revision INTEGER NOT NULL,
    kind TEXT NOT NULL, title TEXT NOT NULL, origin TEXT NOT NULL,
    text_digest TEXT NOT NULL REFERENCES library_texts(digest), contributed_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE (source_id, scope, revision)
)

CREATE TABLE IF NOT EXISTS work_order_library (
    work_order_id TEXT NOT NULL REFERENCES work_orders(id), document_id TEXT NOT NULL,
    entry_id INTEGER NOT NULL REFERENCES library_entries(id), position INTEGER NOT NULL,
    PRIMARY KEY (work_order_id, document_id)
)
```

- [ ] **Step 4: Implement `labfactory/library.py`**

Module docstring: `"""Reference source text stored once, visible to everyone or to one lab, and pinned to work orders."""`

Rules the tests do not fully determine:
- The text digest is the SHA-256 hex of the UTF-8 text exactly as supplied (no stripping). `bytes` is that UTF-8 length.
- `add`: validate text first. Resolve the source in this order: a catalog id (`references.source`); else an existing entry with that `source_id` in any scope (inherit its `kind`, `title`, `origin`); else, when `source_id` is `None`, a title (stripped, 1–250 printable characters) giving `source_id = "contributed-" + canonical_digest([lab_id or "", title.casefold()])[:16]`, kind `note`, origin `"Supplied by " + actor`; anything else is `ContextError("Unknown library source.")`. For a catalog source the supplied title is ignored. Scope is `lab_scope(lab_id)` when `lab_id` is given, else `SHARED`. If the newest entry for `(source_id, scope)` has the same digest, return it; otherwise insert revision `max + 1`.
- Run each write inside `store.transaction()`.
- `visible`: for each source, the newest entry in `lab_scope(lab_id)` if one exists, else the newest `shared` entry.
- `share`: for a lab-scope entry, if the newest shared entry for that source has the same `text_digest` return it; otherwise insert a new shared revision reusing `text_digest`, `kind`, `title`, `origin`.

- [ ] **Step 5: Run the tests and the whole suite**

Run: `cd lab-factory && uv run --locked pytest tests/test_library.py -q && uv run --locked pytest tests -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add lab-factory/src/labfactory/library.py lab-factory/src/labfactory/store.py lab-factory/tests/test_library.py
git commit -m "Store reference source text once with shared and lab-private revisions"
```

---

### Task 2: Pin library text to work orders as citable documents

**Files:**
- Modify: `lab-factory/src/labfactory/library.py` (add `MAX_PINNED`, `pin`, `pinned`, `copy`, `documents`)
- Modify: `lab-factory/src/labfactory/workorders.py` (`_context_for`)
- Modify: `lab-factory/src/labfactory/procedure_drafts.py` (`create`: carry pins to a follow-up)
- Test: `lab-factory/tests/test_library_pins.py`

**Interfaces:**
- Consumes (Task 1): `library.add`, `library.get`, entry dicts, `library.PREFIX`.
- Produces:
  - `library.MAX_PINNED = 8`
  - `library.pin(store, work_order_id: str, entries: list[dict]) -> list[dict]` — pins up to `MAX_PINNED` entries in order, skipping a `document_id` already pinned to that order; returns the summaries of what is now pinned.
  - `library.pinned(store, work_order_id: str) -> list[dict]` — summaries in position order: `{"document_id": str, "source_id": str, "title": str, "scope": "shared" | "lab", "entry_id": int, "revision": int}`.
  - `library.copy(store, source_order_id: str, target_order_id: str) -> None`
  - `library.documents(store, work_order_id: str) -> tuple[Document, ...]` — `Document(id=document_id, kind, title, source=origin, text)` in position order.
  - `WorkOrders.pinned_context(id)` returns the experiment with pinned library documents placed **before** its own documents.

- [ ] **Step 1: Write the failing tests** in `lab-factory/tests/test_library_pins.py`

Build orders the way `tests/test_procedure_drafts.py` and `tests/test_first_draft.py` do (read them for the lab, experiment and draft helpers). Tests:

- `test_pinned_entries_appear_before_the_experiments_own_documents`: an experiment with one document `own`; pin a shared entry on `agilent-cary-60-user-guide`; `WorkOrders(store).pinned_context(order.id)[1].documents` ids are `["library:agilent-cary-60-user-guide", "own"]`, the library document's `kind`, `title`, `source` and `text` match the entry; `store.get_experiment(experiment_id)[0].documents` ids are still `["own"]` and the stored experiment revision digest is unchanged.
- `test_order_without_pins_is_unchanged`: `pinned_context` returns objects equal to `store.get_lab(...)[0]` and `store.get_experiment(...)[0]` at the pinned revisions.
- `test_pinned_text_is_unchanged_after_the_source_is_revised`: pin revision 1, then `library.add` a different text for the same source and `library.share` where applicable; `pinned_context` still returns revision 1's text and `library.pinned(store, order.id)[0]["revision"] == 1`.
- `test_pinned_document_can_be_cited_and_quoted`: for a procedure draft order with a pinned entry whose text contains `"Set the wavelength to 550 nm."`, a candidate artifact with one step citing `library:agilent-cary-60-user-guide` and evidence `{"document": "library:agilent-cary-60-user-guide", "passage": 1, "quote": "Set the wavelength to 550 nm."}` passes `procedure_drafts.evidence_checks(artifact, lab, exp, required=True)` using the lab and experiment from `pinned_context`; `procedure_drafts.passages(lab, exp)` includes a passage for that document; `AgentTools(store).get_work_order_context(order.id)` lists the document under `experiment.documents` and returns it in `passages` for a matching `query`.
- `test_colliding_document_id_is_skipped`: when the experiment already has a document with id `library:agilent-cary-60-user-guide`, `pinned_context` returns exactly one document with that id (the experiment's own) and `CitationIndex(lab, exp).resolve(...)` does not raise.
- `test_pin_is_capped_deduplicated_and_ordered`: pinning 10 entries pins the first 8 in order; pinning an entry whose `document_id` is already pinned leaves the original pin; `library.pinned` returns positions in order with `scope` reported as `"shared"` or `"lab"`.
- `test_follow_up_order_keeps_its_pins`: `procedure_drafts.create(store, experiment_id, "Reviewer", previous=first.id)` gives an order whose `library.pinned` equals the first order's.
- `test_answer_document_is_still_last_when_library_documents_are_pinned`: on a needs-input draft that has a pinned library document, `procedure_drafts.add_source(store, order_id, "Reviewer", "Method note", "Read the mass.")` creates a follow-up whose `pinned_context(new_id)[1].documents[-1].title == "Method note"`, whose first document is the library document, and whose stored experiment record contains no document id starting with `library:`.

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd lab-factory && uv run --locked pytest tests/test_library_pins.py -q`
Expected: `AttributeError: module 'labfactory.library' has no attribute 'pin'`.

- [ ] **Step 3: Implement `pin`, `pinned`, `copy`, `documents` in `library.py`**

`pin` assigns `position` continuing from the order's current maximum and stops at `MAX_PINNED` total. `copy` uses `INSERT OR IGNORE ... SELECT` preserving positions. `documents` joins `work_order_library`, `library_entries` and `library_texts`.

- [ ] **Step 4: Resolve pins in `WorkOrders._context_for`**

After loading `lab` and `experiment`: `linked = library.documents(self.store, order.id)`; drop any whose id is already used by a lab or experiment document; when any remain, return `lab, dataclasses.replace(experiment, documents=(*linked, *experiment.documents))`; otherwise return the two objects unchanged.

- [ ] **Step 5: Carry pins to follow-up orders**

In `procedure_drafts.create`, next to the existing `briefing.copy(store, previous, order.id)`, call `library.copy(store, previous, order.id)`.

- [ ] **Step 6: Run the tests and the whole suite**

Run: `cd lab-factory && uv run --locked pytest tests/test_library_pins.py -q && uv run --locked pytest tests -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add lab-factory/src/labfactory/library.py lab-factory/src/labfactory/workorders.py lab-factory/src/labfactory/procedure_drafts.py lab-factory/tests/test_library_pins.py
git commit -m "Pin library text to work orders and resolve it as citable documents"
```

---

### Task 3: Pin matching library text when an investigation creates a procedure

**Files:**
- Modify: `lab-factory/src/labfactory/briefing.py` (`REFERENCES_INSTRUCTION`, `mark_pinned`, `summary`)
- Modify: `lab-factory/src/labfactory/first_draft.py` (`start`: keyword `library_entries`)
- Modify: `lab-factory/src/labfactory/investigations.py` (`resolve`, procedure branch; helper `_library_entries`)
- Test: `lab-factory/tests/test_investigations.py` (extend), `lab-factory/tests/test_briefing.py` (extend)

**Interfaces:**
- Consumes: `library.visible`, `library.pin`, `library.pinned` (Tasks 1–2); `briefing.build`, `briefing.save`, `briefing.summary`; `investigations._terms`.
- Produces:
  - `briefing.mark_pinned(briefing: dict | None, document_ids: dict[str, str]) -> dict | None` — returns a copy in which each `reference_library` finding whose `id` is a key gains `"document_id"`; the input is not mutated; `None` and briefings without `reference_library` are returned unchanged.
  - `briefing.summary(...)["references"]` items include `"document_id"` when the finding has one.
  - `first_draft.start(store, actor, data, *, library_entries=())` pins those entries to the new order **after** `procedure_drafts.create` and **before** `_compile`.
  - A newly created procedure resource carries `"library": library.pinned(...)` (the summary list) when anything was pinned; reused resources and app resources never do.

- [ ] **Step 1: Write the failing tests**

In `tests/test_briefing.py`:
- `test_mark_pinned_flags_findings_without_mutating`: for a built briefing with two findings, `mark_pinned(b, {first_id: "library:" + first_id})` returns a new dict whose first finding has `document_id` and whose second does not; `b` is unchanged; `summary(marked)["references"][0]["document_id"]` is set and the second item has no such key; `mark_pinned(None, {...}) is None`.
- `test_reference_instruction_explains_pinned_findings`: `briefing.REFERENCES_INSTRUCTION` equals the exact text in the spec's Design section.

In `tests/test_investigations.py` (register projects with `investigations.register`; read the lab id from `store.get_experiment(project_id)[0].lab_id`):
- `test_new_procedure_pins_shared_text_for_a_matched_source`: add shared text to `agilent-cary-60-user-guide`; resolve `"Check wavelength accuracy on the Agilent Cary 60"` with `kind="procedure"`. The resource has `library == [{"document_id": "library:agilent-cary-60-user-guide", "source_id": "agilent-cary-60-user-guide", "title": <catalog title>, "scope": "shared", "entry_id": <id>, "revision": 1}]`; its `briefing["references"]` item for that source has `document_id`; `briefing.load(store, order_id)["reference_library"]["findings"]` has `document_id` on that finding only; `WorkOrders(store).pinned_context(order_id)[1].documents[0].id == "library:agilent-cary-60-user-guide"`; the resource `status == "drafting"` (documents now exist, so the source drafter is registered); the child experiment record has `documents == ()`.
- `test_new_procedure_pins_the_labs_own_contributed_text`: add lab-scope text titled `"Archive balance worksheet"` for the project's lab; resolve `"Draft a procedure to weigh samples with the archive balance worksheet"`; the resource's `library` has one item with `scope == "lab"` and a `document_id` starting `library:contributed-`.
- `test_contributed_text_needs_two_matching_title_terms`: the same entry is not pinned for the objective `"Draft a procedure for the balance"` (one shared term).
- `test_another_labs_private_text_is_not_pinned`: lab-scope text on `agilent-cary-60-user-guide` for a different lab id is not pinned for this project; the resource has no `library` key and `status == "needs_input"`.
- `test_no_library_text_leaves_the_investigation_unchanged`: with empty library tables, resolving the Cary objective returns a resource with no `library` key, `status == "needs_input"`, and no finding with `document_id`.
- `test_library_failure_does_not_fail_the_investigation`: with `library.visible` monkeypatched to raise `sqlite3.OperationalError`, the investigation is still created with no `library` key.
- `test_new_app_never_pins_library_text`: with shared text on a matched honey source, an app investigation's resource has no `library` key and no `document_id` in its briefing references.

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd lab-factory && uv run --locked pytest tests/test_investigations.py tests/test_briefing.py -q`
Expected: the new tests fail.

- [ ] **Step 3: Update `briefing.py`**

Replace `REFERENCES_INSTRUCTION` with the exact text from the spec. Add `mark_pinned`. In `summary`, copy `document_id` onto a reference item when the finding has it.

- [ ] **Step 4: Add `library_entries` to `first_draft.start`**

Keyword-only, default `()`. Pin with `library.pin(store, order.id, list(library_entries))` right after `procedure_drafts.create(...)` and before `_compile(...)`. Do not include it in the request fingerprint.

- [ ] **Step 5: Link in `investigations.resolve`**

Add `_library_entries(store, lab_id, brief, objective) -> list[dict]`:
1. Catalog matches: for the ids of `brief["reference_library"]["findings"]` (when present), in that order, the entries from `library.visible(store, lab_id, ids)`.
2. Contributed matches: entries from `library.visible(store, lab_id)` whose `source_id` starts with `contributed-` and whose title shares at least 2 terms with the objective under `_terms`; ranked by shared-term count descending, then title; at most 3.
3. Catalog matches first, at most `library.MAX_PINNED` in total. Any exception (`Exception`) returns `[]`.

In the procedure branch: build `brief` as today, compute `entries = _library_entries(store, lab.id, brief, objective)`, then `brief = briefing.mark_pinned(brief, {e["source_id"]: e["document_id"] for e in entries})`. For the automatic path pass `library_entries=entries` to `first_draft.start`; for the worker-draft path call `library.pin(store, order.id, entries)` right after `procedure_drafts.create`. Then save the briefing and add its summary as today, and add `library=library.pinned(store, order_id)` to the resource when that list is not empty. The app branch is unchanged.

- [ ] **Step 6: Run the tests and the whole suite**

Run: `cd lab-factory && uv run --locked pytest tests/test_investigations.py tests/test_briefing.py tests/test_briefing_delivery.py -q && uv run --locked pytest tests -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add lab-factory/src/labfactory/briefing.py lab-factory/src/labfactory/first_draft.py lab-factory/src/labfactory/investigations.py lab-factory/tests/test_investigations.py lab-factory/tests/test_briefing.py
git commit -m "Pin matching library text when an investigation creates a procedure"
```

---

### Task 4: Capture answered source text in the library

**Files:**
- Modify: `lab-factory/src/labfactory/procedure_drafts.py` (`add_source`)
- Modify: `lab-factory/src/labfactory/first_draft.py` (`answer`, `detail`)
- Modify: `lab-factory/src/labfactory/hosted.py` (`procedure_source`)
- Test: `lab-factory/tests/test_library_capture.py`

**Interfaces:**
- Consumes: `library.add`, `library.latest`, `library.MAX_TEXT_BYTES`; `briefing.load`.
- Produces:
  - `procedure_drafts.add_source(store, order_id, reviewer, title, text, source_id=None) -> str` — unchanged result; additionally captures the text as a `lab:<order.lab_id>` library entry.
  - `first_draft.answer` accepts the key sets `{title, text}`, `{title, text, source_id}` and `{method_id}` (each plus optional `request_id`).
  - `POST /api/procedures/{id}/source` forwards an optional `source_id`.
  - `first_draft.detail(...)["suggested_sources"]`: `[{"id", "title", "locator"}]` for the order's briefing findings that have no `document_id`; `[]` when there is no briefing.

- [ ] **Step 1: Write the failing tests** in `lab-factory/tests/test_library_capture.py`

Use the needs-input draft setup from `tests/test_procedure_drafts.py` / `tests/test_first_draft.py`.
- `test_answer_is_captured_for_the_orders_lab`: after `add_source(store, order_id, "Reviewer", "Balance worksheet", "Read the mass.")`, `library.latest(store, lab_id)` has one `lab:<lab_id>` entry titled `"Balance worksheet"` with `contributed_by == "Reviewer"`; `library.latest(store)` (shared) is empty; the follow-up order's experiment still contains the `method-…` document exactly as before and the follow-up has no pins.
- `test_answer_can_name_the_catalog_source_it_comes_from`: with `source_id="agilent-cary-60-user-guide"` the lab entry has that `source_id`, the catalog title and `kind == "manual"`; the experiment document keeps the title the researcher typed.
- `test_unknown_source_id_is_rejected_before_anything_is_saved`: `source_id="nope"` raises `ContextError`; no follow-up order and no library rows exist.
- `test_oversized_answer_is_saved_but_not_captured`: text of `library.MAX_TEXT_BYTES + 1` bytes creates the follow-up order as today and stores no library rows.
- `test_capture_failure_does_not_fail_the_answer`: with `library.add` monkeypatched to raise `sqlite3.OperationalError`, `add_source` still returns the new order id.
- `test_demo_answers_are_not_captured`: an answer on a demo draft (`procedure_demo.start`) stores no library rows.
- `test_first_draft_answer_accepts_a_source_id`: `first_draft.answer(store, "Reviewer", order_id, {"title": "T", "text": "Read the mass.", "source_id": "agilent-cary-60-user-guide", "request_id": "r1"})` succeeds and captures under that source; `{"title": "T", "text": "x", "method_id": "m"}` still raises `ContextError`.
- `test_detail_lists_unpinned_suggested_sources`: for an order whose saved briefing has two findings, one with `document_id`, `first_draft.detail(store, order_id)["suggested_sources"]` is the other one as `{"id", "title", "locator"}`; an order with no briefing gives `[]`.
- `test_source_route_forwards_source_id`: following the HTTP client setup in `tests/test_hosted_portal.py`, `POST /api/procedures/{id}/source` with `{"title", "text", "source_id": "agilent-cary-60-user-guide"}` returns 201 and the lab entry exists; with `"source_id": "nope"` it returns 400.

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd lab-factory && uv run --locked pytest tests/test_library_capture.py -q`
Expected: failures on the missing parameter and key.

- [ ] **Step 3: Capture in `add_source`**

Validate a supplied `source_id` first: it must be a string that `references.source` accepts or that already exists in `library_entries`; otherwise `ContextError("Unknown library source.")` before any write. After the follow-up order is created, and only when the draft is not a demo and the UTF-8 text is at most `library.MAX_TEXT_BYTES`, call `library.add(store, reviewer, text.strip(), source_id=source_id, title=title.strip(), lab_id=order.lab_id)` inside a `try` that swallows `Exception`. The experiment document and the returned id are exactly as today.

- [ ] **Step 4: Thread `source_id` through `first_draft.answer` and the route; add `suggested_sources` to `detail`**

`answer`: allow `source_id` only together with `title` and `text`; pass it to `procedure_drafts.add_source`. `procedure_source`: pass `data.get("source_id")`. `detail`: add `"suggested_sources"` from `briefing.load(store, order_id)`.

- [ ] **Step 5: Run the tests and the whole suite**

Run: `cd lab-factory && uv run --locked pytest tests/test_library_capture.py -q && uv run --locked pytest tests -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add lab-factory/src/labfactory/procedure_drafts.py lab-factory/src/labfactory/first_draft.py lab-factory/src/labfactory/hosted.py lab-factory/tests/test_library_capture.py
git commit -m "Capture answered source text in the lab's library"
```

---

### Task 5: Library API

**Files:**
- Modify: `lab-factory/src/labfactory/hosted.py` (handlers `library_entries`, `library_entry`, `library_share`; routes; `reference_search` annotation; CORS path list)
- Modify: `lab-factory/docs/hosted.md`
- Test: `lab-factory/tests/test_library_api.py`

**Interfaces:**
- Consumes: `library.latest`, `library.get`, `library.add`, `library.share`, `library.visible` (Task 1).
- Produces (every route requires a signed-in reviewer, as the other `/api` routes do; POSTs go through `_json_body`):
  - `GET /api/library` → `{"entries": [...]}` shared entries; `GET /api/library?lab_id=<id>` → shared plus that lab's entries. No entry carries `text`.
  - `GET /api/library/{entry_id}` → the entry with `text`; 404 for an unknown or non-integer id.
  - `POST /api/library` with exactly `{"text"}` plus any of `source_id`, `title`, `lab_id` → 201 and the entry. With `lab_id` the entry is lab-scoped; without it, shared. Any other key → 400.
  - `POST /api/library/{entry_id}/share` with `{}` → 200 and the shared entry.
  - `GET /api/references/search` findings gain `"library_text": true` for a source that has **shared** text; findings without shared text are unchanged (no key).

- [ ] **Step 1: Write the failing tests** in `lab-factory/tests/test_library_api.py`

Follow `tests/test_hosted_portal.py` for the app, client, origin header and reviewer session.
- `test_library_requires_a_reviewer`: each of the four routes returns 401 without a session.
- `test_add_list_read_and_share_over_http`: POST shared text to `agilent-cary-60-user-guide` → 201 with `scope == "shared"`; POST `{"text", "title": "Balance worksheet", "lab_id": "lab-a"}` → 201 with `scope == "lab:lab-a"`; `GET /api/library` lists only the shared entry and no `text`; `GET /api/library?lab_id=lab-a` lists both; `GET /api/library?lab_id=lab-b` lists only the shared entry; `GET /api/library/{id}` returns the text; `POST /api/library/{lab entry id}/share` returns a shared entry with the same `digest`, after which `GET /api/library` lists two entries.
- `test_bad_requests_are_rejected`: empty text, text over the limit, an extra key, an unknown `source_id` → 400; `GET /api/library/999` and `GET /api/library/abc` → 404; a POST with a foreign `Origin` → 403.
- `test_search_marks_sources_with_shared_text`: before any text, no finding of `GET /api/references/search?instrument=agilent-cary-60&q=Check%20wavelength%20accuracy` has `library_text`; after adding shared text to `agilent-cary-60-user-guide` that finding has `library_text is True` and the others have no such key; lab-scoped text alone does not set it; the response's `catalog_digest` and each finding's `digest` are unchanged.

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd lab-factory && uv run --locked pytest tests/test_library_api.py -q`
Expected: 404s for the new routes.

- [ ] **Step 3: Implement the handlers and routes**

Use `run_store(..., write=True)` for the two POSTs. Register the routes beside the reference routes. Add `/api/library` to the research-origin CORS path list next to `/api/research-projects`. In `reference_search`, after `references.search`, read `library.visible(store, None, ids)` in a store read and set `library_text` on matching findings (copy the finding dicts; do not mutate the index's objects).

- [ ] **Step 4: Document storage**

In `lab-factory/docs/hosted.md`, in the section that describes the reference library, add a paragraph: source text is stored in the application database (`library_texts`, `library_entries`), shared or per lab; each text is at most 256 KiB; the Vercel Blob backend's 8 MiB limit covers the whole database including this text, so use Turso for a library of any size; "lab-private" is a usage scope, not access control, until accounts exist.

- [ ] **Step 5: Run the tests and the whole suite**

Run: `cd lab-factory && uv run --locked pytest tests/test_library_api.py -q && uv run --locked pytest tests -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add lab-factory/src/labfactory/hosted.py lab-factory/docs/hosted.md lab-factory/tests/test_library_api.py
git commit -m "Serve the reference library: list, read, add and share source text"
```

---

### Task 6: Workspace: show pinned text, attribute answers, share from the lab library

**Files:**
- Modify: `reference-ui/app/project-investigations.tsx` (`Resource` type, briefing block, new `LabLibrary` section under "Registered lab context")
- Modify: `reference-ui/app/research-workflows.tsx` (`DraftDetail` answer form)
- Modify: `reference-ui/app/research-api.ts` (types)
- Create: `reference-ui/app/library-model.ts`, `reference-ui/app/library-model.test.mjs`
- Modify: `reference-ui/app/research-workflows.css`
- Modify: `reference-ui/README.md`

**Interfaces:**
- Consumes: resource `library: {document_id, source_id, title, scope: "shared" | "lab", entry_id, revision}[]`; `briefing.references[].document_id?`; `GET /api/procedure-drafts/{id}` → `suggested_sources: {id, title, locator}[]`; `POST /api/procedure-drafts/{id}/answers` accepts `source_id`; `GET /api/library?lab_id=`, `POST /api/library/{id}/share`.
- Produces (`library-model.ts`, pure functions):
  - `export type LibraryEntry = { id: number; source_id: string; scope: string; revision: number; kind: string; title: string; origin: string; digest: string; bytes: number; contributed_by: string; created_at: string; document_id: string }`
  - `scopeLabel(scope: string): string` → `"Shared with all labs"` for `shared`, `"This lab only"` otherwise.
  - `shareable(entry: LibraryEntry, entries: LibraryEntry[]): boolean` → true for a lab-scope entry unless a `shared` entry with the same `source_id` and `digest` exists.
  - `formatBytes(bytes: number): string` → `"812 B"`, `"1.5 KB"`, `"256 KB"` (1024 base, one decimal below 10 KB, none above).

- [ ] **Step 1: Write the failing test** `reference-ui/app/library-model.test.mjs`

Assert: `scopeLabel("shared") === "Shared with all labs"`, `scopeLabel("lab:x") === "This lab only"`; `shareable` is true for a lab entry alone, false for a shared entry, false for a lab entry when a shared entry has the same `source_id` and `digest`, true when the shared entry has a different `digest`; `formatBytes(812) === "812 B"`, `formatBytes(1536) === "1.5 KB"`, `formatBytes(262144) === "256 KB"`.

- [ ] **Step 2: Run it and confirm it fails**

Run: `cd reference-ui && node --experimental-strip-types --test app/library-model.test.mjs`
Expected: FAIL, module not found.

- [ ] **Step 3: Implement `library-model.ts`**

- [ ] **Step 4: Show pinned text in the Agent briefing block** (`project-investigations.tsx`)

Extend `Resource` with `library?: {document_id: string; source_id: string; title: string; scope: "shared" | "lab"; entry_id: number; revision: number}[]` and `briefing.references[].document_id?: string`. Render the block when the resource has a `briefing` **or** a non-empty `library`. Inside it:
- after the instrument line, when `library` is non-empty: a heading `Pinned library text` and a list; each item is the title followed by ` · ` and `Shared with all labs` or `This lab only`.
- in `Suggested sources`, a source whose reference has `document_id` is followed by ` · pinned as text`.
- the closing note changes to (exact): `Pinned library text can be cited. Other suggested sources are pointers until their text is added to the library.` Show the note only when there are suggested sources or pinned text.

Carry `library` through wherever the merged code copies `briefing` from a request's resources onto an attached-work item (the `briefings` map in `ExperimentRecord`).

- [ ] **Step 5: Let a researcher say which source an answer comes from** (`research-workflows.tsx`)

In `DraftDetail`'s title-and-text answer form, when `data.suggested_sources` is non-empty, add a `<select>` labelled `This text comes from` with a first option `Another source` (value `""`) and one option per suggested source showing `title · locator`. When a source is chosen, include `source_id` in the POST body. Add `suggested_sources?: {id: string; title: string; locator: string}[]` to the `Procedure` type in `research-api.ts`.

- [ ] **Step 6: Lab library section** (`project-investigations.tsx`)

Under "Registered lab context", add a section headed `Lab library` that reads `GET library?lab_id=<context.lab.id>` and lists each entry: title, `scopeLabel(scope)`, `formatBytes(bytes)`, `contributed_by`, revision. For an entry where `shareable(...)` is true show a button `Share with all labs`; on click, confirm with `window.confirm("Share “<title>” with every lab? This cannot be undone.")`, then POST `library/<id>/share` and refresh the list. Empty state (exact): `No source text yet. Text you supply when a worker asks for a source is kept here for this lab.` Add `id` to the `Inventory` lab type if it is missing.

- [ ] **Step 7: Document it** (`reference-ui/README.md`)

In the investigation section, replace the sentence saying suggested sources cannot be cited with: text added to the reference library is pinned to new procedure work and can be cited; text you supply in answer to a worker's source question is kept for your lab and reused on later work; **Lab library** in a project's registered lab context lists it and lets you share an entry with all labs; sharing cannot be undone.

- [ ] **Step 8: Verify**

Run: `cd reference-ui && npm run typecheck && node --experimental-strip-types --test app/*.test.mjs app/review-skills/*.test.mjs`
Expected: typecheck clean; all tests pass.

- [ ] **Step 9: Commit**

```bash
git add reference-ui/app/project-investigations.tsx reference-ui/app/research-workflows.tsx reference-ui/app/research-api.ts reference-ui/app/library-model.ts reference-ui/app/library-model.test.mjs reference-ui/app/research-workflows.css reference-ui/README.md
git commit -m "Show pinned library text, attribute answers to sources and share from the lab library"
```

---

### Task 7: Reference library screen: mark sources with text and add shared text

**Files:**
- Modify: `lab-factory/public/app.js` (Reference library view)
- Modify: `lab-factory/public/style.css` (only if a new class is needed)
- Modify: `lab-factory/README.md`
- Test: `lab-factory/tests/test_hosted_portal.py` (extend, if it already asserts on served portal assets)

**Interfaces:**
- Consumes: `GET /api/references/search` findings with optional `library_text: true`; `POST /api/library` with `{source_id, text}` (shared); `GET /api/library` (to find a source's shared entry) and `GET /api/library/{id}` (to prefill its text).

- [ ] **Step 1: Read the view**

Read `showReferenceLibrary` and the helpers it uses to render a source (`sourceGroups` and whatever renders one finding) in `lab-factory/public/app.js`, and how other forms in this file post JSON and show errors (`api`, `handleForm`, `formError`, `element`, `button`). Follow those helpers; add no new patterns.

- [ ] **Step 2: Mark sources that have text**

Where one finding is rendered, when `finding.library_text` is true add a short status label with the exact text `Text in library`.

- [ ] **Step 3: Add or revise shared text**

Under each rendered finding add a collapsed `<details>` with summary `Add source text` (or `Revise source text` when `library_text` is true). Inside: a `<textarea>` labelled `Source text` (required), a note with the exact text `Shared with every lab. Workers can cite it on new procedure work. Paste only text you may share.`, and a submit button `Save to library`. For a source that already has text, opening the details loads the current shared text into the textarea (find the entry for this `source_id` in `GET library`, then `GET library/<id>`). On submit POST `{source_id, text}` to `library`; on success rerun the current search so the label updates; on failure show the error with the file's existing form-error helper.

- [ ] **Step 4: Document it** (`lab-factory/README.md`, section "Find evidence for an experiment" or the nearest reference-library section)

Add: a source marked **Text in library** has shared text; **Add source text** stores text for a source once for every lab; new procedure work whose objective matches the source gets that text pinned as a citable document; pinned text never changes after the fact, and revising a source affects new work only.

- [ ] **Step 5: Verify**

Run: `cd lab-factory && uv run --locked pytest tests -q`
Expected: all pass. If `tests/test_hosted_portal.py` asserts on strings served from `public/app.js`, add an assertion that the served script contains `Text in library` and `Save to library`.
Run: `node --check lab-factory/public/app.js` from the repository root.
Expected: no output (the module parses).

- [ ] **Step 6: Commit**

```bash
git add lab-factory/public/app.js lab-factory/public/style.css lab-factory/README.md lab-factory/tests/test_hosted_portal.py
git commit -m "Mark sources that have library text and add shared text from the reference screen"
```
