# Lab Factory — Architecture Design

Status: draft for review · 2026-11-25

## Intent

Every research lab gets its own scientific software factory. When a lab is onboarded, its instruments and background are loaded into the factory. When someone starts an experiment, they add that experiment's own context. From then on the factory has two jobs:

1. **Procedure help.** It produces a step-by-step procedure for the experiment, grounded in the lab's context and in published standards. Think of it as teaching an undergrad how to run a procedure in this specific lab.
2. **Analysis software.** It generates accurate analysis software from the same context, so data can be analyzed right after it is collected and nobody has to write code.

**Why.** General-purpose LLMs fail in research labs in two ways. They ignore instrument limits and firmware behavior, especially on uncommon or custom-built instruments. And they have no memory of the lab. The factory fixes both by keeping lab knowledge outside the model, as versioned records, and by checking every output against those records before it is released.

## Users

Undergrads (the main people running experiments), postdocs and PIs.

## Goals

- Store the lab's context and each experiment's context as versioned, immutable records. Instrument limits are structured data that code can check.
- Produce three kinds of output, each a candidate until it passes its checks:
  - a **procedure**: steps a person follows, with citations
  - a **run plan**: instrument commands for live control
  - an **analysis app**: Python that turns raw readings into results
- Serve the context and work orders to any coding agent over MCP (the 8090 pattern). The factory keeps the context, the work orders and the checks. The agent does the writing.
- Trace every released output to the exact revisions of the lab and experiment context it was built from.

## Non-goals (for now)

- Onboarding tooling, such as extracting structured records from manuals. Records are written by hand.
- The rules for who may sign off. For now, a named person approves each release. Roles come later.
- Rules for what labs share with each other. The design leaves room for a shared library but builds none.
- A web UI. People use a CLI first.

## Anti-goals

- **A model that decides whether an instrument limit holds.** Limits are enforced by code, both in checks and later beside the instrument.
- **An agent that can release its own work.** Only a person can approve. The core gives this guarantee only against agents that use the MCP server. See "Trust assumption" below.
- **Answers that can't be traced.** A procedure step without a citation to the lab's context fails its check.
- **Unchecked values presented as checked.** A person sees instrument values only as the factory renders them from checked settings. Any other text is labeled as not checked by code.
- **Silent passes.** An unknown unit, parameter, command or record is a failure, never a skip.

## Approaches considered

- **A. One factory, three output types, served over MCP (chosen).** Lab context is versioned. Work orders pin a revision of it. Checks gate every release. Any agent connects over MCP. This keeps procedures and software consistent with each other and with instrument limits.
- **B. A procedure chatbot added to the existing software factory.** Faster to demo, but the chatbot's answers aren't checked against limits. That's the failure we're trying to remove, and the procedure and the software would drift apart.
- **C. One general agent with tools.** The most flexible, but limits would hold only as far as the model's judgment holds.

## Architecture

```
        Shared library (later, read-only for labs)
                         │ pull
┌──────────────── One lab's deployment ───────────────┐
│ Context store (versioned, immutable revisions)      │
│   Lab: instruments + commands + limits + firmware,  │
│        documents (SOPs, manuals, standards)         │
│   Experiment: goal, instruments used, documents     │
│                                                     │
│ Work-order engine                                   │
│   open → in_progress → in_review → released         │
│   each work order pins lab + experiment revisions   │
│                                                     │
│ Checks (per output type, against pinned context)    │
│                                                     │
│ MCP server ── coding agent (Codex, Claude, …)       │
│ CLI        ── people (create, review, approve)      │
│                                                     │
│ Instrument agent (later): runs released run plans,  │
│   enforces limits beside the hardware, keeps raw data│
└─────────────────────────────────────────────────────┘
```

### Decided

