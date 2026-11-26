# Lab Factory HTTP contract

This is the HTTP API the web app's live client (`lib/live/client.ts`) calls. The
backend does not serve it yet. It is the contract the backend is built to,
working backwards from the web UI (see "Work backwards" at the end).

Every type name below (`Lab`, `Workspace`, `Revision` and so on) is defined in
`lib/types.ts`, and request and response bodies are exactly those shapes.
Field names are snake_case, matching Lab Factory's Python records.

## Configuration

The app is built in one of two modes:

| Variable | Meaning |
|---|---|
| `NEXT_PUBLIC_LABFACTORY_API_URL` | Base URL of the service, for example `https://labfactory.example.org/api`. When it is set at build time, the app uses the live client. When it is unset, the app uses sample data. |
| `NEXT_PUBLIC_LABFACTORY_LAB_ID` | Optional. The lab the app shows in live mode, passed as `{lab}` in the lab-scoped paths below. Defaults to the sample lab id, `emory-biophys`. |

Paths in this document are relative to the base URL. A trailing slash on the
base URL is ignored.

## Requests

- Every request is sent with `credentials: "include"`, so the service can use a
  session cookie. Authentication and accounts are out of scope for version 1:
  names are typed by people, not taken from a login. A service on another
  origin must answer CORS with `Access-Control-Allow-Credentials: true` and an
  explicit `Access-Control-Allow-Origin`.
- Path segments and query values are percent-encoded with
  `encodeURIComponent`. The service decodes them before looking anything up.
  Ids may contain characters such as spaces or `/`.
- JSON requests send `content-type: application/json` and
  `accept: application/json`. Requests without a body send no `content-type`.
- The one multipart request is `POST /experiments/{id}/messages`. The client
  lets the runtime set the multipart boundary.
- The two streaming requests send `accept: application/x-ndjson`.

## Errors

Any non-2xx response carries this JSON body:

```json
{ "code": "not_found", "message": "That project or experiment doesn't exist in this lab." }
```

`code` is one of `not_found`, `invalid` or `refused`, and `message` is a
sentence the UI shows to a person as is. The client maps the HTTP status, not
the `code` field:

| Status | Client error | Used for |
|---|---|---|
| 404 | `ClientError("not_found", message)` | An unknown lab, project, experiment, work order, submission, skill, connector or connector item. |
| 422 | `ClientError("invalid", message)` | A request that is malformed or has a blank required field. |
| 409 | `ClientError("refused", message)` | A well-formed request the current state doesn't allow: a stale sign-off, a name not on the sign-off list, a plan already confirmed, a disconnected connector. |

Anything else, including a 404, 409 or 422 whose body is not JSON or has no
string `message`, becomes `ClientError("refused", "The Lab Factory service
returned {status}.")`. A 2xx response whose body is not valid JSON is treated
the same way. If the request never gets a response, the client throws
`ClientError("refused", "The Lab Factory service couldn't be reached.")`.

## Streaming replies

`POST /experiments/{id}/messages` and `POST /experiments/{id}/plan` answer
`200` with `content-type: application/x-ndjson`: one JSON object per line,
separated by `\n`, written as the work happens.

```
{"type":"activity","item":{"id":"a1","label":"Read lab context (revision 3)","outcome":"done"}}
{"type":"activity","item":{"id":"a2","label":"Used skill: How we write procedures","outcome":"info"}}
{"type":"activity","item":{"id":"a3","label":"Wrote procedure","outcome":"done"}}
{"type":"activity","item":{"id":"a4","label":"Ran 10 checks: all passed","outcome":"passed"}}
{"type":"messages","messages":[ ...Message ]}
```

- Zero or more `{"type":"activity","item": ActivityItem}` lines come first.
  The client calls `onActivity` for each one as soon as its line arrives, so
  the service must flush each line rather than buffer the whole reply.
