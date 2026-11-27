"use strict";

const mappingFields = [
  ["id", "Sample ID", true], ["role", "Row role", true], ["signal", "Measured signal", true],
  ["known", "Known value of standards", false], ["factor", "Factor or volume", false],
];

function analysisLink(text, href) {
  const link = element("a", text);
  link.href = href;
  return link;
}

function analysisInput(title, name, type = "text", required = true) {
  const label = element("label", title, "analysis-field");
  const input = element(type === "textarea" ? "textarea" : type === "select" ? "select" : "input");
  input.name = name;
  input.required = required;
  if (input.tagName === "INPUT") input.type = type;
  if (type === "number") input.step = "any";
  label.append(input);
  return {label, input};
}

function analysisError() {
  const p = element("p", undefined, "form-error");
  p.setAttribute("role", "alert");
  p.hidden = true;
  return p;
}

function analysisSubmit(text) {
  const submit = element("button", text, "primary");
  submit.type = "submit";
  return submit;
}

function analysisDetails(summary, ...content) {
  const detail = element("details", undefined, "analysis-disclosure");
  detail.append(element("summary", summary), ...content);
  return detail;
}

function analysisGroup(title) {
  const group = element("fieldset", undefined, "analysis-group");
  group.append(element("legend", title));
  return group;
}

function analysisFile(title, accept, onText, form) {
  const {label, input} = analysisInput(title, "", "file", false);
  input.accept = accept;
  input.addEventListener("change", async () => {
    const file = input.files[0];
    if (!file) return;
    try {
      const limit = accept.includes(".csv") ? 128 : 32;
      if (file.size > limit * 1024) throw new Error("Select a file of at most " + limit + " KiB.");
      const text = new TextDecoder("utf-8", {fatal:true, ignoreBOM:true}).decode(await file.arrayBuffer());
      if (input.files[0] !== file) return;
      onText(text, file.name);
      formError(form, "");
    } catch (error) {
      if (input.files[0] !== file) return;
      input.value = "";
      formError(form, error instanceof TypeError ? "Use a UTF-8 text file." : error.message);
    }
  });
  return {label, input};
}

// Parse enough of the CSV to show the actual column names and a small preview.
// The service validates and stores the original upload on submission.
function previewCsv(text) {
  const rows = [];
  let row = [], field = "", quoted = false, closed = false;
  text = text.replace(/^\uFEFF/, "");
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"') {
        if (text[i + 1] === '"') { field += '"'; i++; }
        else { quoted = false; closed = true; }
      } else field += c;
    } else if (c === ",") {
      row.push(field); field = ""; closed = false;
    } else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(field); rows.push(row); row = []; field = ""; closed = false;
      if (rows.length === 5) break;
    } else if (c === '"' && !field && !closed) quoted = true;
    else {
      if (closed || c === '"') throw new Error("Check the quotation marks in the CSV.");
      field += c;
    }
  }
  if (quoted) throw new Error("The preview contains an unfinished quoted CSV field.");
  if (row.length || field || closed) { row.push(field); rows.push(row); }
  return rows;
}

function showTabularOrders(data) {
  const create = button("New analysis", "primary", () => { location.hash = "#analysis/new"; });
  const list = panel("Analysis orders");
  if (!data.orders.length) list.append(element("p", "Your first analysis starts with a protocol and a readings CSV.", "empty"));
  else {
    const {wrapper, body} = table(["Order", "Objective", "Worker", "Status"]);
    for (const order of [...data.orders].reverse()) {
      const row = body.insertRow();
      row.insertCell().append(linkToOrder(order.id));
      row.insertCell().textContent = order.objective;
      row.insertCell().textContent = order.worker || "Awaiting worker";
      row.insertCell().append(status(order.status === "open" ? "Queued" : statuses[order.status], order.status));
    }
    list.append(wrapper);
  }
  workspace.replaceChildren(heading("Analysis workspace", refreshButton(), create),
    element("p", "Request an analysis from your protocol and CSV. Review its code and blind control result before releasing it for use.", "assay-intro"), list);
}

