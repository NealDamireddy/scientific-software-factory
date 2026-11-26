---
name: labfactory-work-orders
description: Use when working Lab Factory work orders over MCP. Claims an open order, builds a procedure or run plan from the pinned lab context and the lab's skills, submits it for checks, and fixes and resubmits until every check passes.
---

# Working Lab Factory work orders

Lab Factory hands out work orders for a lab experiment: write a procedure, or write a run plan for an instrument. You do the work through four MCP tools on the `labfactory` server. The factory checks everything you submit against the lab's real instruments and documents, and a person signs off passing work.

## The loop

1. Call `list_work_orders` (status `open` by default) and pick an order.
2. Call `claim_work_order` with the order id and a stable worker name, such as `codex on lab-pc`. Use the same name for every call on this order, and from one session to the next, so the lab can see who did the work.
3. Call `get_work_order_context`. It returns the work order, the pinned lab and experiment, an `artifact_example` showing the exact artifact format, `instructions`, and `previous_rejection`.
4. Build the artifact. Follow the lab's enabled skills and the artifact format in the context. Use only the pinned context: its instruments, commands, parameters, limits and documents.
5. Call `submit_artifact` with the order id, the same worker name and the artifact. It returns numbered check results.
6. If any check failed, read every failed check's detail, fix the artifact, and submit again. Repeat until every check passes. A passing submission waits for a person's sign-off.

A reopened order carries the reviewer's reason in `previous_rejection`. Address that reason before you resubmit.

## Rules

- Instrument values go only in actions: the instrument id, a command the instrument lists, and every required setting, each in a supported unit and within its limits.
- Hand-measured values go in amounts, never in the step text. Don't write numbers with units, such as `550 nm` or `5 minutes`, in the text.
- Every procedure step cites a document id from the pinned context.
- Never invent instruments, commands or parameters. If the context doesn't have what the work needs, say so instead of guessing.

## Sign-off

Only a person can sign off a submission. Agents cannot approve or release work.

Passing checks mean the submission is ready for review, not that it is approved. Don't try to approve, release or reopen orders yourself, and don't claim that work is signed off.
