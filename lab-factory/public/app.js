"use strict";

const byId = (id) => document.getElementById(id);
const workspace = byId("workspace");
const statuses = {open: "Open", in_progress: "In progress", in_review: "In review", released: "Released"};
const kinds = {run_plan: "Run plan", procedure: "Procedure", analysis_app: "B12 analysis app"};
let reviewer = null;
let agentNames = [];
let generation = 0;
let filter = "all";
let decision = null;

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function button(label, className, action) {
  const node = element("button", label, className);
  node.type = "button";
  node.addEventListener("click", action);
  return node;
}

function panel(title) {
  const section = element("section", undefined, "panel");
  const head = element("div", undefined, "section-bar");
  head.append(element("h2", title));
  section.append(head);
  return section;
}

function status(text, value) {
  return element("span", text, "status " + value);
}

function notify(message, isError = false) {
  const bar = byId("notice");
  bar.hidden = !message;
  bar.classList.toggle("error", isError);
  bar.textContent = message;
}

function showSignin() {
  generation++;
  reviewer = null;
  agentNames = [];
  decision = null;
  filter = "all";
  for (const modal of document.querySelectorAll("dialog[open]")) modal.close();
  for (const form of document.forms) form.reset();
  for (const error of document.querySelectorAll(".form-error")) error.hidden = true;
  for (const id of ["decision-summary", "decision-title", "decision-digest", "decision-submit"]) {
    byId(id).textContent = "";
  }
  workspace.replaceChildren();
  byId("user-name").textContent = "";
  for (const node of [workspace, byId("nav"), byId("account"), byId("loading")]) node.hidden = true;
  byId("portal-label").hidden = false;
  byId("signin").hidden = false;
  document.title = "Reviewer sign-in · Lab Factory";
}

async function api(path, options = {}) {
  const headers = {Accept: "application/json"};
  if (options.method === "POST") headers["Content-Type"] = "application/json";
  const response = await fetch("/api/" + path, {
    credentials: "same-origin", cache: "no-store", ...options, headers,
  });
  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error("Workspace unavailable (HTTP " + response.status + "). Please retry.");
  }
  if (response.status === 401 && reviewer) {
    showSignin();
    notify("Your session expired. Sign in again.", true);
  }
  if (!response.ok) throw new Error(data.error || "Request failed (HTTP " + response.status + ").");
  return data;
}

const post = (path, payload) => api(path, {method: "POST", body: JSON.stringify(payload)});

function formError(form, message) {
  const error = form.querySelector(".form-error");
  if (!error) return;
  error.hidden = !message;
  error.textContent = message;
}

function handleForm(form, action) {
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const submit = form.querySelector("button[type=submit]");
    if (submit.disabled) return;
    submit.disabled = true;
    formError(form, "");
    const modal = form.closest("dialog");
    if (modal) for (const close of modal.querySelectorAll("[data-close]")) close.disabled = true;
    try {
      await action(new FormData(form));
    } catch (error) {
      formError(form, error.message);
    } finally {
      submit.disabled = false;
      if (modal) for (const close of modal.querySelectorAll("[data-close]")) close.disabled = false;
    }
  });
}

function openForm(dialog) {
  const form = dialog.querySelector("form");
  form.reset();
  formError(form, "");
  dialog.showModal();
}

function refreshButton() {
  return button("Refresh", "secondary", () => navigate());
}

function actions(...items) {
  const bar = element("div", undefined, "page-actions");
  bar.append(...items);
  return bar;
}

function heading(title, ...controls) {
  const row = element("div", undefined, "title-row");
  row.append(element("h1", title), actions(...controls));
  return row;
}

function table(headings) {
  const wrapper = element("div", undefined, "table-wrap");
  const grid = element("table");
  const row = grid.createTHead().insertRow();
  for (const title of headings) {
    const th = element("th", title);
    th.scope = "col";
    row.append(th);
  }
  const body = grid.createTBody();
  wrapper.append(grid);
  return {wrapper, grid, body};
}