function showTabularIntake() {
  const form = element("form", undefined, "panel-body tabular-form");
  const inputs = analysisGroup("Protocol and readings");
  const objective = analysisInput("What should the analysis report?", "objective");
  const unit = analysisInput("Result unit", "unit");
  unit.input.placeholder = "e.g. mg/L";
  const protocol = analysisInput("Protocol text", "protocol", "textarea");
  protocol.input.rows = 5;
  const csv = analysisInput("Readings CSV", "csv", "textarea");
  csv.input.rows = 4; csv.input.spellcheck = false;
  let protocolName = "protocol.md", csvName = "readings.csv";
  let protocolOriginal = null, csvOriginal = null;
  const protocolFile = analysisFile("Upload protocol (.txt or .md)", ".txt,.md,text/plain,text/markdown", (text, name) => {
    protocol.input.value = text; protocolOriginal = text; protocolName = name;
  }, form);
  const csvFile = analysisFile("Upload readings (.csv)", ".csv,text/csv", (text, name) => {
    csv.input.value = text; csvOriginal = text; csvName = name; updateMapping();
  }, form);
  const objectiveFields = element("div", undefined, "analysis-grid");
  objectiveFields.append(objective.label, unit.label);
  inputs.append(objectiveFields, element("p", "Upload each file or paste its contents below. Keep the blind control’s assigned value out of the protocol and CSV.", "muted"),
    protocolFile.label, protocol.label, csvFile.label, csv.label);

  const columns = analysisGroup("Column mapping");
  const preview = element("div", undefined, "analysis-preview");
  preview.setAttribute("aria-live", "polite");
  const columnFields = element("div", undefined, "analysis-grid");
  const selects = {};
  for (const [key, title, required] of mappingFields) {
    const field = analysisInput(title, "column_" + key, "select", required);
    selects[key] = field.input;
    columnFields.append(field.label);
  }
  const gate = analysisInput("Withhold readings outside the calibration signal range", "range_gate", "checkbox", false);
  gate.input.checked = true;
  gate.label.classList.add("analysis-checkbox");
  columns.append(element("p", "Identify the column containing standard, control and unknown roles. Supply the known value only on standard rows. Include one independent control row.", "muted"),
    preview, columnFields, gate.label);

  function updateMapping(mapping = {}) {
    const previous = Object.fromEntries(Object.entries(selects).map(([k, s]) => [k, s.value]));
    let rows, problem;
    try { rows = previewCsv(csv.input.value); } catch (e) { rows = []; problem = e.message; }
    const headers = rows[0] || [];
    const valid = headers.length && headers.every(h => h.trim()) && new Set(headers).size === headers.length;
    for (const [key,,required] of mappingFields) {
      const select = selects[key];
      const placeholder = key === "factor" ? "Choose a column or confirm factor 1" : required ? "Choose column" : "No standards column";
      select.replaceChildren(new Option(placeholder, ""));
      // A unit factor is an explicit choice, never silently assigned on upload.
      if (key === "factor") {
        select.required = true;
        select.add(new Option("Use factor 1 for every sample", "__unit_factor__"));
      }
      if (valid) for (const head of headers) select.add(new Option(head, head));
      let choice = Object.hasOwn(mapping, key) ? mapping[key] : previous[key];
      if (key === "factor" && Object.hasOwn(mapping, key) && !choice) choice = "__unit_factor__";
      if (choice && [...select.options].some(opt => opt.value === choice)) select.value = choice;
      else if (headers.includes(key)) select.value = key;
    }
    preview.replaceChildren();
    if (!valid) {
      preview.append(element("p", problem || (headers.length ? "Column names must be unique and nonempty." : "Upload or paste your CSV to preview the columns."), "muted"));
      return;
    }
    const {wrapper, body} = table(headers);
    wrapper.tabIndex = 0;
    wrapper.setAttribute("aria-label", "CSV preview");
    for (const values of rows.slice(1)) {
      const row = body.insertRow();
      for (const value of values) row.insertCell().textContent = value;
    }
    preview.append(wrapper);
  }
  csv.input.addEventListener("input", () => { csvName = "readings.csv"; csvOriginal = null; updateMapping(); });
  protocol.input.addEventListener("input", () => { protocolName = "protocol.md"; protocolOriginal = null; });
  updateMapping();

  const blind = analysisGroup("Blind control");
  const control = controlInputs();
  blind.append(element("p", "Enter the independently assigned value in the result unit, and the absolute error your lab will accept. Only the reviewer and verifier receive these values and the control reading.", "muted"), control.group);
  const examples = element("div", undefined, "analysis-examples");
  const exampleSelect = analysisInput("Example dataset", "example", "select", false);
  exampleSelect.input.append(new Option("Choose an example", ""));
  let examplesByFolder = new Map(), loading = 0;
  const loadExample = button("Load example files", "secondary", async () => {
    const example = examplesByFolder.get(exampleSelect.input.value);
    if (!example) return;
    const version = ++loading;
    loadExample.disabled = true;
    try {
      const base = "/examples/tabular/" + encodeURIComponent(example.folder) + "/";
      const parts = await Promise.all(["protocol.md", "readings.csv", "control.json"].map(async file => {
        const response = await fetch(base + file);
        if (!response.ok) throw new Error("The example files are unavailable.");
        return file === "control.json" ? response.json() : response.text();
      }));
      if (version !== loading || !form.isConnected) return;
      protocolFile.input.value = ""; csvFile.input.value = "";
      protocolName = "protocol.md"; csvName = "readings.csv";
      objective.input.value = example.objective; unit.input.value = example.unit;
      protocol.input.value = parts[0]; csv.input.value = parts[1];
      protocolOriginal = parts[0]; csvOriginal = parts[1];
      updateMapping(example.mapping); gate.input.checked = example.range_gate;
      control.expected.value = parts[2].expected; control.tolerance.value = parts[2].tolerance;
      links.replaceChildren(analysisLink("Protocol", base + "protocol.md"), analysisLink("Readings CSV", base + "readings.csv"),
        analysisLink("Simulated control certificate", base + "control.json"));
      for (const a of links.children) a.download = "";
      formError(form, "");
    } catch (error) { formError(form, error.message); }
    finally { if (version === loading) loadExample.disabled = !exampleSelect.input.value; }
  });
  loadExample.disabled = true;
  const links = element("div", undefined, "analysis-example-links");
  exampleSelect.input.addEventListener("change", () => {
    loading++; loadExample.disabled = !exampleSelect.input.value; links.replaceChildren();
  });
  examples.append(exampleSelect.label, loadExample, links);
  fetch("/examples/tabular/index.json").then(r => r.ok ? r.json() : []).then(list => {
    if (!form.isConnected || !Array.isArray(list) || !list.length) { examples.hidden = true; return; }
    examplesByFolder = new Map(list.map(x => [x.folder, x]));
    for (const item of list) exampleSelect.input.append(new Option(item.name, item.folder));
  }).catch(() => { examples.hidden = true; });

  const refs = analysisReferences();
  form.append(examples, inputs, columns, refs.section, blind, analysisError(), analysisSubmit("Request analysis"));
  handleForm(form, async () => {
    const mapping = Object.fromEntries(Object.entries(selects).map(([k, s]) =>
      [k, k === "factor" && s.value === "__unit_factor__" ? "" : s.value]));
    const payload = {objective:objective.input.value.trim(), unit:unit.input.value.trim(),
      protocol_name:protocolName, protocol:protocolOriginal ?? protocol.input.value, csv_name:csvName, csv:csvOriginal ?? csv.input.value,
      mapping, range_gate:gate.input.checked, control_expected:control.expected.valueAsNumber,
      control_tolerance:control.tolerance.valueAsNumber};
    if (refs.selected.size) payload.reference_ids = [...refs.selected.keys()];
    const result = await post("analysis/orders", payload);
    if (form.isConnected) openOrder(result.id);
  });
  const section = panel("Experiment inputs"); section.append(form);
  workspace.replaceChildren(analysisLink("← Analysis workspace", "#analysis"), heading("New analysis"), section);
}

