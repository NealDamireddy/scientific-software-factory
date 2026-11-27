"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  Archive,
  ArrowUpRight,
  BookOpen,
  ChartNoAxesCombined,
  Check,
  ChevronDown,
  ClipboardList,
  FileCheck2,
  Plug,
  Terminal,
  Plus,
  ShieldCheck,
  Microscope,
  Wrench,
} from "lucide-react";
import "./extensions.css";

import Modal from "./modal";
import RecordReview from "./record-review";
import type { Family, Stage } from "./review-skills/types";
import { ExtensionForm, endpointError } from "./extension-form";
import {
  builtinConnectors,
  builtinSkills,
  isValidEndpoint,
  type ExtensionState,
  type CustomConnector,
  type CustomSkill,
} from "./extension-model";
export type { ExtensionState } from "./extension-model";
export { defaultExtensions } from "./extension-model";

type Props = {
  value: ExtensionState;
  onChange: (value: ExtensionState) => void;
};
const catalogIcons: Record<string, typeof Plug> = {
  notebook: BookOpen,
  archive: Archive,
};
const sources = builtinConnectors.map((entry) => ({
  ...entry,
  icon: catalogIcons[entry.id] ?? Plug,
}));
const familyIcons = {
  "Lab knowledge": BookOpen,
  "Experiment planning": ClipboardList,
  "Instruments & execution": Microscope,
  "Analysis & results": ChartNoAxesCombined,
  "Scientific review": ShieldCheck,
  "Evidence & reproducibility": FileCheck2,
} satisfies Record<Family, typeof Plug>;
const families = (Object.keys(familyIcons) as Family[]).map((name) => ({
  name,
  icon: familyIcons[name],
  skills: builtinSkills.filter((skill) => skill.family === name),
}));
const triggerLabel: Record<Stage, string> = {
  start: "Run start",
  result: "Result available",
  repeat: "Repeat run",
};
function toggle(items: string[], id: string) {
  return items.includes(id)
    ? items.filter((item) => item !== id)
    : [...items, id];
}
type Section = "connectors" | "skills";
type EntryDialog =
  { action: "edit" | "remove"; id: string } | { action: "add" };