function definition(list, name, value, className) {
  const group = element("div", undefined, className);
  group.append(element("dt", name), element("dd", value));
  list.append(group);
}

function linkToOrder(id) {
  const link = element("a", id, "order-link");
  link.href = "#order/" + encodeURIComponent(id);
  link.setAttribute("aria-label", "Review work order " + id);
  return link;
}

function openOrder(id) {
  const hash = "#order/" + encodeURIComponent(id);
  if (location.hash === hash) navigate();
  else location.hash = hash;
}

function showOrders(orders) {
  const mainHeading = heading("Work orders", refreshButton(),
    button("Create order", "primary", () => openForm(byId("create-dialog"))));
  const summary = element("dl", undefined, "stats");
  for (const [key, label] of Object.entries(statuses)) {
    definition(summary, label, orders.filter((order) => order.status === key).length, "stat");
  }

  const list = panel("Order queue");
  const select = element("select");
  const selectLabel = element("label", "Status");
  for (const [value, label] of Object.entries({all: "All statuses", ...statuses})) {
    const option = element("option", label);
    option.value = value;
    select.append(option);
  }
  select.value = filter;
  selectLabel.append(select);
  list.firstChild.append(selectLabel);
  const results = element("div");
  list.append(results);
  function renderRows() {
    const selected = orders.filter((order) => filter === "all" || order.status === filter);
    if (!selected.length) {
      results.replaceChildren(element("p", orders.length ? "No orders with this status." : "No work orders yet.", "empty"));
      return;
    }
    const {wrapper, grid, body} = table(["Order", "Artifact", "Objective", "Worker", "Status"]);
    grid.classList.add("orders-table");
    for (const order of selected.slice().reverse()) {
      const row = body.insertRow();
      row.insertCell().append(linkToOrder(order.id));
      row.insertCell().textContent = kinds[order.kind] || order.kind;
      const objective = row.insertCell();
      objective.className = "objective-cell";
      objective.textContent = order.objective;
      row.insertCell().textContent = order.worker || "Unclaimed";
      row.insertCell().append(status(statuses[order.status] || order.status, order.status));
    }
    results.replaceChildren(wrapper);
  }
  select.addEventListener("change", () => { filter = select.value; renderRows(); });
  renderRows();
  workspace.replaceChildren(mainHeading, summary, list);
  if (!orders.length) workspace.append(examplePanel());
}

function openDecision(kind, order, submission) {
  decision = {kind, order: order.id, number: submission.number, reviewer};
  const approve = kind === "approve";
  const label = approve ? "Approve submission" : "Reject submission";
  byId("decision-title").textContent = label + " " + submission.number + "?";
  byId("decision-summary").textContent = approve
    ? "Release " + order.id + " submission " + submission.number + " as " + reviewer + "."
    : "Reopen " + order.id + " as " + reviewer + " and send feedback on submission " + submission.number + " to the next worker.";
  byId("decision-digest").textContent = submission.artifact_digest;
  byId("reason-field").hidden = approve;
  byId("reason").required = !approve;
  byId("decision-submit").textContent = approve ? "Approve and release" : "Reject and reopen";
  byId("decision-submit").className = approve ? "primary" : "danger";
  openForm(byId("decision-dialog"));
}