- **Each lab is a separate deployment.** Shared material comes later, pull-only.
- **Two kinds of knowledge.** Hard facts (parameter limits, units, firmware notes) are structured records. Written material (SOPs, manuals, standards) is stored as documents that outputs must cite.
- **Live control follows the device/plan split.** Instrument drivers and their limits are written and verified once per instrument by a person. The factory generates only run plans, which are checked against those limits. Raw readings are always kept in full, so one instrument can serve many experiments. File upload stays a fallback. A later instrument agent will build on Bluesky.
- **Instruments declare their commands.** Each instrument record lists the commands its driver supports, along with each command's required and optional parameters. Run plans and procedure actions may use only those commands. This is the "device" half of the device/plan split, recorded now so a release means something the later instrument agent can rely on.
- **Procedures separate checked actions from unchecked prose.** A step has free-text notes, citations, an optional instrument *action* (instrument, command, settings) and optional *amounts* for things a person handles by hand, such as "sample 1 mL". The person sees the action as the factory renders it from the checked settings, never as the agent wrote it. Notes and amounts are labeled as not checked against instrument limits. The prose matcher flags the numeric unit expressions listed in the core plan. Free-text notes still require human judgment.
- **The person running the experiment signs off.** They inspect the numbered submission in execution order, including every instrument command and setting or each procedure step’s citations, action, amounts and notes. They approve a specific submission by number. If the work order has moved on to a newer submission, the approval is refused. The detailed sign-off rules are deferred.
- **Trust assumption for the core: a trusted local operator.** The MCP server offers no approve tool. But an agent with shell access as the same computer user could run the CLI's approve command itself, and the core does not prevent that. Enforced human-only release comes with the hosted lab deployment, where approval requires a login the agent doesn't have. The README states this plainly.
- **The new system stays separate from the existing EVOLVE code.** It lives in `lab-factory/`, with its own Python project, and does not import from `factory/`. Ideas such as the sandbox verifier can be ported later as their own sub-projects.

### Sub-projects, in order

1. **Factory core.** Context store, work orders, checks for procedures and run plans, MCP server and CLI. *(This plan.)*
2. **Analysis apps.** The analysis-app output type, with a sandboxed checker that runs reference cases. This ports the idea from EVOLVE's verifier.
3. **Procedure drafting.** The factory turns an experiment goal into work orders by itself, including retrieval over long documents.
4. **Instrument agent.** Bluesky-based runner on the lab PC that runs only released run plans.
5. **Lab memory, sign-off roles, shared library and web UI.**

## Factory core: behavior

- **Units.** Supported units are listed by dimension: wavelength/length, volume, time, temperature, magnetic field and absorbance. Values are converted to a canonical unit before comparison. Temperature converts with offsets (°C ↔ K). An unknown unit fails the check.
- **Limits.** Each instrument parameter has a canonical unit and an inclusive minimum and maximum. A value equal to a limit passes.
- **Revisions.** Saving a lab or experiment whose content differs from its latest revision creates a new numbered revision, with a SHA-256 digest of its canonical JSON. Saving identical content returns the existing revision, because people read "lab revision 3" as "the lab changed three times". Old revisions never change.
- **Work orders.**
  - Creating one pins the experiment's current revision and its lab's current revision.
  - Checks always use the pinned revisions, even after the lab is revised.
  - Kinds in the core are `procedure` and `run_plan`.
- **Lifecycle.**
  - An agent claims an `open` order, which becomes `in_progress`. Only one claim can win.
  - The claiming worker submits an artifact and the checks run. If every check passes, the order becomes `in_review`. If any check fails, it stays `in_progress` and the agent sees why, so it can fix the artifact and resubmit.
  - A person approves a named submission, which releases it, but only if that submission is the latest one, it is in review, and every check passed. The approval records the submission's number and the SHA-256 digest of its artifact.
  - A person can reject a named submission with a reason, which returns the order to `open`. Submissions and decisions are kept as history.
  - An agent that claims a reopened order gets the rejected artifact and the reviewer's reason in its context.
- **Run-plan checks.**
  - The instrument is listed on the experiment.
  - Every command exists on that instrument.
  - Every required setting for a command is present, and no setting the command doesn't accept is present.
  - Parameter names are unique within an instrument. Each action or run step supplies at most one value per parameter. Every setting names a parameter of the instrument, its unit converts, and its value is within limits. Operator-facing instructions preserve the precision of each checked value.
- **Procedure checks.**
  - Every step cites at least one document, and every citation resolves to a lab or experiment document in the pinned revisions.
  - Every action passes the same checks as a run-plan step.
  - Every amount has a known unit.
  - The notes pass the plan’s matcher for numeric unit expressions.
- **What a release certifies.** Against the pinned revisions, every check above passed for the exact artifact whose digest the approval recorded, and a named person approved that submission. It does not certify that the instrument's driver implements a command correctly, which is the instrument agent's job, or that the science is right, which is the reviewer's job.
- **MCP tools** (agent-facing): `list_work_orders`, `get_work_order_context`, `claim_work_order`, `submit_artifact`. There is no approve tool.

## Left to the builder

The SQLite schema details, CLI output formatting, and the internal module boundaries beyond those named in the plan.