- Then exactly one `{"type":"messages","messages": Message[]}` line. These are
  the new messages for the conversation: for `messages`, the person's message
  followed by the factory's reply; for `plan`, the factory's reply. The
  factory's reply carries the same activity items in `activity`, and its
  `output_refs`.
- If the work fails after the `200` has been sent, the service writes
  `{"type":"error","code": "refused","message": "..."}` and ends the stream.
  The client throws `ClientError(code, message)`. Errors found before any work
  starts (an unknown experiment, a blank message, a plan already confirmed)
  use a normal error status and the JSON error envelope instead.
- Blank lines are ignored, the last line may omit its trailing newline, and
  the body is UTF-8. A stream that ends without a `messages` line is a
  failure: the client throws `ClientError("refused")`.

## The service decides, the UI shows

- **Pass or fail comes only from the service.** The service computes every
  `CheckResult`, and it computes every `StepView`, `RunStepView` and
  `SettingView` (including `SettingView.canonical`, the value converted to the
  instrument parameter's unit with that parameter's `minimum` and `maximum`).
  The UI places markers from those numbers and never decides whether a value
  is within limits. A `SettingView.display` is the value as the factory wrote
  it in the structured action, never parsed out of step text.
- **Sign-off rules are enforced by the service.** The UI checks the same rules
  so it can explain them early, but the service refuses a request that breaks
  them, whatever the UI sent. See "Approve" and "Reject".
- **Identical content does not make a revision.** Every change to a lab,
  project, experiment or skill appends a numbered revision with the SHA-256
  digest of its canonical JSON, as `store.py` does today. If the new content's
  digest equals the latest revision's digest, no revision is appended and the
  latest revision is returned unchanged.