function submissionView(order, submission, latest) {
  const section = element(latest ? "section" : "details", undefined, "panel submission");
  const title = "Submission " + submission.number;
  if (!latest) section.append(element("summary", title + " · " + submission.worker + (submission.passed ? " · Checks passed" : " · Checks failed")));
  if (latest) {
    const head = element("div", undefined, "submission-head");
    const name = element("h2", title);
    name.id = "latest-submission";
    name.tabIndex = -1;
    name.append(element("small", "by " + submission.worker));
    head.append(name, status(submission.passed ? "Checks passed" : "Checks failed", submission.passed ? "passed" : "failed"));
    section.append(head);
  }
  const body = element("div", undefined, "details-content");
  if (order.kind === "analysis_app") {
    const source = element("pre", undefined, "analysis-source");
    source.append(element("code", submission.artifact.source));
    body.append(element("h3", "Agent’s Python source"), source);
  } else {
    body.append(element("h3", "Submitted artifact"), element("pre", submission.rendered, "rendered"));
  }
  body.append(element("p", "Artifact SHA-256", "field-caption"), element("p", submission.artifact_digest, "digest mono"));
  body.append(element("h3", order.kind === "analysis_app" ? "Factory verification" : "Recorded checks"));
  const checks = element("ul", undefined, "checks");
  for (const check of submission.results) {
    const item = element("li");
    item.append(status(check.passed ? "Pass" : "Fail", check.passed ? "passed" : "failed"),
      element("span", check.name), element("span", check.detail, "check-detail"));
    checks.append(item);
  }
  body.append(checks);
  if (latest && order.status === "in_review" && submission.passed) {
    const buttons = element("div", undefined, "review-actions");
    buttons.append(button("Approve submission " + submission.number, "primary", () => openDecision("approve", order, submission)),
      button("Reject submission " + submission.number, "danger-outline", () => openDecision("reject", order, submission)));
    body.append(buttons);
  }
  section.append(body);
  return section;
}

function showOrder(data, assay) {
  const {order, submissions, history} = data;
  const back = element("div", undefined, "nav-back");
  const link = element("a", assay ? "← B12 analysis" : "← Work orders");
  link.href = assay ? "#b12" : "#orders";
  back.append(link);
  const statusLine = element("div", undefined, "order-title");
  statusLine.append(element("span", order.id), status(statuses[order.status], order.status));
  const meta = element("dl", undefined, "order-meta");
  definition(meta, "Artifact", kinds[order.kind] || order.kind);
  definition(meta, "Experiment", order.experiment_id + " · revision " + order.experiment_revision);
  definition(meta, "Lab", order.lab_id + " · revision " + order.lab_revision);
  definition(meta, "Worker", order.worker || "Unclaimed");
  workspace.replaceChildren(back, statusLine, heading(order.objective, refreshButton()), meta);
  if (assay) {
    workspace.append(readingEntry(order, assay));
    if (order.status === "released") workspace.append(readingResults(order, assay.readings));
  }
  const sorted = submissions.slice().sort((a,b) => b.number - a.number);
  if (!sorted.length) {
    const empty = panel("Submissions");
    empty.append(element("p", order.status === "open"
      ? "This order is open for an agent to claim." : "Waiting for the claiming agent to submit an artifact.", "empty"));
    if (assay) {
      const connect = element("a", "Connect a coding agent");
      connect.href = "#agents";
      const connection = element("div", undefined, "details-content");
      connection.append(connect);
      empty.append(connection);
    }
    workspace.append(empty);
  }
  sorted.forEach((submission, i) => workspace.append(submissionView(order, submission, i === 0)));
  const path = "orders/" + encodeURIComponent(order.id);
  const pageVersion = generation;
  let older = data.older_submission;
  if (older) {
    const previous = button("View earlier submission " + older, "secondary older", async () => {
      previous.disabled = true;
      try {
        const page = await api(path + "?submission=" + older);
        if (pageVersion !== generation) return;
        const detail = submissionView(order, page.submissions[0], false);
        detail.open = true;
        previous.before(detail);
        older = page.older_submission;
        if (older) previous.textContent = "View earlier submission " + older;
        else previous.remove();
      } catch (error) { if (pageVersion === generation) notify(error.message, true); }
      finally { previous.disabled = false; }
    });
    workspace.append(previous);
  }
  if (assay && order.status !== "released") workspace.append(readingResults(order, assay.readings));
  const events = panel("Order history");
  events.classList.add("history");
  const {wrapper, body} = table(["Event", "Actor", "Time", "Submission", "Note"]);
  function appendHistory(records) {
    for (const event of records.slice().reverse()) {
      const row = body.insertRow();
      for (const value of [event.event, event.actor, event.at, event.submission ?? "—", event.note || "—"]) {
        row.insertCell().textContent = value;
      }
    }
  }
  appendHistory(history);
  wrapper.tabIndex = 0;
  wrapper.setAttribute("role", "region");
  wrapper.setAttribute("aria-label", "Order history table");
  events.append(wrapper);
  let cursor = data.before_event;
  if (cursor) {
    const more = button("View earlier events", "secondary older", async () => {
      more.disabled = true;
      try {
        const page = await api(path + "?before_event=" + cursor);
        if (pageVersion !== generation) return;
        appendHistory(page.history);
        cursor = page.before_event;
        if (!cursor) more.remove();
      } catch (error) { if (pageVersion === generation) notify(error.message, true); }
      finally { more.disabled = false; }
    });
    events.append(more);
  }
  workspace.append(events);
}

