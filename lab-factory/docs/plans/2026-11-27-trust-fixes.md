# Trust Fixes (Roadmap Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the holes that let something appear "checked" or "controlled" when it was not, in the engine, the reviewer site and the researcher site.

**Architecture:** Seven small, independent changes. Each one adds a failing test that reproduces a problem found in the 2026-11-27 review, then the smallest code change that makes it pass. No new modules, no database layout change, no new dependencies.

**Tech Stack:** Python 3.11+ with pytest (backend, run from `lab-factory/`); plain browser JavaScript with Playwright (reviewer site, run from the repository root); Next.js with `node --test` and Playwright (researcher site, run from `lab-factory/web/`).

**Spec:** `lab-factory/docs/specs/2026-11-25-lab-factory-architecture-design.md`, sections "Anti-goals" and "What a release certifies". The problems being fixed are described in plain terms in `lab-factory/docs/plain-language-guide.md`, section 5.

**For the owner, in plain terms:** each task below starts with a "Why" line. A "test" is a small program that checks the real program. Every task first writes a test that fails because of the problem, then fixes the problem, then shows the test passing. That order proves the fix really fixes it.

## Global Constraints

- "Unchecked values presented as checked" is an anti-goal: a person sees instrument values only as the factory renders them from checked settings.
- "Silent passes" is an anti-goal: an unknown or unverifiable input is a failure, never a skip.
- No agent-facing code path may approve or release.
- Backend runtime dependencies stay as they are in `lab-factory/pyproject.toml`; the only dev dependency is `pytest`.
- `requires-python = ">=3.11"`: no syntax or library newer than Python 3.11.
- The backend never imports from the top-level `factory/` package.
- No change to the SQLite table definitions in `lab-factory/src/labfactory/store.py`.
- Never weaken, skip or delete an existing test. All 340 backend tests must still pass after every task.
- Work on branch `claude/wonderful-carson-obkjh5`. One commit per task.

## Review Focus

Situations the tasks' main tests would otherwise miss, most likely first. Each has a test in the task named.

1. **A reviewer opens the original spreadsheet in a spreadsheet program and saves it again.** Line endings, quoting and number formatting (`10` becomes `10.0`) all change. It must still count as the original batch. (Task 2)
2. **Records saved before these fixes.** Old run receipts have no `intake_csv_digest` and may have no `control.source`. The reviewer site must still show them, labelled as not recorded, not crash. (Task 5)
3. **A control exactly at the lowest or highest standard, or standards listed high-to-low.** Limits are inclusive, so it must be accepted. (Task 3)
4. **Padding made of unusual blank characters** (non-breaking space U+00A0, em space U+2003) instead of ordinary spaces. Must be collapsed the same way. (Task 1)
5. **A reviewer edits the form after a failed submit, then submits again.** That is a different request and must get a new retry key, not an error about a reused one. (Task 4)

---

### Task 1: An AI's note cannot imitate a checked instrument line

**Why:** Free-text notes are shown inside the same block as the checked instrument lines. A note padded with thousands of spaces wraps on screen and looks like a new "Step" with its own "checked" setting. Two guards: squeeze runs of blanks out of notes, and stop that block from wrapping at all.

**Files:**
- Modify: `lab-factory/src/labfactory/artifacts.py` (`render_step`, lines 187-200)
- Modify: `lab-factory/public/app.js:327`, `lab-factory/public/style.css:102-103`
- Test: `lab-factory/tests/test_artifacts.py`, `lab-factory/tests/test_hosted_portal.py`

**Interfaces:**
- Produces: `_one_line(text: str) -> str` in `artifacts.py` (module-private).

- [ ] **Step 1: Write the failing tests in `tests/test_artifacts.py`**