- **Analysis code never reaches the network.** The analysis app and the
  simulation run in a browser worker on the person's readings, which never
  leave the browser. Once the Python runtime has loaded, the worker removes
  every way the code has to make a request (`fetch`, `XMLHttpRequest`,
  `WebSocket`, `EventSource`, `importScripts`, `sendBeacon`, nested workers,
  and running strings as code, which would reach dynamic `import()`), so
  Python's `js` module finds them refused with `Network access is not
  available to analysis code.` The host serving the app should also send
  `Content-Security-Policy: connect-src 'self'` (plus the service's origin in
  live mode), so the browser itself enforces the same boundary.
- **Digests.** A digest is SHA-256 over canonical JSON (`sort_keys`, compact
  separators, ASCII-escaped). The backend must not emit whole-valued floats
  (for example `550.0`) in digested records, because JSON parsers in the
  browser cannot tell them from integers.

## Endpoints

### Get the lab

`GET /labs/{lab}`

- Response `200`: `Lab`, at its latest revision.
- Errors: `404` for an unknown lab.

### List projects

`GET /labs/{lab}/projects`

- Response `200`: `(Project & { experiments: Pick<Experiment, "id" | "title">[] })[]`,
  in creation order.
- Errors: `404` for an unknown lab.

### Get a project

`GET /projects/{id}`

- Response `200`: `Project & { experiments: Experiment[] }`, the project and
  its experiments at their latest revisions.
- Errors: `404` for an unknown project.

### Create a project

`POST /labs/{lab}/projects`

```json
{ "title": "Coomassie reduction", "goals": "Measure how fast dithionite fades Coomassie blue." }
```

- Response `201` (or `200`): `Project`, at revision 1, with no documents.
- The id is a slug of the title. If it is taken, the service appends `-2`,
  `-3` and so on.
- Errors: `404` for an unknown lab, `422` if the title or goals are blank.

### Create an experiment

`POST /projects/{id}/experiments`

```json
{ "description": "Measure the rate of fading at three dithionite amounts", "instrument_ids": ["uvvis-1"] }
```

- Response `201` (or `200`): `Experiment`, at revision 1.
- The title is the description cut to 60 characters at a word boundary, and
  the goal is the description.
- The service also starts the conversation: it stores the person's message and
  a factory message carrying a `Proposal` (`accepted: null`) that lists the
  outputs it would build. `getWorkspace` returns both.
- Errors: `404` for an unknown project, `422` if the description is blank or
  an instrument id isn't in the lab.

### Get an experiment's workspace

`GET /experiments/{id}/workspace`

- Response `200`: `Workspace`.
  - `procedure` and `run_plan` are the newest work order of each kind, as
    `OrderView<StepView>` and `OrderView<RunStepView>`. `submissions` is oldest
    first, `shown` is the latest submission's number, `steps` are the views of
    that submission, and `history` is the order's events oldest first.
  - `earlier` (optional) lists the experiment's older work orders of the same
    kind, newest first, each with its `submissions` (oldest first) and
    `history`. The submission picker lists these after the newest order's
    submissions, and the UI loads an earlier submission's steps with "Get one
    submission's view". A service that leaves it out shows only the newest
    order's submissions.
  - `analysis_app` and `simulation` are present only when the experiment has
    them.
- Errors: `404` for an unknown experiment.
- The UI has no other source for an experiment's status, so on each refresh
  it calls this once per experiment in the lab: for the sidebar's status
  dots, the status lines on the project page and the order links on the
  "Connect your agent" page (see "Work backwards").

```json
{
  "experiment": { "id": "coomassie-run-1", "...": "..." },
  "project": { "id": "coomassie-reduction", "...": "..." },
  "messages": [],
  "procedure": {
    "order": { "id": "WO-2", "kind": "procedure", "status": "in_review", "...": "..." },
    "submissions": [{ "work_order_id": "WO-2", "number": 1, "...": "..." }],
    "shown": 1,
    "steps": [],
    "history": [],
    "earlier": [
      {
        "order": { "id": "WO-1", "kind": "procedure", "status": "in_progress", "...": "..." },
        "submissions": [{ "work_order_id": "WO-1", "number": 1, "...": "..." }],
        "history": []
      }
    ]
  }
}
```

### Get one submission's view

`GET /work-orders/{id}/submissions/{n}`

- Response `200`: `{ "submission": Submission, "steps": (StepView | RunStepView)[] }`.
  The steps are `StepView`s for a procedure order and `RunStepView`s for a run
  plan order, computed against the context pinned to the order.
- Errors: `404` for an unknown work order or submission number.

### Send a message

`POST /experiments/{id}/messages`, `multipart/form-data`

| Field | Value |
|---|---|
| `text` | The message text. Always sent, possibly empty. |
| `files` | Zero or more attachments, each with its file name. Repeated once per file. |

- Response `200`: an NDJSON stream (see "Streaming replies").
- The person's message is stored with `attachments` set to the file names.
  Each attachment the factory keeps is added to the experiment as a document,
  under the same rules as "Add a document", which makes a new experiment
  revision.
- Errors: `404` for an unknown experiment, `422` if the text is blank and
  there are no files.

### Confirm a plan

`POST /experiments/{id}/plan`

```json
{ "message_id": "m2", "outputs": ["procedure", "analysis_app"] }
```

- `message_id` names the factory message that carries the proposal, and
  `outputs` lists the outputs the person kept switched on.
- Response `200`: an NDJSON stream. The service records `accepted`, builds
  each output from the pinned context and the lab's enabled skills, and
  streams activity as it goes: reading each context layer (with its revision),
  one `Used skill: {title}` line per enabled skill, writing each output,
  running its checks, and running the analysis app's reference cases.
- New work orders are pinned to the current lab, project and experiment
  revisions and to each enabled skill's revision (`Pin` with kind `skill`). A
  submission that passes every check moves its order to `in_review`.
- Errors: `404` for an unknown experiment or message, `422` if `outputs` is
  empty or names an output that wasn't proposed, `409` if the proposal was
  already accepted.

### Approve a submission

`POST /work-orders/{id}/approve`

```json
{ "submission": 2, "person": "Dr Rivera" }
```

- Response `200`: `WorkOrder`, now `released` with `released_submission` set.
- The service appends an `approved` event with the person as actor, the
  submission number, and the artifact digest as its note.
- The service must refuse the request under the same rules as the sample
  client, in this order, whatever the UI sent:
  1. `404` for an unknown work order.
  2. `422` if `person` is blank after trimming.
  3. `409` unless the order is `in_review` and `submission` is its latest
     submission. The message is exactly
     `Submission {n} is not the latest. Review submission {latest}.`
  4. `409` if the lab's sign-off rule is `listed` and the trimmed name isn't
     in the list, compared case-insensitively after trimming each listed
     name. The message is exactly `{name} isn't on this lab's sign-off list.`,
     with the name as typed after trimming.
  5. `409` if the submission doesn't pass every check, including when it is
     re-checked against the current checker, as `workorders.py` does today.
- Two identical approvals sent at once produce one release. The second is
  refused because the order is no longer `in_review`.

### Reject a submission

`POST /work-orders/{id}/reject`

```json
{ "submission": 2, "person": "Dr Rivera", "reason": "Use the 1 cm cuvette from the lab SOP." }
```

- Response `200`: `WorkOrder`, back to `open`.
- The service appends a `rejected` event with the reason as its note, and a
  factory message to the experiment's conversation with exactly the copy
  `Thanks. I’ll revise this to address: {reason}`. `get_work_order_context`
  returns the reason as `previous_rejection.reason` to the next agent that claims the order.
- Refusals are rules 1-4 of approve (not the re-check in rule 5), plus `422`
  if `reason` is blank after trimming. A reason is always required to reject.

### Needs your attention

`GET /labs/{lab}/attention?role={role}` where `role` is `researcher` or
`approver`.

- Response `200`: `AttentionItem[]`.
  - `approver`: one `sign_off` item per `in_review` order.
  - `researcher`: one `signed_off` item per `released` order, and one
    `rejected` item per `open` order whose latest event is `rejected`.
- The list filters by role, not by person. Records carry no author.
- Errors: `404` for an unknown lab, `422` for any other role.

### Add a document

`POST /projects/{id}/documents` or `POST /experiments/{id}/documents`

```json
{ "title": "Dithionite stock preparation", "kind": "sop", "text": "Weigh the sodium dithionite..." }
```

- `kind` is a `Document["kind"]`: `sop`, `manual`, `standard`, `paper` or
  `note`.
- Response `201` (or `200`): `Revision`, the record's new revision, with the
  note `Added {title}`.
- The document id is a slug of the title. If it collides with any document id
  in the lab, the project or the experiment, the service appends `-2`, `-3`
  and so on, so every citation resolves to one document. The service sets the
  document's `source`: `Added in Lab Factory` for a document added here
  (pasted or uploaded), `{connector name}: {account}` for a connector import,
  and `Attached in the conversation` for an attachment kept from a message.
- If the target already has a document with the same title and text, nothing
  changes and the response is the latest revision.
- Errors: `404` for an unknown project or experiment, `422` if the title or
  text is blank or the kind is unknown.

### List revisions

`GET /labs/{id}/revisions`, `GET /projects/{id}/revisions`,
`GET /experiments/{id}/revisions` or `GET /skills/{id}/revisions`

The client maps `Pin["kind"]` to the path: `lab` to `labs`, `project` to
`projects`, `experiment` to `experiments`, `skill` to `skills`.

- Response `200`: `Revision[]`, oldest first. `digest` is the SHA-256 of the
  record's canonical JSON, `at` is an ISO 8601 timestamp and `note` says what
  changed.
- Errors: `404` for an unknown record.
- "Built from" lists a submission's pins. Next to a pinned skill revision it
  shows the skill's current title, from "Skills", because a `Pin` carries no
  title; a skill renamed since keeps its pinned revision but reads with its
  new title.

### Get and update lab settings

`GET /labs/{lab}/settings`

- Response `200`: `LabSettings`. A new lab's rule is `{ "mode": "anyone" }`.

`PUT /labs/{lab}/settings`, with a `LabSettings` body:

```json
{ "sign_off": { "mode": "listed", "names": ["Dr Rivera", "Sam Okafor"] } }
```

- Response `200`: the stored `LabSettings`. Names are trimmed, blank names
  dropped, and duplicates removed, keeping the first.
- Errors: `404` for an unknown lab, `422` if the mode is unknown or a
  `listed` rule has no non-blank names.

### Search

`GET /labs/{lab}/search?q={query}`

- Response `200`: `SearchHit[]`, at most 20.
- A case-insensitive substring match on titles and ids of projects,
  experiments, documents (lab, project and experiment), instruments, skills
  and connectors. Hits are ordered projects, experiments, documents,
  instruments, skills, connectors.
- `href` is a hash route: `#/projects/{id}`,
  `#/projects/{projectId}/experiments/{id}`, `#/lab` for instruments and lab
  documents, `#/skills?skill={id}` for skills and `#/connectors` for
  connectors. A document links to its owner's page with `?doc={id}` appended.