function showB12(data) {
  const create = button("Start B12 example", "primary", async () => {
    const page = generation;
    create.disabled = true;
    try {
      const result = await post("b12/orders", {});
      if (page === generation) openOrder(result.id);
    } catch (error) { if (page === generation) notify(error.message, true); }
    finally { create.disabled = false; }
  });
  const list = panel("Analysis orders");
  if (data.orders.length) {
    const {wrapper, body} = table(["Order", "Objective", "Status"]);
    for (const order of data.orders.slice().reverse()) {
      const row = body.insertRow();
      row.insertCell().append(linkToOrder(order.id));
      row.insertCell().textContent = order.objective;
      row.insertCell().append(status(statuses[order.status], order.status));
    }
    list.append(wrapper);
  } else {
    list.append(element("p", "Start the B12 example to open your first analysis order.", "empty"));
  }
  workspace.replaceChildren(heading("Vitamin B12 analysis", refreshButton(), create),
    element("p", "Start a fresh review of the agent-written Python, or reopen an existing order. Each new example tests the source again before you approve it and calculate a concentration from simulated readings.", "assay-intro"), list);
}

function readingEntry(order, assay) {
  const section = panel("Simulated absorbance readings");
  const body = element("div", undefined, "panel-body assay-entry");
  const form = element("form");
  const caption = element("p", "Enter three replicate readings for the same simulated vial.", "muted");
  const fields = element("div", undefined, "replicates");
  const inputs = assay.sample_readings.map((value, index) => {
    const label = element("label", "Reading " + (index + 1) + " (AU)");
    const input = element("input");
    input.type = "number";
    input.name = "replicate";
    input.step = "any";
    input.required = true;
    input.placeholder = String(value);
    label.append(input);
    fields.append(label);
    return input;
  });
  const fill = button("Use example readings", "secondary", () => {
    inputs.forEach((input, i) => { input.value = assay.sample_readings[i]; });
    formError(form, "");
  });
  const save = element("button", "Save readings", "primary");
  save.type = "submit";
  const error = element("p", "", "form-error");
  error.hidden = true;
  error.setAttribute("role", "alert");
  form.append(caption, fields, error, actions(fill, save));
  const path = "b12/orders/" + encodeURIComponent(order.id) + "/readings";
  handleForm(form, async (values) => {
    const page = generation;
    const readings = values.getAll("replicate").map(Number);
    if (readings.length !== 3 || !readings.every(Number.isFinite)) throw new Error("Enter three finite numeric readings.");
    await post(path, {readings});
    if (page !== generation) return;
    await navigate();
    if (reviewer && location.hash === "#order/" + encodeURIComponent(order.id)) {
      notify("Readings saved for " + order.id + ".");
      const next = order.status === "in_review" ? byId("latest-submission") : byId("b12-datasets");
      next?.focus();
    }
  });
  const cal = assay.calibration;
  const calibration = element("aside", undefined, "assay-calibration");
  const label = element("h3", "Pinned calibration");
  const dl = element("dl", undefined, "calibration-data");
  definition(dl, "Wavelength", cal.wavelength_nm + " nm");
  definition(dl, "Calibrated interval", cal.min_au + "–" + cal.max_au + " AU");
  definition(dl, "Slope", cal.slope_au_per_mg_l + " AU per mg/L");
  definition(dl, "Intercept", cal.intercept_au + " AU");
  calibration.append(label, dl, element("p", cal.id, "mono calibration-id"));
  body.append(form, calibration);
  section.append(body);
  return section;
}

