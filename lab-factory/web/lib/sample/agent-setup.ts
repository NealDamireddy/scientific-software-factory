// What a person needs to connect their own coding agent: MCP setup that matches
// lab-factory/README.md, the four MCP tools with their docstrings from
// lab-factory/src/labfactory/mcp_server.py, and the work-order skill.
import type { AgentSetup } from "../types.ts";

const PROJECT = "/absolute/path/to/lab-factory";
const DATABASE = "/absolute/path/to/labfactory.db";
const ARGS = ["run", "--locked", "--project", PROJECT, "labfactory", "--db", DATABASE, "serve"];

/** Equal, byte for byte, to public/skills/labfactory-work-orders/SKILL.md (a test checks it). */
export const SKILL_MD = `---
name: labfactory-work-orders
description: Use when working Lab Factory work orders over MCP. Claims an open order, builds a procedure or run plan from the pinned lab context and the lab's skills, submits it for checks, and fixes and resubmits until every check passes.
---

# Working Lab Factory work orders

Lab Factory hands out work orders for a lab experiment: write a procedure, or write a run plan for an instrument. You do the work through four MCP tools on the \`labfactory\` server. The factory checks everything you submit against the lab's real instruments and documents, and a person signs off passing work.

## The loop

1. Call \`list_work_orders\` (status \`open\` by default) and pick an order.
2. Call \`claim_work_order\` with the order id and a stable worker name, such as \`codex on lab-pc\`. Save the returned \`claim_id\` before starting work. Use the same worker name and saved ID for retries of this work.
3. Call \`get_work_order_context\`. It returns the work order, the pinned lab and experiment, an \`artifact_example\` showing the exact artifact format, \`instructions\`, and \`previous_rejection\`.
4. Build the artifact. Follow the lab's enabled skills when the context includes them (or they were given to you alongside this file), and the artifact format in \`artifact_example\`; if there are none, follow \`instructions\`. Use only the pinned context: its instruments, commands, parameters, limits and documents.
5. Call \`submit_artifact\` with the order id, worker name, saved \`claim_id\`, and artifact. It returns numbered check results.
6. If any check failed, read every failed check's detail, fix the artifact, and submit again. If the server refuses the claim ID, stop this attempt. Repeat until every check passes. A passing submission waits for a person's sign-off.

A reopened order is \`open\` again with no worker, and carries the reviewer's reason in \`previous_rejection\`. Claim it again, read the context, address that reason, then submit.

If a tool returns an \`error\` field, read it. A failed claim means the order is no longer open, so pick another.

## Rules

- Instrument values go only in actions: the instrument id, a command the instrument lists, and every required setting, each in a supported unit and within its limits.
- Hand-measured values go in amounts, never in the step text. Don't write numbers with units, such as \`550 nm\` or \`5 minutes\`, in the text.
- Every procedure step cites a document id from the pinned context.
- Never invent instruments, commands or parameters. If the context doesn't have what the work needs, say so instead of guessing.

## Sign-off

Only a person can sign off a submission. Agents cannot approve or release work.

Passing checks mean the submission is ready for review, not that it is approved. Don't try to approve, release or reopen orders yourself, and don't claim that work is signed off.
`;

export const AGENT_SETUP: AgentSetup = {
  claude_code: `claude mcp add labfactory -- uv run --locked --project "${PROJECT}" labfactory --db "${DATABASE}" serve`,
  codex_toml: [
    "[mcp_servers.labfactory]",
    'command = "uv"',
    `args = [${ARGS.map((a) => JSON.stringify(a)).join(", ")}]`,
  ].join("\n"),
  cursor_json: JSON.stringify({ mcpServers: { labfactory: { command: "uv", args: ARGS } } }, null, 2),
  tools: [
    { name: "list_work_orders", description: "List work orders with the given status." },
    { name: "get_work_order_context", description: "Read pinned context, artifact format, and feedback from the previous reviewer." },
    { name: "claim_work_order", description: "Claim an open order and return its claim ID. Include untagged_artifact to preflight an untagged upload." },
    { name: "submit_artifact", description: "Submit with the claim ID captured before starting work. Reuse the ID on retries." },
  ],
  skill_md: SKILL_MD,
};