- A blank query returns `[]`.
- Errors: `404` for an unknown lab.

### Skills

`GET /labs/{lab}/skills`

- Response `200`: `Skill[]`, in creation order.

`POST /labs/{lab}/skills` creates a skill, and
`PUT /labs/{lab}/skills/{id}` edits one. Both take:

```json
{ "title": "How we write procedures", "description": "One action per step, cite the SOP.", "body": "# How we write procedures\n..." }
```

- Response `201` for create (or `200`) and `200` for edit: `Skill`.
- Create: the id is a slug of the title, de-duplicated with `-2`, `-3`. The id `new` is
  reserved (it is the new-skill route) and the server must never issue it. The
  skill starts enabled at revision 1 with the note `Created`.
- Edit: appends a revision with the note `Edited`, unless title, description
  and body are all unchanged, in which case the skill is returned as is.
- Errors: `404` for an unknown lab or skill, `422` if the title or body is
  blank.

`POST /labs/{lab}/skills/{id}/enabled`

```json
{ "enabled": false }
```

- Response `200`: `Skill`. Switching a skill on or off never makes a revision.
- Errors: `404` for an unknown skill, `422` if `enabled` isn't a boolean.

### Connectors

`GET /labs/{lab}/connectors`

- Response `200`: `Connector[]`. A disconnected connector has
  `connected: false`, `account: null` and `items: []`.