function analysisReferences() {
  const query = analysisInput("Search library sources", "reference_query", "text", false);
  const selected = new Map(), list = element("div", undefined, "analysis-ref-list"), count = element("p", "", "muted");
  const find = button("Find references", "secondary", async () => {
    find.disabled = true;
    try {
      if (!query.input.value.trim()) throw new Error("Enter an experiment or topic to search.");
      const data = await api("references/search?" + new URLSearchParams({instrument:"all", q:query.input.value.trim()}));
      const records = new Map([...selected, ...data.findings.map(r => [r.id, r])]);
      list.replaceChildren();
      if (!records.size) list.append(element("p", "No matching publications.", "muted"));
      for (const r of records.values()) {
        const label = element("label", r.title, "analysis-checkbox");
        const input = element("input"); input.type = "checkbox"; input.checked = selected.has(r.id);
        input.addEventListener("change", () => {
          if (input.checked && selected.size >= 10) { input.checked = false; return; }
          if (input.checked) selected.set(r.id, r); else selected.delete(r.id);
          count.textContent = selected.size + " of 10 selected";
        });
        label.append(input); list.append(label);
      }
    } catch (error) { list.replaceChildren(element("p", error.message, "form-error")); }
    finally { find.disabled = false; }
  });
  const section = analysisDetails("Attach library references (optional)", query.label, find, count, list);
  return {section, selected};
}