function readingResults(order, datasets) {
  const section = panel("Saved readings and results");
  section.id = "b12-datasets";
  section.tabIndex = -1;
  section.classList.add("space-top");
  if (!datasets.length) {
    section.append(element("p", "Save three readings above to add a dataset.", "empty"));
    return section;
  }
  for (const dataset of [...datasets].sort((a,b) => b.id - a.id)) {
    const body = element("article", undefined, "dataset panel-body");
    const caption = element("div", undefined, "dataset-head");
    caption.append(element("h3", "Dataset " + dataset.id),
      element("span", dataset.actor + " · " + dataset.created_at, "dataset-byline"));
    body.append(caption, element("p", dataset.readings.join(" · ") + " AU", "dataset-readings"));
    const result = dataset.result;
    if (result) {
      const estimated = result.status === "estimated";
      const outcome = element("div", undefined, "b12-outcome" + (estimated ? "" : " withheld"));
      if (estimated) {
        const concentration = element("p", String(Number(result.concentration_mg_l.toPrecision(10))), "concentration");
        concentration.append(element("span", " mg/L"));
        outcome.append(element("p", "B12 concentration", "field-caption"), concentration);
        concentration.title = String(result.concentration_mg_l) + " mg/L";
      } else {
        outcome.append(element("h3", "Concentration withheld"), element("p", result.reason));
      }
      outcome.append(element("p", "Mean absorbance " + Number(result.mean_absorbance_au.toPrecision(10)) + " AU", "mean"));
      const trace = element("details", undefined, "result-trace");
      trace.append(element("summary", "Result provenance"));
      const dl = element("dl", undefined, "order-meta");
      definition(dl, "Approved source", order.id + " · submission " + result.submission);
      definition(dl, "Written by", result.worker);
      definition(dl, "Approved by", result.approved_by);
      definition(dl, "Calibration", result.calibration_id);
      definition(dl, "Run by", result.actor + " · " + result.created_at);
      definition(dl, "Artifact SHA-256", result.artifact_digest, "mono");
      definition(dl, "Readings SHA-256", result.readings_digest, "mono");
      trace.append(dl);
      body.append(outcome, trace);
    } else if (order.status === "released") {
      const run = button("Run analysis", "primary", async () => {
        const page = generation;
        run.disabled = true;
        try {
          await post("b12/orders/" + encodeURIComponent(order.id) + "/readings/" + encodeURIComponent(dataset.id) + "/run",
            {submission: order.released_submission});
          if (generation !== page) return;
          await navigate();
          if (reviewer && location.hash === "#order/" + encodeURIComponent(order.id)) byId("dataset-" + dataset.id)?.focus();
        } catch (error) { if (generation === page) notify(error.message, true); }
        finally { run.disabled = false; }
      });
      run.setAttribute("aria-label", "Run analysis on dataset " + dataset.id);
      body.append(run);
    } else {
      body.append(element("p", "Available to run once a reviewer releases the analysis.", "muted"));
    }
    body.id = "dataset-" + dataset.id;
    body.tabIndex = -1;
    section.append(body);
  }
  return section;
}

