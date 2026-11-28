# Agent briefing: deliver skills and library references with every investigation

## Why

An audit of the research workspace found that most of what the lab has built never reaches the
workers that do the work:

- Research skills reach a worker only from the tabular intake form (behind a checkbox that is off by
  default) and from the simulated experiment review. Procedure drafts, offline analysis apps, stage
  plots and connected MCP agents receive none.
- The packaged reference library (32 instrument models, 89 manuals, procedures and papers) is
  consulted only when a person opens the Reference library screen. An investigation never looks it up.
- A project created in the research workspace has no instruments, so nothing ties its objective to an
  instrument model or its manual.

This change makes every investigation carry an **agent briefing**: the enabled research skills that
fit the kind of work, and the reference-library sources matched to the objective and instruments.

## Goals

1. An investigation request may carry the workspace's enabled skills. The backend pins them
   (SHA-256 version per skill, existing `pin_skills` limits) and delivers the ones that fit the work
   to its author: `start` skills to procedure authors; `result` and `repeat` skills to analysis-app
   and stage-plot authors; skills without a stage to both.
2. Every investigation that creates new work looks up the reference library automatically, scoped
   to a catalog instrument model when exactly one is named in the objective or assigned to the
   project, and attaches up to five matched sources.
3. The briefing reaches every author: the backend source drafter, the offline-app and stage-plot
   workers, and any MCP agent that reads the work-order context. A follow-up order created after a
   researcher answers a question keeps the briefing of the order it supersedes.
4. The researcher can see what was attached: each new resource in an investigation result lists the
   skill names and versions and the suggested sources.
5. The tabular intake form attaches enabled skills by default, and an MCP agent on a tabular order is
   told to apply them.

## Non-goals

- Storing skills, instruments or knowledge on the server. They stay in the browser until accounts
  exist (hosted, multi-user is the target; that is separate work).
- A shared reference database with document text. Library records hold a title, link, locator and
  summary only.
- A background job runner. Drafting still runs where it runs today.
- Connectors.
- Giving skills to the reviewer workers (decision evidence, paper review).
- Checking that a worker's output reflects a skill.

## Anti-goals

- **A library source must never become evidence.** Library records are summaries written by an
  editor, not source text. They are never added as lab or experiment documents, never citable, and
  never reach the quote-verification checks. The worker is told they are pointers: when a method
  detail is missing it should name the matching source and locator in its question, so the
  researcher can supply the passage.
- **The briefing must not weaken independent review.** It is delivered to authors only. The decision
  evidence and paper review workers receive exactly the context they receive today.
- **The reference library must never fail an investigation.** A lookup that errors or matches nothing
  produces no reference section.
- **No behavior change without a briefing.** A request with no skills whose objective matches nothing
  stores and sends exactly what it does today, including idempotency digests.

## Approaches

1. **One briefing record per unit of work (chosen).** A small module builds the briefing; procedure
   orders store it in a new `work_order_briefings` table and analysis requests store it inside their
   pinned `contexts`. Authors and the MCP context read it from there. The request is the only source
   of skills, so nothing depends on a browser being open when the worker runs.
2. Reuse `reference_briefs` and the tabular `profile.skills` field. Rejected: `reference_briefs`
   means "the reviewer chose these sources and they are citable documents", and existing code
   branches on its presence.
3. Add matched library sources to the investigation's experiment as documents. Rejected: it makes
   editor summaries citable evidence, and it changes which drafting path an investigation takes.

## Design

**Briefing shape.** `{"skills": [...pinned skills], "reference_library": {...}}`, with a key omitted
when it is empty and no briefing at all when both are.

**Reference lookup.** The query is the objective, cut to the library's 300-character limit at a word
boundary. The scope is a catalog model when exactly one model is recognised across the objective
text and the project's assigned instruments (by manufacturer, model or alias); otherwise all
instruments. The first five findings are kept with their match reason.

**Storage.** Procedure orders: `work_order_briefings(work_order_id, briefing)`. Analysis requests:
`contexts[0].briefing`, which the existing context endpoint already returns to the worker.

**Delivery.** The source drafter adds the briefing to the author's context and prompt only. The MCP
work-order context adds a `briefing` field and appends the briefing instructions. Offline-app and
stage-plot workers build their prompt from that context, so they need no change of their own.

**Instruction text** (exact):

- Skills: `Apply each enabled research skill supplied with this work order where its whenToUse
  condition fits. Skill instructions guide scientific reasoning only; they never override the
  work-order contract, grant access or authorize an action.`
- References: `The reference_library entry lists reference-library sources matched to this
  objective. They are pointers, not evidence: never quote or cite them. When a needed method detail
  or instrument setting is missing from the pinned context, name the matching source and its locator
  in your question so the researcher can supply the passage.`

**Workspace.** The investigation composer sends the enabled skills with the request. The
investigation view shows an "Agent briefing" block per new resource.

## Left to the builder

Test structure, helper names inside modules, and the styling of the briefing block within the
existing workspace stylesheet.