function controlInputs() {
  const expected = analysisInput("Expected control value", "expected", "number");
  const tolerance = analysisInput("Absolute tolerance (±)", "tolerance", "number");
  tolerance.input.min = "0";
  const group = element("div", undefined, "analysis-grid");
  group.append(expected.label, tolerance.label);
  return {group, expected:expected.input, tolerance:tolerance.input};
}

function tabularControl(control) {
  const box = element("div", undefined, "blind-report " + (control.passed ? "is-pass" : "is-fail"));
  box.append(element("h3", "Blind control"), status(control.passed ? "Passed" : "Failed", control.passed ? "passed" : "failed"));
  const stats = element("dl", undefined, "calibration-data");
  const display = n => typeof n === "number" ? String(n) + (control.unit ? " " + control.unit : "") : "Withheld";
  definition(stats, "Assigned value", display(control.expected));
  definition(stats, "Predicted value", display(control.predicted));
  definition(stats, "Absolute error", display(control.error));
  definition(stats, "Allowed error (±)", display(control.tolerance));
  box.append(stats);
  if (control.reason) box.append(element("p", control.reason, "muted"));
  return box;
}

function tabularSubmission(submission) {
  const host = document.createDocumentFragment();
  const artifact = submission.artifact || {};
  if (submission.control) host.append(tabularControl(submission.control));
  host.append(element("h3", "Agent’s explanation"), element("p", artifact.explanation || "No explanation submitted."),
    element("h3", "Submitted Python"), element("pre", artifact.source || "", "analysis-source"),
    analysisDetails("Agent-written tests", element("pre", JSON.stringify(artifact.tests, null, 2), "snippet")),
    analysisDetails("Exact submitted artifact", element("pre", JSON.stringify(artifact, null, 2), "analysis-source")));
  return host;
}