`POST /labs/{lab}/connectors/{id}/connect`

```json
{ "account": "Lab drive" }
```

- Response `200`: `Connector`, now connected, with `account` set and its items
  listed.
- Errors: `404` for an unknown connector, `422` if `account` is blank.

`POST /labs/{lab}/connectors/{id}/disconnect`, with no body.

- Response `200`: `Connector`, with `connected: false`, `account: null` and
  `"items": []`.

`POST /labs/{lab}/connectors/{id}/items/{item}/import`

```json
{ "target": { "kind": "experiment", "id": "coomassie-rate" } }
```

- `target` is a `DocumentTarget`.
- Response `200`: `Revision`. The item is added under the rules of "Add a
  document": its kind becomes the document kind (`code` becomes `note`), its
  title and text are copied, and the source is `{connector name}: {account}`.
- Errors: `404` for an unknown connector, item or target. `409` with
  `Connect {name} first.` when the connector is disconnected. `422` with
  `Readings go to an experiment's Results tab.` for a `readings` item.

### Connected agents

`GET /labs/{lab}/agents`

- Response `200`: `AgentConnection[]`, derived from `claimed` events on the
  lab's work orders: one entry per worker name, with `last_seen` the time of
  its latest claim and `work_order_ids` deduplicated, newest first.

### Agent setup