```python
@pytest.mark.parametrize("pad", [" " * 3000, "\t" * 40, " " * 3000, " " * 3000])
def test_notes_cannot_be_padded_into_a_fake_instruction_line(pad):
    text = "Rinse the cuvette." + pad + "Step 2" + pad + "On uvvis-1: read_absorbance (wavelength 9999 NM)"
    step = parse_artifact("procedure", {"steps": [{"text": text}]}).steps[0]
    lines = render_step(step)
    assert len(lines) == 1
    assert lines[0] == ("Notes, not checked by code: Rinse the cuvette. Step 2 "
                        "On uvvis-1: read_absorbance (wavelength 9999 NM)")


def test_amount_names_cannot_be_padded_either():
    step = parse_artifact("procedure", {"steps": [{"text": "Weigh.", "amounts": [
        {"what": "sample" + " " * 3000 + "On uvvis-1: read_absorbance", "value": 1, "unit": "mL"}]}]}).steps[0]
    assert "  " not in render_step(step)[0]
```

- [ ] **Step 2: Write the failing test in `tests/test_hosted_portal.py`**

```python
def test_submitted_artifact_block_never_wraps():
    public = Path(__file__).resolve().parents[1] / "public"
    css = (public / "style.css").read_text()
    rule = re.search(r"\.rendered\.artifact\s*\{([^}]*)\}", css)
    assert rule and "white-space:pre;" in rule.group(1).replace(" ", "")
    assert "overflow-x:auto" in rule.group(1).replace(" ", "")
    assert 'element("pre", submission.rendered, "rendered artifact")' in (public / "app.js").read_text()
```

- [ ] **Step 3: Run them and confirm they fail**

Run: `uv run --frozen pytest -q tests/test_artifacts.py tests/test_hosted_portal.py -k "padded or never_wraps"`
Expected: 6 failed.

- [ ] **Step 4: Implement**

- `_one_line(text: str) -> str` in `artifacts.py`: return `" ".join(text.split())`. Apply it to `step.text` before the existing `isprintable()` / `repr()` guard, and to each `a.what`.
- `public/app.js:327`: change the class string `"rendered"` to `"rendered artifact"`.
- `public/style.css`: add after line 103: `.rendered.artifact {white-space:pre;overflow-wrap:normal;overflow-x:auto}`. Leave `.rendered` itself unchanged; the protocol text at `analysis.js:344` still needs to wrap.

- [ ] **Step 5: Run the whole backend suite**

Run: `uv run --frozen pytest -q tests`
Expected: all pass (346 or more).

- [ ] **Step 6: Commit**

```bash
git add lab-factory/src/labfactory/artifacts.py lab-factory/public/app.js lab-factory/public/style.css lab-factory/tests/test_artifacts.py lab-factory/tests/test_hosted_portal.py
git commit -m "fix(lab-factory): keep notes from imitating a checked instrument line"
```

---

### Task 2: The same readings are the same batch, however the file was saved

**Why:** The engine decides "is this the original batch?" by fingerprinting the file's raw bytes. Saving the same spreadsheet again changes the bytes, so a failed original can be re-uploaded as a "new" batch with any control value. Compare the measurements instead of the bytes, and write the original file's fingerprint into every receipt so a run can always be traced back.

**Files:**
- Modify: `lab-factory/src/labfactory/tabular_service.py` (`_execution_batch` lines 388-407; receipt in `run` lines 450-458)
- Test: `lab-factory/tests/test_tabular_service.py`