export function ExtensionPage({
  section,
  value,
  onChange,
  openSettings,
  selectedId,
}: Props & {
  section: Section;
  openSettings: () => void;
  selectedId?: string;
}) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const [openFamily, setOpenFamily] = useState<Family | null>(null);
  const [reviewingRecord, setReviewingRecord] = useState(false);
  const [dialog, setDialog] = useState<EntryDialog | null>(null);
  const addButton = useRef<HTMLButtonElement>(null);
  const isConnector = section === "connectors";
  const kind = isConnector ? "connector" : "skill";
  const entries = isConnector ? value.customConnectors : value.customSkills;
  const editId = dialog && dialog.action !== "add" ? dialog.id : undefined;
  const current = entries.find((entry) => entry.id === editId);
  const names = [
    ...(isConnector ? sources : builtinSkills),
    ...entries.filter((entry) => entry.id !== editId),
  ].map((entry) => entry.name);
  function reveal(id: string) {
    const family = builtinSkills.find((skill) => skill.id === id)?.family;
    if (family) setOpenFamily(family);
    setExpanded(id);
    requestAnimationFrame(() => {
      const row = document.getElementById("extension-" + id);
      row?.focus({ preventScroll: true });
      row?.scrollIntoView({ block: "nearest" });
    });
  }
  useEffect(() => {
    setDialog(null);
    setReviewingRecord(false);
    if (selectedId) reveal(selectedId);
    else setExpanded(null);
  }, [section, selectedId]);
  function saveConnector(entry: CustomConnector) {
    const customConnectors = current
      ? value.customConnectors.map((old) => (old.id === entry.id ? entry : old))
      : [...value.customConnectors, entry];
    onChange({ ...value, customConnectors });
    setDialog(null);
    reveal(entry.id);
  }
  function saveSkill(entry: CustomSkill) {
    const customSkills = current
      ? value.customSkills.map((old) => (old.id === entry.id ? entry : old))
      : [...value.customSkills, entry];
    onChange({
      ...value,
      customSkills,
      skills: current ? value.skills : [...value.skills, entry.id],
    });
    setDialog(null);
    reveal(entry.id);
  }
  function remove() {
    if (!current) return;
    if (isConnector)
      onChange({
        ...value,
        customConnectors: value.customConnectors.filter(
          (entry) => entry.id !== current.id,
        ),
        connectors: value.connectors.filter((id) => id !== current.id),
      });
    else
      onChange({
        ...value,
        customSkills: value.customSkills.filter(
          (entry) => entry.id !== current.id,
        ),
        skills: value.skills.filter((id) => id !== current.id),
      });
    setExpanded(null);
    setDialog(null);
    requestAnimationFrame(() => addButton.current?.focus());
  }
  function access(id: string, name: string) {
    const enabled = value[section].includes(id);
    const change = () =>
      onChange({ ...value, [section]: toggle(value[section], id) });
    return isConnector ? (
      <button
        className="ws-button"
        aria-label={(enabled ? "Disconnect " : "Connect ") + name}
        onClick={change}
      >
        {enabled ? <Check size={15} /> : <Plug size={15} />}{" "}
        {enabled ? "Disconnect" : "Connect"}
      </button>
    ) : (
      <button
        className="ext-switch"
        role="switch"
        aria-checked={enabled}
        aria-label={name}
        onClick={change}
      >
        <span />
      </button>
    );
  }
  function customRow(entry: CustomConnector | CustomSkill) {
    const open = expanded === entry.id;
    return (
      <div
        key={entry.id}
        id={"extension-" + entry.id}
        className="ext-record"
        tabIndex={-1}
        aria-label={entry.name}
      >
        <div className="ext-row">
          <span className="ext-icon">
            {isConnector ? <Plug /> : <Wrench />}
          </span>
          <button
            className="ext-copy ext-disclosure"
            aria-expanded={open}
            aria-controls={"detail-" + entry.id}
            onClick={() => setExpanded(open ? null : entry.id)}
          >
            <span className="ext-title">
              {entry.name}
              <ChevronDown size={15} />
            </span>
            <span className="ext-description">
              {"endpoint" in entry
                ? entry.description || entry.endpoint
                : entry.whenToUse}
            </span>
            {isConnector && value.connectors.includes(entry.id) && (
              <small className="ext-status">
                <i />
                Simulated connection
              </small>
            )}
          </button>
          {access(entry.id, entry.name)}
        </div>
        <div className="ext-expanded" hidden={!open} id={"detail-" + entry.id}>
          <dl className="ext-details">
            <dt>{"endpoint" in entry ? "MCP endpoint" : "Instructions"}</dt>
            <dd>{"endpoint" in entry ? entry.endpoint : entry.instructions}</dd>
          </dl>
          <div className="ext-row-actions">
            <button
              className="ws-button"
              onClick={() => setDialog({ action: "edit", id: entry.id })}
            >
              Edit {kind}
            </button>
            <button
              className="ws-button"
              onClick={() => setDialog({ action: "remove", id: entry.id })}
            >
              Remove {kind}
            </button>
          </div>
        </div>
      </div>
    );
  }
  return (
    <section className="ws-page ext-page">
      <div className="ws-pagehead">
        <h1>{isConnector ? "Connectors" : "Skills"}</h1>
        <div className="ext-header-actions">
          {!isConnector && (
            <button
              className="ws-button"
              onClick={() => setReviewingRecord(true)}
            >
              <FileCheck2 size={16} />
              Review a record
            </button>
          )}
          <button
            ref={addButton}
            className="ws-button primary"
            onClick={() => setDialog({ action: "add" })}
          >
            <Plus size={16} />
            Add {kind}
          </button>
        </div>
      </div>
      <p className="ws-lede">
        {isConnector
          ? "Manage the tools and data sources available to this workspace."
          : "Choose the research skills enabled in this demo workspace."}
      </p>
      {entries.length > 0 && (
        <>
          <div className="ws-sectionhead">
            <h2>{isConnector ? "Your connectors" : "Custom skills"}</h2>
            {!isConnector && (
              <span>
                {
                  value.customSkills.filter((skill) =>
                    value.skills.includes(skill.id),
                  ).length
                }{" "}
                enabled
              </span>
            )}
          </div>
          {entries.map(customRow)}
        </>
      )}
      {isConnector ? (
        <>
          <div
            className={"ws-sectionhead" + (entries.length ? " ext-group" : "")}
          >
            <h2>Coding harness</h2>
          </div>
          <div className="ext-row" id="extension-harness" tabIndex={-1}>
            <span className="ext-icon">
              <Terminal />
            </span>
            <div className="ext-copy">
              <h3>{value.harness?.name || "Custom coding harness"}</h3>
              <p>
                {value.harness
                  ? value.harness.endpoint
                  : "Connect your own coding environment through MCP."}
              </p>
              {value.harness && (
                <small className="ext-status">
                  <i />
                  Simulated connection
                </small>
              )}
            </div>
            <button className="ws-button" onClick={openSettings}>
              {value.harness ? "Manage" : "Configure"}{" "}
              <ArrowUpRight size={15} />
            </button>
          </div>
          <div className="ws-sectionhead ext-group">
            <h2>Demo data sources</h2>
          </div>
          {sources.map(({ id, name, icon: Icon, description }) => (
            <div
              key={id}
              id={"extension-" + id}
              tabIndex={-1}
              className="ext-row"
            >
              <span className="ext-icon">
                <Icon />
              </span>
              <div className="ext-copy">
                <h3>{name}</h3>
                <p>{description}</p>
                {value.connectors.includes(id) && (
                  <small className="ext-status">
                    <i />
                    Simulated connection
                  </small>
                )}
              </div>
              {access(id, name)}
            </div>
          ))}
        </>
      ) : (
        <>
          <div
            className={"ws-sectionhead" + (entries.length ? " ext-group" : "")}
          >
            <h2>Workspace skills</h2>
            <span>
              {
                builtinSkills.filter((skill) => value.skills.includes(skill.id))
                  .length
              }{" "}
              enabled
            </span>
          </div>
          <div className="ext-families">
            {families.map(
              ({ name: family, icon: Icon, skills: members }, index) => {
                const familyOpen = openFamily === family;
                const familyId = "skill-family-" + index;
                return (
                  <section className="ext-family" key={family}>
                    <h3>
                      <button
                        id={familyId + "-title"}
                        className="ext-family-toggle"
                        aria-expanded={familyOpen}
                        aria-controls={familyId}
                        onClick={() =>
                          setOpenFamily(familyOpen ? null : family)
                        }
                      >
                        <span className="ext-family-icon">
                          <Icon size={20} aria-hidden />
                        </span>
                        <span className="ext-family-name">{family}</span>
                        <span className="ext-family-count">
                          {
                            members.filter((skill) =>
                              value.skills.includes(skill.id),
                            ).length
                          }{" "}
                          of {members.length} enabled
                        </span>
                        <ChevronDown
                          size={16}
                          aria-hidden
                          className="ext-family-chevron"
                        />
                      </button>
                    </h3>
                    <div
                      id={familyId}
                      hidden={!familyOpen}
                      aria-labelledby={familyId + "-title"}
                    >
                      {members.map(
                        ({
                          id,
                          name,
                          description,
                          input,
                          output,
                          stage,
                          whenToUse,
                          instructions,
                        }) => {
                          const open = expanded === id;
                          return (
                            <div
                              className="ext-family-skill"
                              key={id}
                              id={"extension-" + id}
                              tabIndex={-1}
                            >
                              <div className="ext-row">
                                <button
                                  className="ext-disclosure ext-copy"
                                  aria-expanded={open}
                                  aria-controls={"skill-" + id}
                                  onClick={() => setExpanded(open ? null : id)}
                                >
                                  <span className="ext-title">
                                    {name}
                                    <ChevronDown size={14} />
                                  </span>
                                  <span className="ext-description">
                                    {description}
                                  </span>
                                </button>
                                <span className="ext-trigger">
                                  {triggerLabel[stage]}
                                </span>
                                {access(id, name)}
                              </div>
                              <dl
                                className="ext-details ext-skill-details"
                                id={"skill-" + id}
                                hidden={!open}
                              >
                                <dt>When to use</dt>
                                <dd>{whenToUse}</dd>
                                <dt>Inputs</dt>
                                <dd>{input}</dd>
                                <dt>Output</dt>
                                <dd>{output}</dd>
                                <dt>Instructions</dt>
                                <dd className="ext-skill-instructions">
                                  {instructions}
                                </dd>
                              </dl>
                            </div>
                          );
                        },
                      )}
                    </div>
                  </section>
                );
              },
            )}
          </div>
        </>
      )}
      {reviewingRecord && !isConnector && (
        <RecordReview close={() => setReviewingRecord(false)} />
      )}
      {dialog &&
        (dialog.action === "remove" ? (
          current && (
            <Modal title={"Remove " + kind + "?"} close={() => setDialog(null)}>
              <p>Remove “{current.name}” from this workspace?</p>
              <div className="ws-actions">
                <button
                  autoFocus
                  className="ws-button"
                  onClick={() => setDialog(null)}
                >
                  Cancel
                </button>
                <button className="ws-button primary" onClick={remove}>
                  Remove {kind}
                </button>
              </div>
            </Modal>
          )
        ) : (
          <Modal
            title={(current ? "Edit " : "Add ") + kind}
            close={() => setDialog(null)}
          >
            {isConnector ? (
              <ExtensionForm
                kind="connector"
                names={names}
                record={value.customConnectors.find(
                  (entry) => entry.id === editId,
                )}
                save={saveConnector}
                cancel={() => setDialog(null)}
              />
            ) : (
              <ExtensionForm
                kind="skill"
                names={names}
                record={value.customSkills.find((entry) => entry.id === editId)}
                save={saveSkill}
                cancel={() => setDialog(null)}
              />
            )}
          </Modal>
        ))}
    </section>
  );
}