`GET /labs/{lab}/agent-setup`

- Response `200`: `AgentSetup`: copy-ready MCP setup for Claude Code, Codex
  and Cursor that matches `lab-factory/README.md`, the four MCP tools with the
  docstrings from `mcp_server.py` as descriptions, and the work-order
  `SKILL.md`.

## Work backwards

The backend today (`lab-factory/src/labfactory/`) has versioned Lab and
Experiment records in SQLite, work orders with claim, submit, approve and
reject, deterministic checks, and four MCP tools. This contract implies the
following backend changes. They are separate work, done after the web UI.

1. **Project record.** Add `Project` (`id`, `lab_id`, `title`, `goals`,
   `documents`) as a versioned record in `store.py`, and `project_id` on
   `Experiment`. Pin the project revision on work orders next to the lab and
   experiment revisions, and let procedure citations resolve to project
   documents in `checks.py`. Give every revision a timestamp and a note so
   `Revision` can be served.
2. **The HTTP API.** A server for every endpoint above, with the error
   envelope, status mapping and percent-decoding described here, cookie
   credentials and CORS for the web app's origin.
3. **View models.** Server-side computation of `StepView`, `RunStepView` and
   `SettingView`, reusing the unit conversion and limit lookup that
   `checks.py` already does, so the UI never decides pass or fail. Also the
   `OrderView` history from the `events` table and `AttentionItem` lists.
4. **Sign-off over HTTP.** Approve and reject under the rules in "Approve a
   submission", including the exact refusal copy. `workorders.py` already
   requires the latest submission, a printable name and a reason to reject;
   the HTTP layer adds the lab's sign-off rule and the person-facing messages.
5. **Lab settings.** Store `LabSettings` per lab, defaulting to
   `{ "mode": "anyone" }`, and enforce the sign-off rule in approve and
   reject.
6. **Documents.** Adding a document to a project or experiment appends a
   revision, with id de-duplication across the lab, project and experiment
   and no revision for identical content, as `_append_revision` does today.
7. **Skills.** A versioned `Skill` record per lab with an enabled flag that
   isn't part of the revision. Work orders pin each enabled skill's revision.
   **`get_work_order_context` over MCP must include the lab's enabled skills**
   (id, title, description, body and revision) so an outside agent follows
   the same instructions the factory does, and its `INSTRUCTIONS` should tell
   the agent to follow them.
8. **Connectors.** A connector registry per lab (Google Drive, Zotero, a lab
   notebook, a shared instrument-data folder, GitHub) holding the connected
   account, listing items, and importing an item as a document. Readings from
   the instrument-data folder feed the Results tab rather than becoming
   documents.
9. **Conversation and plans.** Store each experiment's messages, proposals and
   activity. `POST /experiments/{id}/messages` and `POST /experiments/{id}/plan`
   drive a drafting agent that reads the pinned context and enabled skills,
   creates and submits work orders, and streams its activity as NDJSON.
   Creating an experiment produces the first proposal.
10. **Analysis apps and simulations.** Store an `AnalysisApp` (standard-library
    Python with an `analyze` entry and reference cases) and an optional
    `Simulation` per experiment, generated by the factory and served in the
    workspace. The browser runs them; the server never receives readings.
11. **Search.** The lab-wide search described in "Search".
12. **Agent connections and setup.** Derive `AgentConnection`s from `claimed`
    events, and serve `AgentSetup` from the same values as
    `lab-factory/README.md` and `mcp_server.py`, with the `SKILL.md` the web
    app ships at `public/skills/labfactory-work-orders/SKILL.md`.
13. **A status summary on `listProjects`.** Each experiment row could carry
    its newest procedure order's status and latest event (for example
    `{ "status": "in_review", "rejected_by": null }`). That would remove the
    UI's one `GET /experiments/{id}/workspace` per experiment on each refresh,
    which today feeds the sidebar's status dots, the project page's status
    lines and the agents page's order links.