function examplePanel() {
  const section = panel("Example work order");
  section.classList.add("space-top");
  const body = element("div", undefined, "panel-body");
  const create = button("Create example order", "secondary", async () => {
    create.disabled = true;
    try {
      const data = await post("example", {});
      openOrder(data.id);
    } catch (error) {
      notify(error.message, true);
    } finally { create.disabled = false; }
  });
  body.append(element("p", "Load the UV-visible spectrophotometer and B12 experiment, then open a run plan for an agent to claim.", "muted"), create);
  section.append(body);
  return section;
}

function showContext() {
  const split = element("div", undefined, "split");
  for (const kind of ["lab", "experiment"]) {
    const label = kind === "lab" ? "Lab record" : "Experiment record";
    const section = panel(label);
    const body = element("div", undefined, "panel-body");
    body.append(element("p", kind === "lab" ? "Save a revision of the instruments, limits, and reference documents." :
      "Save an experiment after importing the lab and instruments it references.", "muted"));
    const form = element("form");
    form.method = "post";
    const file = element("input");
    file.type = "file"; file.accept = ".json,application/json"; file.name = "record"; file.required = true;
    file.id = "import-" + kind;
    const fileLabel = element("label", "JSON file");
    fileLabel.htmlFor = file.id;
    const error = element("p", "", "form-error");
    error.hidden = true; error.setAttribute("role", "alert");
    const submit = element("button", "Import " + kind, "primary");
    submit.type = "submit";
    form.append(fileLabel, file, error, submit);
    handleForm(form, async (fields) => {
      // Preserve the original JSON for duplicate-field detection on the server.
      const data = await api("context/" + kind, {method: "POST", body: await fields.get("record").text()});
      form.reset();
      notify(label + " " + data.id + " saved at revision " + data.revision + ".");
    });
    body.append(form);
    section.append(body);
    split.append(section);
  }
  workspace.replaceChildren(heading("Lab context"), split, examplePanel());
}

function copyButton(value, label) {
  return button(label, "secondary", async () => {
    try {
      await navigator.clipboard.writeText(value);
      notify("Copied to clipboard.");
    } catch {
      notify("Clipboard access is unavailable. Select and copy the text above.", true);
    }
  });
}

function showAgents() {
  const endpoint = location.origin + "/mcp";
  const cmd = "codex mcp add lab-factory --url " + endpoint + " --bearer-token-env-var LAB_FACTORY_AGENT_TOKEN";
  const section = panel("Remote MCP connection");
  const body = element("div", undefined, "panel-body");
  body.append(element("h3", "Endpoint"), element("pre", endpoint, "snippet"), copyButton(endpoint, "Copy endpoint"),
    element("p", "Transport", "field-caption"), element("p", "Streamable HTTP"),
    element("p", "Agent names", "field-caption"), element("p", agentNames.length ? agentNames.join(", ") : "No agents configured."),
    element("p", "Connect with Codex", "field-caption"),
    element("p", "Set LAB_FACTORY_AGENT_TOKEN in your agent’s environment to its issued bearer token. Use the corresponding agent name as the worker when claiming and submitting."),
    element("pre", cmd, "snippet"), copyButton(cmd, "Copy command"));
  section.append(body);
  workspace.replaceChildren(heading("Agent access"), section);
}