function renderTabularOrder(data) {
  const {order, analysis, runs} = data;
  const path = "analysis/orders/" + encodeURIComponent(order.id);
  const info = panel("Pinned inputs"), body = element("div", undefined, "panel-body");
  const summary = element("dl", undefined, "calibration-data");
  definition(summary, "Output unit", analysis.unit);
  definition(summary, "Standards", analysis.standards_count);
  definition(summary, "Unknown samples", analysis.unknown_count);
  definition(summary, "Range check", analysis.range_gate ? "Withhold outside the standards’ range" : "Disabled for this protocol");
  const files = element("div", undefined, "analysis-example-links");
  files.append(analysisLink("Download protocol", "/api/" + path + "/uploads/protocol"),
    analysisLink("Download original CSV", "/api/" + path + "/uploads/readings"));
  const hashes = element("dl", undefined, "order-meta");
  definition(hashes, analysis.protocol_name, analysis.protocol_digest, "mono");
  definition(hashes, analysis.csv_name, analysis.csv_digest, "mono");
  const labels = element("dl", undefined, "calibration-data");
  for (const [key, name] of mappingFields) {
    definition(labels, name, analysis.mapping[key] || (key === "factor" ? "1 for every sample" : "Unused"));
  }
  body.append(summary, files, analysisDetails("Protocol, column mapping and file digests",
    element("pre", analysis.protocol, "rendered"), labels, hashes));
  if (analysis.references?.length) {
    const list = element("ul");
    for (const ref of analysis.references) {
      const li = element("li"); const a = analysisLink(ref.title, ref.url); a.target = "_blank"; a.rel = "noopener noreferrer";
      li.append(a, element("span", " · " + ref.locator, "muted")); list.append(li);
    }
    body.append(analysisDetails("Pinned publications (" + analysis.references.length + ")", list));
  }
  info.append(body); workspace.append(info);
  if (analysis.needs_input) {
    const question = panel("The agent needs clarification"); question.classList.add("space-top");
    const prompt = element("div", undefined, "panel-body");
    prompt.append(element("p", analysis.needs_input), analysisLink("Start a revised analysis with updated inputs", "#analysis/new"));
    question.append(prompt); workspace.append(question);
  }
  if (analysis.control_renewal_required) workspace.append(renewControl(path, !!analysis.mapping.factor));
  if (order.status === "released") {
    workspace.append(batchForm(order, analysis, path));
    if (runs?.length) workspace.append(tabularRuns(runs));
  }
}

function renewControl(path, hasFactor) {
  const section = panel("Fresh blind control required");
  section.classList.add("space-top");
  const form = element("form", undefined, "panel-body");
  const signal = analysisInput("New blind signal", "signal", "number");
  const factor = analysisInput("New control factor or volume", "factor", "number");
  const control = controlInputs();
  const numbers = element("div", undefined, "analysis-grid");
  numbers.append(signal.label);
  if (hasFactor) numbers.append(factor.label);
  form.append(element("p", "Provide an independent control measurement before the worker’s next submission can be verified. Enter its assigned value and absolute tolerance separately.", "muted"),
    numbers, control.group, analysisError(), analysisSubmit("Replace blind control"));
  handleForm(form, async () => {
    await post(path + "/control", {signal:signal.input.valueAsNumber, factor:hasFactor ? factor.input.valueAsNumber : 1,
      expected:control.expected.valueAsNumber, tolerance:control.tolerance.valueAsNumber});
    if (form.isConnected) { await navigate(); notify("Fresh control saved for the next submission."); }
  });
  section.append(form);
  return section;
}