export function HarnessSettings({ value, onChange }: Props) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(""),
    [endpoint, setEndpoint] = useState(""),
    [error, setError] = useState("");
  const harness = value.harness;
  function begin() {
    setName(harness?.name ?? "");
    setEndpoint(harness?.endpoint ?? "");
    setError("");
    setEditing(true);
  }
  function save(event: FormEvent) {
    event.preventDefault();
    const label = name.trim(),
      address = endpoint.trim();
    if (!label) {
      setError("Enter a name for your harness.");
      return;
    }
    if (!isValidEndpoint(address)) {
      setError(endpointError);
      return;
    }
    onChange({ ...value, harness: { name: label, endpoint: address } });
    setEditing(false);
  }
  return (
    <section className="ext-harness">
      <h3>
        <Terminal size={18} />
        Coding harness
      </h3>
      {editing ? (
        <form onSubmit={save}>
          <p>
            Configure a simulated MCP connection. These settings stay in this
            browser.
          </p>
          <label className="ws-field">
            Harness name
            <input
              autoFocus
              required
              maxLength={80}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="My coding harness"
            />
          </label>
          <label className="ws-field">
            MCP endpoint
            <input
              required
              type="url"
              maxLength={512}
              autoComplete="off"
              spellCheck={false}
              value={endpoint}
              onChange={(e) => setEndpoint(e.target.value)}
              placeholder="http://localhost:3000/mcp"
            />
          </label>
          {error && <p role="alert">{error}</p>}
          <div className="ws-actions">
            <button
              type="button"
              className="ws-button"
              onClick={() => setEditing(false)}
            >
              Cancel
            </button>
            <button className="ws-button primary" type="submit">
              Save connection
            </button>
          </div>
        </form>
      ) : harness ? (
        <div>
          <div className="ext-harness-record">
            <strong>{harness.name}</strong>
            <span>{harness.endpoint}</span>
            <small className="ext-status">
              <i />
              Simulated connection
            </small>
          </div>
          <div className="ext-harness-actions">
            <button className="ws-button" onClick={begin}>
              Edit connection
            </button>
            <button
              className="ws-button"
              onClick={() => onChange({ ...value, harness: null })}
            >
              Disconnect
            </button>
          </div>
        </div>
      ) : (
        <>
          <p>
            Connect your coding environment through Model Context Protocol (MCP)
            in simulation mode.
          </p>
          <button className="ws-button" onClick={begin}>
            <Plug size={15} />
            Connect coding harness
          </button>
        </>
      )}
    </section>
  );
}
