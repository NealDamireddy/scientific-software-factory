# Shared reference library: store source text once and pin it to work

## Why

The reference catalog holds titles, links and summaries, never the text of a manual or method. A
worker therefore cannot cite a library source; it can only ask the researcher to paste the passage.
The pasted text is saved inside one investigation's experiment record, so the next project (and the
next lab) has to paste it again. Nothing accumulates.

The target is a hosted service with separate accounts. Source text should live in the database once,
independent of any one user, and reach every piece of work that needs it without anyone repeating
themselves.

## Decisions already made by the product owner

- **Private until shared.** Text a researcher pastes inside a project is stored once in the library
  but is usable only by that project's lab until someone explicitly shares it. Text added through
  the Reference library screen is shared with everyone.
- This work goes on its own branch, stacked on the agent-briefing change.

## Goals

1. A library in the application database: each source's text is stored once (content-addressed),
   with append-only revisions per scope (`shared`, or one lab).
2. Library text is **pinned** to a procedure work order as ordinary documents, so every existing
   reader (worker context, passage retrieval, quote verification, citation checks, reviewers, the
   order detail page) treats it as citable evidence, and a released order stays reproducible after
   the library changes.
3. A new procedure investigation pins matching library text automatically: catalog sources the
   briefing matched that have text visible to the project's lab, and the lab's own contributed
   sources whose title matches the objective.
4. When a researcher answers a worker's source question, the text is also captured in the library
   for that lab, optionally attached to the catalog source the worker asked about.
5. People can add text to a source from the Reference library (shared), see what a lab holds, and
   share a lab-private entry with everyone.

## Non-goals

- Moving the catalog's metadata and search index into the database. The catalog stays packaged
  JSON; the database holds text, contributed sources and pins.
- Search over contributed (non-catalog) sources in the Reference library search box.
- Fetching text from publishers. People supply it.
- Accounts, lab membership or access control. "Lab-private" means the entry is used only for work in
  that lab and is listed under that lab; it is not an authorization boundary until accounts exist.
- Pinning library text to analysis apps and stage plots. They keep pointer-only references.
- A background job runner (the next piece of work).
- Removing the per-investigation copy of an answered source from the experiment record.

## Anti-goals

- **No project record ever stores library text.** Lab and experiment records, their digests and
  their revisions are untouched. Linked text appears only when an order's pinned context is read.
- **A pin never changes.** A pin names one immutable entry revision. Adding, revising or sharing
  text never alters what an existing order cites.
- **One lab's private text never reaches another lab's work**, and never appears in the shared
  listing, until it is shared.
- **The library never fails a request.** Linking and capture are best-effort: an error or an
  oversized text means nothing is pinned or captured, and the investigation or answer proceeds.
- **No behavior change while the library is empty.** With no text stored, every request stores and
  returns exactly what it does today.

## Approaches

1. **Pin entries per work order and resolve them where the pinned context is loaded (chosen).** A
   `work_order_library` table maps an order to entry revisions; `WorkOrders._context_for` prepends
   the resolved documents to the experiment's documents. One choke point, no change to stored
   records, and reproducibility comes from immutable entries.
2. Store link stubs in experiment records and hydrate them in `Store.get_experiment`. Rejected:
   several call sites read an experiment and write it back (`replace(root, ...)`, `add_source`),
   which would write the hydrated text into records and change their digests; SQL-level readers
   would see stubs.
3. Copy matched library text into each new investigation's experiment as documents. Rejected: it is
   the copying this work exists to stop.

## Design

**Tables.** `library_texts(digest, text)`; `library_entries(id, source_id, scope, revision, kind,
title, origin, text_digest, contributed_by, created_at)` unique on `(source_id, scope, revision)`;
`work_order_library(work_order_id, document_id, entry_id, position)`.

**Sources.** A catalog source keeps its catalog id; its kind maps to a document kind as reference
orders already do (`procedure` becomes `note`; `manual` and `paper` stay). A source outside the
catalog gets the id `contributed-` plus 16 hex characters derived from the lab and title, kind
`note`, and origin `Supplied by <name>`.

**Scopes.** `shared` or `lab:<lab id>`. For a lab, its own latest entry for a source wins over the
shared one. Sharing creates a `shared` revision that points at the same stored text.

**Documents.** A pinned entry appears as `Document(id="library:" + source_id, kind, title,
source=origin, text)`, placed before the experiment's own documents. A pinned document whose id
already exists on the lab or experiment is skipped.

**Limits.** Text is 1 byte to 256 KiB of UTF-8 with no NUL character. Titles are at most 250
characters. At most 8 documents are pinned to one order.

**Briefing.** A matched catalog finding that was pinned carries `document_id`. The worker
instruction becomes (exact): `The reference_library entry lists reference-library sources matched
to this objective. A finding with a document_id is pinned to this work order as that document: cite
it like any other pinned document. Every other finding is a pointer, not evidence: never quote or
cite it. When a needed method detail or instrument setting is missing from the pinned context, name
the matching source and its locator in your question so the researcher can supply the passage.`

**Consequence to know.** Where a source drafter is available, a procedure request with pinned text
goes to it instead of returning an immediate question, because the project now has documents. Where
none is (the hosted deployment today), the request keeps its immediate question and its pins, and the
text is used once a drafter exists.

## Left to the builder

Helper names inside modules, test structure, and the styling of the new workspace and portal
elements within the existing stylesheets.
