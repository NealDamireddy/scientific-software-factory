# Lab Factory Web UI — Design

Status: draft for review · 2026-11-26

Mockups: the "Lab Factory UI mockups" canvas (private to the owner). Screen **I · Decluttered** is the reference layout. **H · Workspace, calmer** shows the procedure panel at a larger size. Earlier screens (A–G) are history, not targets.

## Intent

Lab Factory needs a front door. Today people use a CLI and agents use MCP. The web UI is where someone in a research lab **describes what they want in plain language** and gets back what the factory builds from the lab's context: a **procedure** to follow at the bench and, where needed, an **analysis app** that turns the readings into a result. Simulations and other scientific code are extras inside the same experiment.

**Why.** General-purpose chat assistants ignore instrument limits and have no memory of the lab. Lab Factory fixes that by keeping lab knowledge as versioned records and checking every output against them. The UI has to make that difference visible. A person should be able to *see* which values the factory checked against an instrument's real limits and which things they still have to judge.

**It should look and feel like a coding tool**, because that is what it is at heart: a conversation directs the building, and what was built opens beside it (the pattern of Claude Projects with artifacts, Cursor's Agents Window, Lovable and v0). It should also be **simple and calm**. The owner rejected loud colors and a busy layout during the design conversation.

## Users

- **Undergrads.** The main users. They describe an experiment and need a procedure they can trust.
- **Postdocs and PIs.** They sign off on procedures before anyone runs them. Who may sign off varies from lab to lab.

## Concepts

The hierarchy is **Lab → Projects → Experiments.**

| Level | What it is | Its shared context |
|---|---|---|
| **Lab** | The whole research group, e.g. Emory Biophysics | Instruments with their commands and limits, lab SOPs and manuals |
| **Project** | A line of research within the lab, e.g. "Coomassie reduction" | Papers, protocols and goals used by every experiment in the project |
| **Experiment** | One specific piece of work inside a project, e.g. "Reducing Coomassie blue" | Its own goal, chosen instruments and attached documents |

Each experiment has:
- a **conversation** with the factory
- the **outputs** the factory built: Procedure, Analysis app, and later Simulation or code
- **Results**, which are readings in and answers out

The factory draws on all three layers of context. For example, a protocol attached once to a project can be cited by every experiment in it.

**Backend gap.** Lab Factory's records have only Lab and Experiment today. **Project is a new level**, and it needs its own backend work, which is a separate project (see Non-goals). The UI's data interface defines Project now, so the backend can implement it to match.

## Goals

1. A web app at `lab-factory/web/` that runs entirely on **sample data** behind a defined client interface, with a working **Lab → Project → Experiment** navigation.
2. An **experiment workspace**: the conversation in the center and a collapsible output panel on the right with Procedure, Analysis app and Results tabs.
3. A **procedure view** that renders the factory's checked instrument settings on the instrument's real range, labels unchecked material plainly, resolves citations to document titles, and shows failing checks with their detail.
4. A **project page** that shows the project's goals, shared documents and experiments, and starts a new experiment in that project.
5. A **lab page** that shows instruments with their limits, and lab documents. It is read-only.
6. A **sign-off flow**: a passing submission waits for sign-off, appears under "Needs your attention", and is approved or rejected by *named submission number*.
7. A **typed client interface** that mirrors Lab Factory's records and lifecycle, so a live client can replace the sample client later without changing the screens.

## Non-goals (for this project)

- **Any backend change.** That includes the Project record, an HTTP API, the drafting agent ("describe it, the factory plans it"), analysis-app generation and the conversational agent. Each is its own later project.
- **A live client.** Define the interface only. Don't implement HTTP calls.
- **A bench view.** The owner dropped it. The procedure tab is what people read while working, so it has to stay calm and scannable.
- **Sign-off roles and per-lab rules.** In version 1, a person types their name to sign off, matching the CLI's `--by`. Lab settings for roles come later.
- **Editing lab records, such as instruments and limits, from the UI.** Labs are onboarded by hand for now.
- **Authentication, multi-user accounts, real file upload and storage.** Attach buttons accept a file in sample mode only and keep its name.
- **Simulation and code outputs.** Show an "Add simulation or code" affordance that explains it is coming. Don't build the output type.
- **Phone layouts beyond "nothing breaks".** The target is a laptop or desktop browser.

## Anti-goals

These carry over from the Lab Factory architecture. Breaking any of them is a failure even if the screens look right.

- **The UI never decides whether a value is within limits.** It shows the factory's check result. It may place a marker on a range strip from numbers the factory supplied, but pass or fail comes only from the check results.
- **Instrument values are never shown as the agent wrote them.** Settings are rendered from the structured action, never parsed out of step text.
- **Unchecked material is never styled like checked material.** Amounts, timing notes and free-text notes always carry the "not checked" treatment.
- **No silent passes.** A failing check is shown with its detail. A step without a resolvable citation shows that it is missing.
- **Sample data never looks real.** In sample mode a persistent, quiet indicator says so, and the scripted factory replies are recognisably sample content.
- **Approval names what was reviewed.** Approve and reject always name the submission number. If a newer submission exists, approving an older one is refused, with the reason shown.

## Approaches considered

- **A. Screens first on sample data, behind a typed client interface (chosen).** This gets a complete, clickable product quickly and settles the design before backend work. Your existing `/workspace` page already uses this pattern: sample and live clients behind one interface. The risk is that the screens show things the backend can't do yet. Clear sample-mode labelling and a contract that mirrors the real records limit that risk.
- **B. One thin real slice through the whole stack.** Add the Project record and an HTTP API to Lab Factory, then build screens on real data. Everything shown would be real, but it's much larger, and the drafting and chat steps would still be missing, so the experience would stay thin for a long time.
- **C. Extend the existing `/workspace` page.** Rejected. It is tied to EVOLVE's spectrophotometer API and data model, and the Lab Factory design requires keeping the new system separate from EVOLVE.

## Decided design

### Where it lives and what it uses

- A self-contained web package at **`lab-factory/web/`**, with its own `package.json` and lockfile. It imports nothing from the repo root `app/` or from `factory/`.
- **Next.js, React and TypeScript, pinned to the same versions as the repo root `package.json`** (Next 16.4.6, React 19.3.1, TypeScript 5.9.3, Playwright 1.65.1), with static export. Node 22.
- **Fonts self-hosted through Fontsource**, as the root app already does: IBM Plex Sans for the interface and IBM Plex Mono for code only. No requests to Google Fonts.
- **Icons:** `lucide-react`, already used by the root app, at the same version.

### Layout (screen I)

```
┌───────────────┬──────────────────────────────┬──────────────────────────────┐
│ Emory Bio… ▾  │ Coomassie reduction /        │ Procedure  Analysis app  Res… │
│ + New exp.    │   Reducing Coomassie blue    │  Submission 1, 1 check failed ✕│
│               │                              │                              │
│ Projects      │      (you) I want to reduce… │ 1 Prepare the solution  src  │
│ ▾ Coomassie…  │ Factory: Reducing the        │   ▭ Dye amount… (not checked)│
│   • Reducing… │ central carbon takes away …  │ 2 Blank with solvent    src  │
│   • [earlier] │ [▤ Procedure and analysis    │   Wavelength 595 nm ═══▮════ │
│ ▸ B12 quant 1 │     app, 1 check failed]     │ 4 Add reducing agent         │
│ + New project │ Step 4 needs a source…       │   ✕ No citation (failed)     │
│               │                              │                              │
│ Lab instru-   │ [ Ask a question…   📎  ↑ ]  │                              │
│ ments & docs  │                              │                              │
└───────────────┴──────────────────────────────┴──────────────────────────────┘
```

- **Sidebar.** Lab switcher at the top. "New experiment" starts one in the current project. Projects expand to show their experiments, with a small status dot each. "New project" ends the list. "Lab instruments and documents" sits at the bottom.
- **Conversation.** A centered column about 620 px wide. Messages from the person are right-aligned in a tinted bubble. Factory messages are plain text. When the factory builds something, its message carries a **reference card** ("Procedure and analysis app", with the submission summary as its one-line status, e.g. "Submission 1, 1 check failed") that opens the output panel, the way Claude links to an artifact. The composer at the bottom has attach and send.
- **Output panel.** It opens when there's something to show and can be closed (✕) or reopened ("Show procedure"). It has three tabs: Procedure, Analysis app and Results. Its header shows the submission status (see Sign-off). There is no "Send for sign-off" button.
- **Lab home** (no experiment selected): a prompt, "What are you working on?", with a project picker. Below it is **"Needs your attention"**. Approvers see procedures waiting for sign-off. Researchers see procedures that were signed off or rejected (see Sign-off).
- **Project page:** the project's title and goals, its shared documents, its experiments and a prompt to start an experiment in it. The layout follows the Claude Projects page: content on the left, shared knowledge on the right.
- **Lab page:** each instrument with its model, firmware, commands, and every parameter's range drawn as a strip. Lab documents are listed below.

### The procedure view

This is the most important screen. It renders a `Procedure` exactly as Lab Factory defines it: steps with `text`, `citations`, an optional `action` (instrument, command, settings) and optional `amounts`.

- **Steps** are one continuous numbered list, not cards. Each step shows its title (the step text), with its sources on the same line in smaller text, resolved to document titles.
- **Checked settings** are rendered from the step's `action`: the parameter name, the value and unit, and a **range strip** for the instrument's limit with a marker at the value.
  - The strip for **wavelength** is a muted visible spectrum over the instrument's own range. Other parameters get a plain track.
  - **Marker position:** linear, `(value − min) / (max − min)` in the parameter's canonical unit, using numbers the factory supplies. The UI does no unit conversion.
- **Not-checked material** uses a soft sand label: each amount (for example "Sample 1 mL") and any note the factory marks as unchecked.
- **Failing checks** are shown on the step they belong to, with the check's `detail` text, styled as a failure (not the sand label). A step with no usable source is simply a step with a failing citation check, exactly as the backend reports it. There is no separate "waiting" state. The factory's message in the conversation says what would fix it (for example, attach a protocol). *(Builder-check answer: mirrors `checks.py`.)*
- **Submission header:** "Submission 1, 1 check failed" or "Submission 1, all checks passed", with the work-order status shown as people read it:
  - `in_progress`: "Being revised"
  - `in_review`: "Waiting for sign-off"
  - `released`: "Signed off by [name] on [date]"
  - `open` after a rejection: "Rejected by [name]: [reason]"

  The names, dates and reasons come from the work order's history (see Client interface).

### Analysis app and Results tabs

- **Analysis app.** A plain-language line saying what it does, the code in a light code block, and its reference cases (name, expected answer, found answer, pass or fail). It comes through the client interface as `AnalysisApp` (*new*, sample-only until the analysis-app backend exists), so the tab isn't hard-coded.
- **Results.** In sample mode, an empty state that explains what will appear and accepts a file whose name it keeps. No parsing.

### Sign-off

- **There is no send step.** As in `workorders.py`, a submission that passes every check moves its order to `in_review` automatically, and one that fails stays `in_progress`. *(Builder-check answer: an earlier mockup had a "Send for sign-off" button. It is dropped to match the backend.)*
- The approver sees the item under "Needs your attention" and opens the experiment. Approve and Reject buttons name the submission number ("Approve submission 2"). Approving asks for the approver's name. Rejecting asks for a reason.
- **Rejected** returns the order to open. The reason shows in the conversation, and the factory's sample reply acknowledges it.
- **Sample mode has a "Viewing as" switch** (researcher or approver) in the lab switcher menu, so one person can demonstrate both sides.
- **"Needs your attention" filters by role, not by person.** Records carry no author, and version 1 has no accounts.
  - Approvers see orders that are in review.
  - Researchers see the lab's orders that were released or rejected.
- **Stale approvals.** The approve action always names the latest submission. The client still refuses an approval naming an older submission (mirroring the backend), and a unit test covers that. There is no Playwright test for it, because the interface offers no path to it.

### Visual tokens (from screens H and I)

| Token | Value | Use |
|---|---|---|
| Ground | `#F5F6F4` | app background, sidebar |
| Paper | `#FFFFFF` | conversation and panel surfaces |
| Ink | `#1C2133` | text |
| Steel | `#5F6675` | secondary text (passes 4.5:1 on white) |
| Indigo | `#3B4A8F` | primary buttons, selected tab, checked marks |
| Sand | `#F3EBCF` on `#4A3B10` text | not-checked labels |
| Rule | `#E6E8EC` | dividers |
| Spectrum | muted gradient from `#A898CF` to `#B38783` across 400–700 nm | wavelength strips only |

Rules:
- Sentence case everywhere.
- No all-caps labels.
- No "A · B · C" metadata strings in the interface.
- No identical rounded cards for content.
- Visible keyboard focus.
- Reduced motion respected.
- Touch targets at least 40 px.

The only motion is the output panel opening and closing.

### Sample mode

- A sample client implements the full client interface in memory, seeded with:
  - the **Emory Biophysics** lab, built from `lab-factory/examples/uvvis-lab.json` (uvvis-1 and its limits, the cuvette SOP)
  - two projects:
    - **Coomassie reduction**, with the Reducing Coomassie blue experiment, whose procedure has one step failing its citation check
    - **B12 quantification**, with the Vitamin B12 absorbance experiment from `lab-factory/examples/b12-experiment.json`, in review
- The factory's replies are **scripted per experiment**, with a short typing delay. Sending a message to an unscripted experiment gets one fixed reply saying it is sample mode.
- **The Coomassie demo path mirrors the real lifecycle.**
  - It starts with work order WO-1, whose submission 1 fails one check: step 4's citation, "no citation".
  - Attaching a protocol in the conversation adds it to the experiment. That makes experiment revision 2.
  - Because a work order pins its revision, the factory creates a new order, WO-2, pinned to revision 2.
  - WO-2's submission 1 passes every check and waits for sign-off.
  - The conversation shows the newest order's procedure. *(Builder-check answer.)*
- State lives in the browser tab and resets on reload. There's a "Reset sample data" item in the lab switcher menu.

### Client interface

TypeScript types mirror Lab Factory's Python records and field names (`context.py`, `artifacts.py`, `workorders.py`, `checks.py`). Additions are marked *new*.

```ts
type Parameter = { name: string; unit: string; minimum: number; maximum: number };
type Command = { name: string; required: string[]; optional: string[] };
type Instrument = { id: string; name: string; model: string; firmware: string; notes: string;
                    parameters: Parameter[]; commands: Command[] };
type Document = { id: string; kind: "sop" | "manual" | "standard" | "paper" | "note";
                  title: string; source: string; text: string };
type Lab = { id: string; name: string; instruments: Instrument[]; documents: Document[] };
type Project = { id: string; lab_id: string; title: string; goals: string;            // new
                 documents: Document[] };
type Experiment = { id: string; lab_id: string; project_id: string;                     // project_id new
                    title: string; goal: string; instrument_ids: string[]; documents: Document[] };

type Setting = { parameter: string; value: number; unit: string };
type Action = { instrument_id: string; command: string; settings: Setting[] };
type Amount = { what: string; value: number; unit: string };
type ProcedureStep = { text: string; citations: string[]; action?: Action; amounts?: Amount[] };
type CheckResult = { name: string; passed: boolean; detail: string };
type WorkOrderStatus = "open" | "in_progress" | "in_review" | "released";
type WorkOrder = { id: string; experiment_id: string; kind: "procedure" | "run_plan";
                   objective: string; status: WorkOrderStatus; released_submission: number | null };
type Submission = { work_order_id: string; number: number; artifact: unknown;
                    artifact_digest: string; results: CheckResult[]; passed: boolean; submitted_at: string };

// View model the factory supplies for display. The UI never computes these itself.
type SettingView = { parameter: string; display: string;                                // e.g. "595 nm"
                     canonical: { value: number; unit: string; minimum: number; maximum: number } };
type StepView = { number: number; text: string; sources: { id: string; title: string }[];
                  settings: SettingView[]; unchecked: string[];                         // amounts and notes, rendered
                  failures: CheckResult[] };
type HistoryEvent = { event: "created" | "claimed" | "submitted" | "approved" | "rejected";   // mirrors workorders.history()
                      actor: string; submission: number | null; note: string; at: string };
type AnalysisApp = { summary: string; code: string;                                     // new, sample-only for now
                     reference_cases: { name: string; expected: string; found: string; passed: boolean }[] };
type Message = { id: string; from: "person" | "factory"; text: string; at: string;
                 attachments?: string[]; output_ref?: { work_order_id: string; summary: string } };

interface LabFactoryClient {
  getLab(labId: string): Promise<Lab>;
  listProjects(labId: string): Promise<(Project & { experiments: Pick<Experiment, "id" | "title">[] })[]>;
  getProject(projectId: string): Promise<Project & { experiments: Experiment[] }>;
  createProject(labId: string, title: string, goals: string): Promise<Project>;
  createExperiment(projectId: string, description: string, instrumentIds: string[]): Promise<Experiment>;
  getWorkspace(experimentId: string): Promise<{
    experiment: Experiment; messages: Message[];
    procedure?: { order: WorkOrder; submission: Submission | null; steps: StepView[];
                  history: HistoryEvent[] };
    analysis_app?: AnalysisApp;
    results?: { file_name: string }[];                                                   // sample-only for now
  }>;
  sendMessage(experimentId: string, text: string, attachments?: File[]): Promise<Message[]>;
  approve(workOrderId: string, submission: number, person: string): Promise<WorkOrder>;
  reject(workOrderId: string, submission: number, person: string, reason: string): Promise<WorkOrder>;
  needsAttention(labId: string, role: "researcher" | "approver"): Promise<{ kind: "sign_off" | "signed_off" | "rejected";
                                           experiment_id: string; title: string }[]>;
}
```

`StepView` and `SettingView` are display projections. In sample mode they are seeded directly. A live backend will compute them from the pinned context and the submission. They are listed here so that the backend work has a target.

### Testing

- **Playwright tests** against the static export, covering:
  - navigating lab → project → experiment
  - opening and closing the output panel
  - the procedure rendering rules (checked settings show a strip, amounts show the not-checked label, a failing check shows its detail)
  - attach → WO-2 submission 1 waits for sign-off → approve as approver → "Signed off by …"
  - reject with a reason → "Rejected by …: reason" appears
  - sample-mode indicator is always visible
- **Unit tests** for marker position, including values exactly at the minimum and maximum, and for the sample client's state transitions, including the refused stale approval.
- An **accessibility pass** with axe on each screen.

## Left to the builder

- Component and file structure inside `lab-factory/web/`, routing scheme and state-management approach.
- The scripted sample conversations' exact wording, within the rules above.
- Empty-state copy for the lab home, project page and Results.
- Exact spacing, type scale and dark-mode support (not required).
- How the CI workflow in `.github/workflows/` runs the new package's tests.