async function navigate() {
  if (!reviewer) return;
  const request = ++generation;
  for (const modal of document.querySelectorAll("dialog[open]")) modal.close();
  const hash = location.hash.slice(1);
  const isOrder = hash.startsWith("order/");
  const tab = ["context","agents","b12"].includes(hash) ? hash : "orders";
  function selectTab(active) {
    for (const link of byId("nav").querySelectorAll("a")) {
      if (link.dataset.tab === active) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    }
  }
  selectTab(tab);
  notify("");
  const page = {orders:"Work orders",context:"Lab context",agents:"Agent access",b12:"Vitamin B12 analysis"}[tab];
  document.title = page + " · Lab Factory";
  workspace.setAttribute("aria-busy","true");
  try {
    if (isOrder || tab === "orders") {
      workspace.replaceChildren(element("p", "Loading work orders…", "muted"));
      const id = isOrder ? decodeURIComponent(hash.slice(6)) : "";
      const data = await api(isOrder ? "orders/" + encodeURIComponent(id) + "?submission=latest" : "orders");
      if (generation !== request) return;
      if (isOrder) {
        const assay = data.order.kind === "analysis_app" ? await api("b12/orders/" + encodeURIComponent(id) + "/readings") : null;
        if (generation !== request) return;
        if (assay) selectTab("b12");
        showOrder(data, assay); document.title = data.order.id + " · Lab Factory";
      }
      else showOrders(data.orders);
    } else if (tab === "b12") {
      workspace.replaceChildren(element("p", "Loading analysis orders…", "muted"));
      const data = await api("b12");
      if (generation === request) showB12(data);
    } else if (tab === "context") showContext();
    else showAgents();
  } catch (error) {
    if (request !== generation) return;
    notify(error.message, true);
    const back = element("a", "Back to work orders"); back.href = "#orders";
    workspace.replaceChildren(actions(refreshButton(), back));
  } finally {
    if (request === generation) workspace.removeAttribute("aria-busy");
  }
}

async function loadSession() {
  const session = await api("session");
  if (!session.reviewer) { showSignin(); return; }
  reviewer = session.reviewer;
  agentNames = Array.isArray(session.agent_names) ? session.agent_names : [];
  byId("signin").hidden = true;
  byId("loading").hidden = true;
  byId("portal-label").hidden = true;
  byId("user-name").textContent = reviewer;
  for (const node of [workspace,byId("nav"),byId("account")]) node.hidden = false;
  await navigate();
}

handleForm(byId("login-form"), async (fields) => {
  await post("login", {name: fields.get("name"), password: fields.get("password")});
  byId("login-form").reset();
  await loadSession();
});
byId("logout").addEventListener("click", async () => {
  try {
    await post("logout", {});
    showSignin();
    notify("You have signed out.");
  } catch (error) { notify(error.message, true); }
});
handleForm(byId("create-form"), async (fields) => {
  const result = await post("orders", Object.fromEntries(fields));
  byId("create-dialog").close();
  openOrder(result.id);
});
handleForm(byId("decision-form"), async (fields) => {
  const {kind, order, number, reviewer: expectedReviewer} = decision;
  const payload = {submission: number, expected_reviewer: expectedReviewer};
  if (kind === "reject") {
    payload.reason = String(fields.get("reason")).trim();
    if (!payload.reason) throw new Error("Enter the reason for rejection.");
  }
  await post("orders/" + encodeURIComponent(order) + "/" + kind, payload);
  byId("decision-dialog").close();
  await navigate();
  notify(order + " submission " + number + (kind === "approve" ? " released." : " rejected. Order reopened."));
  if (kind === "approve" && location.hash === "#order/" + encodeURIComponent(order)) byId("b12-datasets")?.focus();
});
for (const close of document.querySelectorAll("[data-close]")) {
  close.addEventListener("click", () => close.closest("dialog").close());
}
for (const modal of document.querySelectorAll("dialog")) {
  modal.addEventListener("cancel", event => {
    if (modal.querySelector("button[type=submit]").disabled) event.preventDefault();
  });
}
document.querySelector(".skip").addEventListener("click", event => {
  event.preventDefault();
  byId("main").focus();
});
window.addEventListener("hashchange", navigate);
window.addEventListener("pageshow", event => {
  if (event.persisted) { showSignin(); loadSession().catch(error => notify(error.message, true)); }
});
loadSession().catch(error => { showSignin(); notify(error.message, true); });