**Interfaces:**
- Produces: `_content_key(batch: dict, control: dict) -> str` in `tabular_service.py`. `batch` is the dict `_batch` returns; `control` is the dict `_control` returns.
- Produces: receipt field `"intake_csv_digest": str` (the `csv_digest` of the order's original batch) on every new run receipt.

- [ ] **Step 1: Write the failing tests**

```python
def _released_with_failing_original(store, request_data):
    """Original control is wrong for the final method, so the original batch is withheld."""
    request_data["control_expected"] = 6.0
    key = _create(store, request_data)
    orders = WorkOrders(store)
    orders.claim(key, "Writer")
    assert not orders.submit(key, "Writer", _artifact(2)).passed
    svc.replace_control(store, key, "R", {"signal": 40, "factor": 1, "expected": 4, "tolerance": .02})
    assert orders.submit(key, "Writer", _artifact()).passed
    orders.approve(key, "R", 2)
    return key


RESAVED = {
    "unix line endings": lambda csv: csv.replace("\r\n", "\n"),
    "no byte-order mark": lambda csv: csv.lstrip("﻿"),
    "trailing blank line": lambda csv: csv + "\r\n",
    "numbers quoted": lambda csv: csv.replace("s1,standard,10,1,1", 's1,standard,"10","1","1"'),
    "numbers reformatted": lambda csv: csv.replace("s1,standard,10,1,1", "s1,standard,10.0,1.00,1"),
    "rows reordered": lambda csv: "\r\n".join(
        [csv.split("\r\n")[0], *reversed(csv.rstrip("\r\n").split("\r\n")[1:])]) + "\r\n",
    "samples renamed": lambda csv: csv.replace('"unknown,trial A"', "renamed-vial"),
}


@pytest.mark.parametrize("resave", RESAVED.values(), ids=RESAVED.keys())
def test_resaved_original_cannot_take_a_new_control(store, request_data, resave):
    key = _released_with_failing_original(store, request_data)
    original = svc.run(store, key, "R", {"submission": 2})
    assert original["status"] == "withheld"
    resaved = dict(submission=2, csv_name="again.csv", csv=resave(request_data["csv"]))
    with pytest.raises(WorkOrderError, match="already pinned"):
        svc.run(store, key, "R", {**resaved, "control_expected": 5.392, "control_tolerance": 1000})
    same = svc.run(store, key, "R", {**resaved, "control_expected": 6.0,
                                     "control_tolerance": request_data["control_tolerance"]})
    assert same == original


def test_a_new_batch_cannot_be_resaved_for_a_second_control(store, request_data):
    key = _released_with_failing_original(store, request_data)
    csv = request_data["csv"].replace("70.123", "80.5")
    new = dict(submission=2, csv_name="b.csv", csv=csv, control_expected=5.392, control_tolerance=.0137)
    first = svc.run(store, key, "R", new)
    assert first["control"]["source"] == "uploaded batch"
    with pytest.raises(WorkOrderError, match="already has a pinned control"):
        svc.run(store, key, "R", {**new, "csv": csv.replace("\r\n", "\n"), "control_tolerance": 1000})


def test_every_receipt_names_the_original_file(store, request_data):
    key = _released_with_failing_original(store, request_data)
    _, intake = svc._intake(store, key)
    csv = request_data["csv"].replace("70.123", "80.5")
    run = svc.run(store, key, "R", dict(submission=2, csv_name="b.csv", csv=csv,
                                        control_expected=5.392, control_tolerance=.0137))
    assert run["intake_csv_digest"] == intake["csv_digest"] != run["csv_digest"]
    assert svc.run(store, key, "R", {"submission": 2})["intake_csv_digest"] == intake["csv_digest"]
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `uv run --frozen pytest -q tests/test_tabular_service.py -k "resaved or names_the_original"`
Expected: 9 failed (the "already pinned" error is not raised; `intake_csv_digest` is missing).

- [ ] **Step 3: Implement `_content_key` and use it**

`_content_key` fingerprints only what was measured, ignoring file name, sample IDs, row order and text formatting:

```python
def _content_key(batch, control):
    return canonical_digest({
        "standards": sorted(batch["standards"]),
        "unknowns": sorted([row["signal"], row["factor"]] for row in batch["unknowns"]),
        "control": [control["signal"], control["factor"]],
    })
```

In `_execution_batch`:
- Load the edition-1 control before the comparison.
- Treat the upload as the original batch when `_content_key(uploaded, uploaded_control) == _content_key(original, original_control)`, in place of the `csv_digest` comparison. In that case keep the existing rule: a different `expected` or `tolerance` raises "This is the original batch; its control and tolerance are already pinned."; otherwise return `original, original_control, {"source": "original batch", "edition": 1}`.
- For a genuinely new batch, pin its control under `(order_id, _content_key(uploaded, uploaded_control))`. Store that key in the existing `csv_digest` column of `tabular_batch_controls`; no table change. Add a one-line comment saying the column now holds the content key, and that rows written before this change no longer match (such a batch can be pinned once more).

In `run`, add `"intake_csv_digest": <csv_digest of the order's intake batch>` to the receipt dict. Capture it before `batch` is reassigned by `_execution_batch`.

- [ ] **Step 4: Run the tabular tests, then the whole suite**

Run: `uv run --frozen pytest -q tests/test_tabular_service.py tests/test_tabular_acceptance.py` then `uv run --frozen pytest -q tests`
Expected: all pass. `test_original_batch_qc_withholds_after_a_passing_replacement_and_checks_exact_reuploads` must pass unchanged.

- [ ] **Step 5: Document the new receipt field**

In `lab-factory/docs/analysis-api.md`, in the row for `POST /api/analysis/orders/{id}/runs`, add: "Each receipt carries `intake_csv_digest`, the SHA-256 of the order's original readings file. A re-saved copy of the original file is treated as the original batch."

- [ ] **Step 6: Commit**

```bash
git add lab-factory/src/labfactory/tabular_service.py lab-factory/tests/test_tabular_service.py lab-factory/docs/analysis-api.md
git commit -m "fix(lab-factory): identify a batch by its measurements, not its file bytes"
```

---

### Task 3: A control must sit inside the range the standards cover

**Why:** When the "range gate" is on, the engine refuses to estimate anything outside the lowest-to-highest standard. A control outside that range can never pass, yet it is accepted at upload. It then burns the one-time blind check and leaves the batch impossible to run. Refuse it at the door, with a clear message.

**Files:**
- Modify: `lab-factory/src/labfactory/tabular_service.py` (`_batch` lines 79-125; `replace_control` lines 335-349)
- Test: `lab-factory/tests/test_tabular_service.py`

**Interfaces:**
- Produces: `_require_control_in_range(standards: list, signal: float) -> None`; raises `ContextError("The control signal must lie inside the range of the standard signals.")`.

- [ ] **Step 1: Write the failing tests**

```python
MESSAGE = "inside the range of the standard signals"


@pytest.mark.parametrize("area", ["9.99", "100.01", "500"])
def test_control_outside_the_standards_is_refused_at_upload(store, request_data, area):
    request_data["csv"] = request_data["csv"].replace("53.92", area)
    with pytest.raises(ContextError, match=MESSAGE):
        _create(store, request_data)


@pytest.mark.parametrize("area", ["10", "100"])
def test_control_on_the_edge_of_the_range_is_accepted(store, request_data, area):
    request_data["csv"] = request_data["csv"].replace("53.92", area)
    assert _create(store, request_data).startswith("WO-")


def test_standards_listed_high_to_low_are_fine(store, request_data):
    request_data["csv"] = request_data["csv"].replace(
        "s1,standard,10,1,1\r\ns2,standard,100,10,1", "s2,standard,100,10,1\r\ns1,standard,10,1,1")
    assert _create(store, request_data).startswith("WO-")


def test_range_check_is_off_when_the_range_gate_is_off(store, request_data):
    request_data.update(range_gate=False, csv=request_data["csv"].replace("53.92", "500"))
    assert _create(store, request_data).startswith("WO-")


def test_replacement_control_outside_the_standards_is_refused(store, request_data):
    key = _create(store, request_data)
    orders = WorkOrders(store)
    orders.claim(key, "Writer")
    assert not orders.submit(key, "Writer", _artifact(2)).passed
    with pytest.raises(ContextError, match=MESSAGE):
        svc.replace_control(store, key, "R", {"signal": 500, "factor": 1, "expected": 50, "tolerance": .02})
```

- [ ] **Step 2: Run them and confirm the three "refused" tests fail**

Run: `uv run --frozen pytest -q tests/test_tabular_service.py -k "control_outside or edge_of or high_to_low or range_gate_is_off or replacement_control_outside"`
Expected: 4 failed, 4 passed.

- [ ] **Step 3: Implement**

`_require_control_in_range` compares `signal` with the minimum and maximum standard signal, inclusive, matching `tabular_analysis.py:171-174`. Call it in `_batch` when `range_gate` is true, after the "at least two distinct standard signals" check. In `replace_control`, read `profile, batch = _intake(store, order_id)` and call it with `batch["standards"]` when `profile["range_gate"]` is true.

- [ ] **Step 4: Run the whole suite**

Run: `uv run --frozen pytest -q tests`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add lab-factory/src/labfactory/tabular_service.py lab-factory/tests/test_tabular_service.py
git commit -m "fix(lab-factory): refuse a control outside the calibration range at upload"
```

---

### Task 4: Clicking "Request analysis" twice cannot create two orders

**Why:** If the network drops the reply, the reviewer sees an error and clicks again, and the engine creates a second order. The engine already supports a "retry key" (`request_id`): send the same key twice and it returns the first order. The reviewer site just never sends one.

**Files:**
- Modify: `lab-factory/public/analysis.js` (the new-analysis form, lines 200-258)
- Create: `tests/integrated/analysis.spec.mjs` (repository root)

**Interfaces:**
- Consumes: backend `request_id` handling in `tabular_service.create_order` (already present).

- [ ] **Step 1: Write the failing browser test**

```js
import { expect, test } from "playwright/test";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

async function loadCaffeineExample(page) {
  await page.goto("/#analysis/new");
  await page.getByLabel("Example dataset").selectOption("caffeine");
  await page.getByRole("button", { name: "Load example files" }).click();
  await expect(page.getByRole("button", { name: "Request analysis" })).toBeEnabled();
}

test("a retried analysis request reuses its key and creates one order", async ({ page }) => {
  const sent = [];
  let dropFirstReply = true;
  await page.route("**/api/analysis/orders", async route => {
    if (route.request().method() !== "POST") return route.continue();
    sent.push(route.request().postDataJSON());
    if (dropFirstReply) {
      dropFirstReply = false;
      await route.fetch();          // the server creates the order
      return route.abort();         // the browser never hears back
    }
    return route.continue();
  });
  await loadCaffeineExample(page);
  await page.getByRole("button", { name: "Request analysis" }).click();
  await expect(page.getByRole("button", { name: "Request analysis" })).toBeEnabled();
  await page.getByRole("button", { name: "Request analysis" }).click();
  await expect(page).toHaveURL(/#order\/WO-1$/);
  expect(sent).toHaveLength(2);
  expect(sent[0].request_id).toMatch(UUID);
  expect(sent[1].request_id).toBe(sent[0].request_id);
  const orders = await (await page.request.get("/api/orders")).json();
  expect(orders.filter(order => order.kind === "analysis_app")).toHaveLength(1);
});

test("editing the form after a failure starts a new request", async ({ page }) => {
  const sent = [];
  await page.route("**/api/analysis/orders", async route => {
    if (route.request().method() !== "POST") return route.continue();
    sent.push(route.request().postDataJSON());
    return sent.length === 1 ? route.abort() : route.continue();
  });
  await loadCaffeineExample(page);
  await page.getByRole("button", { name: "Request analysis" }).click();
  await page.getByLabel("Objective").fill("A different objective");
  await page.getByRole("button", { name: "Request analysis" }).click();
  await expect(page).toHaveURL(/#order\/WO-\d+$/);
  expect(sent[1].request_id).toMatch(UUID);
  expect(sent[1].request_id).not.toBe(sent[0].request_id);
});
```

The label text ("Example dataset", "Objective"), the example's option value and the order-page address pattern must match what `analysis.js` and `app.js` actually render; correct the selectors, and how the order list is read from the `/api/orders` reply, to the real ones. Do not change what is asserted about `sent` or the rule that exactly one analysis order exists.

- [ ] **Step 2: Run it and confirm it fails**

From the repository root (first time only: `npm ci`, `npm run build:lab`, and `uv sync --locked` inside `lab-factory/`):

Run: `npm run test:lab -- analysis.spec.mjs --trace off`
Expected: FAIL, `sent[0].request_id` is undefined.

- [ ] **Step 3: Implement in `public/analysis.js`**

In the function that builds the new-analysis form: `let requestId = crypto.randomUUID();`, a `form.addEventListener("input", () => { requestId = crypto.randomUUID(); })` (and the same reset when "Load example files" finishes), and `request_id: requestId` in the payload at line 250.

- [ ] **Step 4: Run both integrated specs**

Run: `npm run test:lab -- --trace off`
Expected: 3 passed (the existing navigation test and the two new ones).

- [ ] **Step 5: Commit**

```bash
git add lab-factory/public/analysis.js tests/integrated/analysis.spec.mjs
git commit -m "fix(lab-factory): send a retry key when requesting an analysis"
```

---

### Task 5: A result card says which control it was judged against

**Why:** Today a run judged against a control the reviewer typed in at upload looks identical to a run judged against the original, sealed control. And the card says "Completed" for any status it does not recognise. Show the control's origin and value on the card itself, link to the exact readings file, and treat anything unrecognised as withheld.

**Files:**
- Modify: `lab-factory/public/analysis.js` (`tabularRuns`, lines 420-449)
- Modify: `tests/integrated/analysis.spec.mjs`

**Interfaces:**
- Consumes: receipt fields `status`, `control.source` (`"original batch"` or `"uploaded batch"`), `control.expected`, `control.tolerance`, `control.unit`, `intake_csv_digest` (Task 2), and the existing download route `GET /api/analysis/orders/{id}/runs/{run_id}/readings`.

- [ ] **Step 1: Write the failing browser test**

Append to `tests/integrated/analysis.spec.mjs`. The test creates a real order, then adds three made-up runs to the order-detail reply so the card can be checked without an AI worker:

```js
const RUNS = [
  { id: 1, csv_name: "original.csv", status: "estimated", submission: 1, results: [],
    control: { source: "original batch", edition: 1, passed: true, expected: 16, tolerance: 0.5, unit: "mg/L" } },
  { id: 2, csv_name: "second.csv", status: "estimated", submission: 1, results: [],
    control: { source: "uploaded batch", passed: true, expected: 99, tolerance: 1000, unit: "mg/L" } },
  { id: 3, csv_name: "old.csv", status: "something-new", submission: 1, results: [] },
];

test("each result card shows where its control came from and fails closed", async ({ page }) => {
  await loadCaffeineExample(page);
  await page.getByRole("button", { name: "Request analysis" }).click();
  await expect(page).toHaveURL(/#order\/WO-\d+$/);
  const id = page.url().split("/").pop();
  await page.route(`**/api/analysis/orders/${id}`, async route => {
    const reply = await route.fetch();
    const body = await reply.json();
    // Put RUNS wherever analysis.js reads the list it passes to tabularRuns().
    body.runs = RUNS;
    return route.fulfill({ response: reply, json: body });
  });
  await page.reload();
  const cards = page.locator("article.dataset");
  await expect(cards).toHaveCount(3);
  await expect(cards.nth(0)).toContainText("Control: original batch, 16 ± 0.5 mg/L");
  await expect(cards.nth(0)).toContainText("Completed");
  await expect(cards.nth(1)).toContainText("Control: entered with this upload, 99 ± 1000 mg/L");
  await expect(cards.nth(2)).toContainText("Control: not recorded");
  await expect(cards.nth(2)).toContainText("Withheld");
  await expect(cards.nth(2)).not.toContainText("Completed");
  await expect(cards.nth(1).getByRole("link", { name: "Download these readings" }))
    .toHaveAttribute("href", `/api/analysis/orders/${id}/runs/2/readings`);
});
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `npm run test:lab -- analysis.spec.mjs --trace off`
Expected: the new test fails on the first "Control:" assertion.

- [ ] **Step 3: Implement in `tabularRuns`**

- Status: show "Completed" only when `run.status === "estimated"`; every other value shows "Withheld" with the `failed` style.
- Directly under the title, always visible (not inside the collapsed details), a line built with `textContent`:
  - `control.source === "original batch"`: `Control: original batch, <expected> ± <tolerance> <unit>`
  - `control.source === "uploaded batch"`: `Control: entered with this upload, <expected> ± <tolerance> <unit>`
  - no `control` or any other source: `Control: not recorded`
- A link "Download these readings" to `/api/analysis/orders/<order id>/runs/<run id>/readings`, built with the existing link helper and `encodeURIComponent` on both IDs.
- In the provenance list, add "Original file SHA-256" showing `run.intake_csv_digest` when present.

- [ ] **Step 4: Run the integrated specs**

Run: `npm run test:lab -- --trace off`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add lab-factory/public/analysis.js tests/integrated/analysis.spec.mjs
git commit -m "fix(lab-factory): show each run's control origin and fail closed on unknown status"
```

---

### Task 6: The researcher site really sends the rule that keeps analysis code off the network

**Why:** The researcher site promises "Readings stay in your browser." It tries to enforce that by removing network functions one by one inside the locked room (the worker), and one was missed. The dependable guard is a browser rule (a security header) saying "this page may only talk to its own server." The README asks the host to send it, but the site's own hosting file does not. Send it, and run the browser tests with it switched on so we know the site works under it.

**Files:**
- Modify: `lab-factory/web/vercel.json`
- Create: `lab-factory/web/scripts/serve-out.mjs`, `lab-factory/web/lib/hosting.test.ts`, `lab-factory/web/e2e/network-boundary.spec.ts`
- Modify: `lab-factory/web/playwright.config.ts:17-20`, `lab-factory/web/README.md:29-31`

**Interfaces:**
- Produces: `vercel.json` `headers` entry for source `/(.*)` with `Content-Security-Policy: connect-src 'self'; font-src 'self'`.
- Produces: `node scripts/serve-out.mjs <port>`: serves `out/` on `127.0.0.1:<port>` and applies every header listed in `vercel.json`.

- [ ] **Step 1: Write the failing unit test `lib/hosting.test.ts`**

```ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

test("the host sends the rule that keeps analysis code off the network", () => {
  const config = JSON.parse(readFileSync(new URL("../vercel.json", import.meta.url), "utf8"));
  const rule = config.headers.find((entry: { source: string }) => entry.source === "/(.*)");
  const policy = rule.headers.find((h: { key: string }) => h.key === "Content-Security-Policy");
  assert.equal(policy.value, "connect-src 'self'; font-src 'self'");
});
```

- [ ] **Step 2: Write the failing browser test `e2e/network-boundary.spec.ts`**

```ts
import { expect, test } from "@playwright/test";

test("every page and the Python worker are served with the network rule", async ({ request }) => {
  for (const path of ["/", "/runtime/python-worker.mjs"]) {
    const reply = await request.get(path);
    expect(reply.headers()["content-security-policy"]).toBe("connect-src 'self'; font-src 'self'");
  }
});

test("the browser refuses a request to any other server", async ({ page }) => {
  await page.goto("/");
  const blocked = await page.evaluate(() => new Promise<string>(resolve => {
    document.addEventListener("securitypolicyviolation", event => resolve(event.effectiveDirective));
    fetch("http://127.0.0.1:9/leak").catch(() => {});
  }));
  expect(blocked).toBe("connect-src");
});
```

- [ ] **Step 3: Run both and confirm they fail**

Run: `npm run test:unit` and `npm run build && npm run test:e2e -- network-boundary --trace off`
Expected: the unit test fails (`headers` is undefined); both browser tests fail (no header).

- [ ] **Step 4: Implement**

- `vercel.json`: add the `headers` entry from the Interfaces block.
- `scripts/serve-out.mjs`: a static file server using only Node's built-in `node:http`, `node:fs` and `node:path`. Serve `index.html` for a directory, return 404 for anything resolving outside `out/`, set the usual content types (`.html`, `.js`, `.mjs`, `.css`, `.json`, `.wasm`, `.svg`, `.woff2`, `.txt`, `.py`, `.zip`), and add the `vercel.json` headers to every reply.
- `playwright.config.ts`: change the `webServer.command` to `node scripts/serve-out.mjs ${port}`.
- `README.md:29-31`: replace "The host should send" with "`vercel.json` sends", and add that live mode will need the backend's origin added to `connect-src`.

Do not add `script-src` to the policy: the Next.js export uses inline start-up scripts that a `script-src 'self'` rule would block.

- [ ] **Step 5: Run every researcher-site suite**

Run: `npm run typecheck && npm run test:unit && npm run test:py && npm run build && npm run test:e2e -- --trace off`
Expected: all pass, including the full existing browser suite, now served with the header.

- [ ] **Step 6: Commit**

```bash
git add lab-factory/web/vercel.json lab-factory/web/scripts/serve-out.mjs lab-factory/web/lib/hosting.test.ts lab-factory/web/e2e/network-boundary.spec.ts lab-factory/web/playwright.config.ts lab-factory/web/README.md
git commit -m "fix(lab-factory/web): send and test the header that keeps analysis code off the network"
```

---

### Task 7: The backend's source bundle contains only the backend

**Why:** Bundling the backend for installation ("building the package") currently sweeps up the researcher site's downloaded libraries: a 199 MB file with 16,832 entries where about 1 MB is expected. Tell the bundler exactly what belongs, and have the robot that runs the tests (CI) build the bundle every time so this cannot creep back.

**Files:**
- Modify: `lab-factory/pyproject.toml`
- Modify: `.github/workflows/lab-factory-backend.yml`

- [ ] **Step 1: Run the check and confirm it fails**

From `lab-factory/`, after `npm ci` has been run in `lab-factory/web/` (so the stray files exist):

```bash
rm -rf /tmp/lf-dist && uv build --out-dir /tmp/lf-dist && tar tzf /tmp/lf-dist/labfactory-0.1.0.tar.gz | grep -c "/web/"
```

Expected: a count in the thousands.

- [ ] **Step 2: Add an explicit source-bundle list to `pyproject.toml`**

```toml
[tool.hatch.build.targets.sdist]
include = [
    "/src/labfactory",
    "/src/lab_codex_worker",
    "/examples",
    "/public/examples",
    "/tests",
    "/README.md",
]
```

`/public/examples` is needed because `examples/tabular` is a link into it.

- [ ] **Step 3: Run the check again**

```bash
rm -rf /tmp/lf-dist && uv build --out-dir /tmp/lf-dist
tar tzf /tmp/lf-dist/labfactory-0.1.0.tar.gz | grep -c "/web/\|/benchmarks/\|/public/evolve/"   # expected: 0
test "$(stat -c %s /tmp/lf-dist/labfactory-0.1.0.tar.gz)" -lt 2000000 && echo small           # expected: small
unzip -l /tmp/lf-dist/labfactory-0.1.0-py3-none-any.whl | grep -c "reference_data/.*\.json"   # expected: 24
```

`uv build` builds the installable file (the wheel) from the source bundle, so a successful build also proves nothing needed was left out.

- [ ] **Step 4: Make CI build the bundle**

In `.github/workflows/lab-factory-backend.yml`, after the pytest step, add:

```yaml
      - name: Build the package and check its size
        run: |
          uv build --out-dir "$RUNNER_TEMP/dist"
          test "$(stat -c %s "$RUNNER_TEMP"/dist/labfactory-*.tar.gz)" -lt 2000000
          uv run --no-project --with "$RUNNER_TEMP"/dist/labfactory-*.whl python -c "import labfactory.hosted, labfactory.references as r; assert r.catalog()"
```

- [ ] **Step 5: Run the backend suite, then commit**

Run: `uv run --frozen pytest -q tests`
Expected: all pass.

```bash
git add lab-factory/pyproject.toml .github/workflows/lab-factory-backend.yml
git commit -m "build(lab-factory): list the source bundle's contents and build it in CI"
```

---

## After the last task

- [ ] Run everything once more: backend `uv run --frozen pytest -q tests` (from `lab-factory/`); reviewer site `npm run test:lab -- --trace off` (from the root); researcher site `npm run typecheck && npm run test:unit && npm run test:py && npm run build && npm run test:e2e -- --trace off` (from `lab-factory/web/`).
- [ ] In `lab-factory/docs/plain-language-guide.md` section 6, change Phase 1's status to "Done", and move the three fixed problems in section 5 from "Not right yet" to "Working well".

## Deliberately left for later phases

- A limit on how loose a new batch's control tolerance may be (needs a scientific rule from the owner).
- Sign-in rate limiting, and stopping one person from both submitting and approving (Phase 3, with identities).
- The reference-search wording bug that skips the oven warning (Phase 3).
- Giving each analysis run in the researcher site a fresh interpreter (Phase 4, once that site runs real code).
- Which of the three hosting files each Vercel project uses (Phase 2 decision; needs the Vercel dashboard).