function batchForm(order, analysis, path) {
  const section = panel("Run approved analysis");
  section.classList.add("space-top"); section.id = "tabular-run"; section.tabIndex = -1;
  const body = element("div", undefined, "panel-body");
  const original = button("Run uploaded readings", "primary", async () => {
    original.disabled = true;
    try {
      const receipt = await post(path + "/runs", {submission:order.released_submission});
      if (original.isConnected) { await navigate(); byId("analysis-result-" + receipt.id)?.focus(); }
    } catch (error) { if (original.isConnected) notify(error.message, true); }
    finally { original.disabled = false; }
  });
  body.append(element("p", "Use submission " + order.released_submission + " on " + analysis.csv_name + " or upload another batch with the same columns and units.", "muted"), original);
  const form = element("form", undefined, "analysis-batch-form");
  let name = "new-batch.csv", originalCsv = null;
  const csv = analysisInput("New batch CSV", "csv", "textarea"); csv.input.rows = 4; csv.input.spellcheck = false;
  const file = analysisFile("Upload new batch (.csv)", ".csv,text/csv", (text, filename) => {
    csv.input.value = text; originalCsv = text; name = filename;
  }, form);
  csv.input.addEventListener("input", () => { name = "new-batch.csv"; originalCsv = null; });
  const control = controlInputs();
  form.append(element("p", "Include this batch’s control and standards as required by the pinned mapping. Report the control target in " + analysis.unit + ".", "muted"),
    file.label, csv.label, control.group, analysisError(), analysisSubmit("Verify and run new batch"));
  handleForm(form, async () => {
    const receipt = await post(path + "/runs", {submission:order.released_submission, csv_name:name,
      csv:originalCsv ?? csv.input.value, control_expected:control.expected.valueAsNumber, control_tolerance:control.tolerance.valueAsNumber});
    if (form.isConnected) { await navigate(); byId("analysis-result-" + receipt.id)?.focus(); }
  });
  body.append(analysisDetails("Upload a new batch", form)); section.append(body);
  return section;
}

function tabularRuns(runs) {
  const section = panel("Batch results");
  section.classList.add("space-top");
  for (const run of runs) {
    const entry = element("article", undefined, "panel-body dataset");
    entry.tabIndex = -1; entry.id = "analysis-result-" + run.id;
    const withheld = run.status === "withheld";
    const title = element("div", undefined, "dataset-head");
    title.append(element("h3", run.csv_name), status(withheld ? "Withheld" : "Completed", withheld ? "failed" : "passed"));
    entry.append(title);
    if (run.reason) entry.append(element("p", run.reason));
    if (run.results?.length) {
      const {wrapper, body} = table(["Sample", "Result", "Unit", "Comment"]);
      for (const result of run.results) {
        const row = body.insertRow();
        for (const x of [result.id, result.value ?? "Withheld", result.unit || run.unit, result.reason || "—"]) row.insertCell().textContent = x;
      }
      entry.append(wrapper);
    } else if (withheld) entry.append(element("p", "The batch control failed. Sample results are withheld.", "muted"));
    const meta = element("dl", undefined, "order-meta");
    for (const [name, value] of [["Approved submission", run.submission], ["Approved by", run.approved_by],
         ["Run by", run.actor], ["Artifact SHA-256", run.artifact_digest], ["CSV SHA-256", run.csv_digest]]) {
      definition(meta, name, value, name.endsWith("256") ? "mono" : "");
    }
    const details = analysisDetails("Control and run provenance", meta);
    if (run.control) details.append(tabularControl(run.control));
    entry.append(details); section.append(entry);
  }
  return section;
}

function showTabularOrder(data, page) {
  showOrder(data, null);
  if (!["open", "in_progress"].includes(data.order.status) || data.analysis.control_renewal_required || data.analysis.needs_input) return;
  const stamp = d => JSON.stringify([
    d.order.status, d.order.worker, d.submissions[0]?.number, d.analysis.control_renewal_required, d.analysis.needs_input,
  ]);
  const initial = stamp(data);
  const poll = async () => {
    if (generation !== page || !reviewer) return;
    if (document.visibilityState === "visible" && !document.querySelector("dialog[open]")) {
      try {
        const next = await latestOrder(data.order.id);
        if (generation !== page) return;
        if (stamp(next) !== initial && !document.querySelector("dialog[open]")) {
          showTabularOrder(next, ++generation);
          return;
        }
      } catch { /* Keep the manual refresh available after a temporary network interruption. */ }
    }
    if (generation === page) setTimeout(poll, 7000);
  };
  setTimeout(poll, 7000);
}
