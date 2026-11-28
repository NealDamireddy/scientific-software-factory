# General procedure first drafts

Lab Factory drafts procedures from pinned sources, compiles applicable methods, and records questions when the evidence leaves a decision open. The endpoints use the existing reviewer session. The researcher workspace serves these endpoints on the same origin. [Workspace setup](../../reference-ui/README.md#start-an-investigation)

| Request | Result |
| --- | --- |
| `GET /api/procedure-drafts` | List automatic drafts and their current state, including superseded drafts. |
| `POST /api/procedure-drafts` | Save or reuse context, pin revisions, and return the first checked submission or question. |
| `GET /api/procedure-drafts/{order_id}` | Read the current state, immutable submitted steps or question, checks, evidence and related order IDs. |
| `POST /api/procedure-drafts/{order_id}/answers` | Resolve an outstanding question, produce a new numbered submission on a linked order, and preserve the earlier evidence. |

## Start

Supply a client-generated `request_id` and either an existing `experiment_id`, or both `lab` and `experiment` in the standard Lab Factory record formats. Inline records may create new IDs or reuse identical saved records. To change an existing record, save a revision through the context API before starting by ID. A document-only experiment may have empty instrument lists.

```json
{
  "request_id": "trace-review-001",
  "lab": {"id": "archive-lab", "name": "Archive lab", "instruments": [], "documents": []},
  "experiment": {
    "id": "trace-review", "lab_id": "archive-lab", "title": "Drift trace review",
    "goal": "Compare the recorded drift traces.", "instrument_ids": [],
    "documents": [{
      "id": "drift-check", "kind": "sop", "title": "Drift trace method",
      "source": "Archive handbook, section 2",
      "text": "Compare the drift traces.\nRecord the matching trace IDs."
    }]
  }
}
```

The optional `method_id` selects a specific pinned lab or experiment document. Otherwise the service looks for a single SOP that shares a topic word with the goal. Multiple applicable SOPs or an ambiguous selected ID produce a question. With sources and no applicable SOP the backend automatically invokes the source drafter. Clients can attach method excerpts, project notes and reference material as documents, and provide registered instruments and settings in the lab record. Connector metadata alone supplies no method evidence.

## Source-based drafting

The source drafter runs on a backend host with the Codex CLI on its PATH and an active CLI sign-in. The backend uses the objective, assigned instruments and document catalog to propose decision-specific searches. Each search retrieves up to 12 ranked passages from pinned records. The resolver can use their union and the latest researcher answer. It selects exact excerpts for each decision, and the drafter receives the selected passages. The scope covers archival studies and benign physical measurements. It can ask a specific question or submit ordered steps. A source reply creates a linked order and automatically invokes the drafter again with the previous question and the newly pinned answer. No separate agent claim or manual submission is needed.

The response includes `decision_evidence` with search phrases, retrieved passage IDs, findings, selected excerpts and decision status. A pending design preference has `state: needs_input` and `input_kind: researcher_choice`. A missing or conflicting method detail has `state: needs_input` and `input_kind: missing_method_detail`. Both can receive a reply through the existing answers endpoint. A separate model call checks proposed blockers against the goal and available records. A search that introduced an irrelevant requirement can be marked `out_of_scope`. The first confirmed unresolved decision takes precedence.

An independent model reviews the ordered steps and structured actions against the decisions, including omissions, conflicting instructions and the direction of a requested comparison. The backend checks referenced step numbers and supporting passage IDs. For operating decisions with a selected model-specific manual it checks the reference on the instrument step. The review is bound to the submitted artifact digest. The backend checks source quotes and quantities, device commands, units and limits before accepting the draft. A follow-up draft must cite the decision that informed it. For a completed source-authored draft, a separate model call reviews every pinned document of kind `paper`. It identifies the published choices the procedure uses, the step where each choice is adopted, and a supporting excerpt. It records a reason for each inapplicable paper. The backend checks each required excerpt against both the pinned passage and the evidence on that step. It saves the review against the exact draft digest and rechecks it at release. A source-authored draft with papers from before this check needs a fresh draft to obtain its review.

If the backend rejects the evidence for a planning decision or a proposed follow-up question, it can return a persisted `needs_input` question with `input_kind: missing_method_detail`. When the study identifies a single required instrument setting, the question names that setting and its unit and asks for its project-authorized value or method passage. Otherwise it requests the source and instruction for the decision. Submitting the answer runs the normal verification on a linked order. On an answered order the planner gets one internal retry before requesting more evidence.

When a step is missing an excerpt the reviewer identified, the backend attaches the verified passage to that step, preserves the procedure text and actions, and reruns the checks. If problems remain, the author receives the failures for correction. When a citation repair first makes the draft eligible for independent decision review, the author can still address that reviewer’s first objection using its selected evidence. If independent decision review still rejects an identifiable study decision after correction, the backend requests supporting method evidence and discards the rejected draft. At intake, if the author repeatedly fails to produce a verifiable draft and there is a single required setting identified by the study and device, the backend can still ask for that setting. Other exhausted artifact checks or an unavailable author or reviewer return HTTP 503 and the pending order ID. Repeat the same POST (including its request ID) to resume. An overlapping POST returns HTTP 202 and state `drafting`. GET reads status. Model calls run outside write transactions. A crashed worker's lease expires after thirty-three minutes.

The Vercel function alone does not provision a Codex CLI or its sign-in. The verified deployment path for this author is a local backend with the authenticated CLI. The backend does not execute the experiment or release a procedure.

## Supplied-method drafting

The first-draft compiler preserves the order of source instructions. It handles observational and record-keeping steps, explicit measured volumes, and registered instrument commands with settings. For example, with a registered `read_absorbance` command, “Read absorbance at 550 nm.” becomes a structured action and retains the original passage as evidence. Commands can use named parameters or a quantity whose unit resolves to exactly one accepted parameter. An optional `On instrument-id:` prefix resolves device ambiguity.

Supply one complete instruction per line, optionally numbered. Methods exceeding 128 instructions or 700 characters per line prompt for a focused excerpt. The compiler asks for clarification when it cannot represent a step, its conditions, or its settings. It does not invent experimental methods. Every candidate goes through the existing citation, quantity, command and instrument-limit checks. A passing candidate requires a separate human review.

## Reply and recover

For `state: needs_input`, display `question`, the 1-based `question_step` when available, and the relevant `sources`. Post a new `request_id` plus one of these inputs:

- `method_id` selects an entire pinned method from the returned `documents`.
- `title` and `text` supply a source. For a question about a particular step, supply a replacement instruction. A missing instrument setting can also be answered with a cited literal such as “The wavelength is 550 nm.” Other steps keep their original evidence. For a question about the entire method, provide the method excerpt.

The response includes `order.id`, pinned revision numbers, `state`, `submission.artifact`, `submission.results`, `sources`, and predecessor/successor order IDs. A ready first draft has state `in_review`. Review and release use the existing numbered-submission decision API. A superseded order points to its successor.

If a write response is lost, repeat the identical request with the same ID and reviewer. The backend returns the original order's current state, resuming a pending author call when needed. Reusing the ID for different input, answering a superseded question, or answering after the underlying context changes returns HTTP 409. Invalid input returns 400 and an unknown order or saved experiment returns 404.
