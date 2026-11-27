"use client";

import { useState, type FormEvent } from "react";
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
} from "lucide-react";
import "./extensions.css";

type Harness = { name: string; endpoint: string };
export type ExtensionState = {
  harness: Harness | null;
  connectors: string[];
  skills: string[];
};
export const defaultExtensions: ExtensionState = {
  harness: null,
  connectors: [],
  skills: ["calibration", "evidence"],
};

type Props = {
  value: ExtensionState;
  onChange: (value: ExtensionState) => void;
};
const sources = [
  {
    id: "notebook",
    name: "Lab notebook",
    icon: BookOpen,
    description:
      "Protocol notes and sample annotations from a shared notebook.",
  },
  {
    id: "archive",
    name: "Instrument archive",
    icon: Archive,
    description: "Measurement files and instrument run records.",
  },
];
const skills = [
  {
    id: "calibration",
    name: "Calibration review",
    icon: ChartNoAxesCombined,
    description: "Check sample readings against a calibration range.",
    input: "Calibration standards and sample absorbance",
    output: "Range assessment and a review note",
  },
  {
    id: "evidence",
    name: "Evidence summary",
    icon: FileCheck2,
    description: "Summarize the records behind an experiment result.",
    input: "Run history, source readings, and reviewer decisions",
    output: "A summary with references to the underlying records",
  },
  {
    id: "method",
    name: "Method comparison",
    icon: ClipboardList,
    description: "Compare two versions of an experimental method.",
    input: "Two method records",
    output: "A list of changes to parameters and interpretation",
  },
];
function toggle(items: string[], id: string) {
  return items.includes(id)
    ? items.filter((item) => item !== id)
    : [...items, id];
}
export function ExtensionPage({
  section,
  value,
  onChange,
  openSettings,
}: Props & { section: "connectors" | "skills"; openSettings: () => void }) {
  const [expanded, setExpanded] = useState<string | null>(null);
  if (section === "connectors")
    return (
      <section className="ws-page ext-page">
        <h1>Connectors</h1>
        <p className="ws-lede">
          Manage the tools and data sources available to this workspace.
        </p>
        <div className="ws-sectionhead">
          <h2>Coding harness</h2>
        </div>
        <div className="ext-row">
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
            {value.harness ? "Manage" : "Configure"} <ArrowUpRight size={15} />
          </button>
        </div>
        <div className="ws-sectionhead ext-group">
          <h2>Demo data sources</h2>
        </div>
        {sources.map(({ id, name, icon: Icon, description }) => {
          const connected = value.connectors.includes(id);
          return (
            <div key={id} className="ext-row">
              <span className="ext-icon">
                <Icon />
              </span>
              <div className="ext-copy">
                <h3>{name}</h3>
                <p>{description}</p>
                {connected && (
                  <small className="ext-status">
                    <i />
                    Simulated connection
                  </small>
                )}
              </div>
              <button
                className="ws-button"
                aria-label={(connected ? "Disconnect " : "Connect ") + name}
                onClick={() =>
                  onChange({
                    ...value,
                    connectors: toggle(value.connectors, id),
                  })
                }
              >
                {connected ? <Check size={15} /> : <Plug size={15} />}{" "}
                {connected ? "Disconnect" : "Connect"}
              </button>
            </div>
          );
        })}
      </section>
    );
  return (
    <section className="ws-page ext-page">
      <h1>Skills</h1>
      <p className="ws-lede">
        Choose the research skills enabled in this demo workspace.
      </p>
      <div className="ws-sectionhead">
        <h2>Workspace skills</h2>
        <span>{value.skills.length} enabled</span>
      </div>
      {skills.map(({ id, name, icon: Icon, description, input, output }) => {
        const enabled = value.skills.includes(id),
          open = expanded === id;
        return (
          <div className="ext-skill" key={id}>
            <div className="ext-row">
              <span className="ext-icon">
                <Icon />
              </span>
              <button
                className="ext-disclosure ext-copy"
                aria-expanded={open}
                aria-controls={"skill-" + id}
                onClick={() => setExpanded(open ? null : id)}
              >
                <span className="ext-title">
                  {name}
                  <ChevronDown size={15} />
                </span>
                <span className="ext-description">{description}</span>
              </button>
              <button
                className="ext-switch"
                role="switch"
                aria-checked={enabled}
                aria-label={name}
                onClick={() =>
                  onChange({ ...value, skills: toggle(value.skills, id) })
                }
              >
                <span />
              </button>
            </div>
            <dl className="ext-details" id={"skill-" + id} hidden={!open}>
              <dt>Inputs</dt>
              <dd>{input}</dd>
              <dt>Output</dt>
              <dd>{output}</dd>
            </dl>
          </div>
        );
      })}
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
    try {
      const url = new URL(address);
      if (
        !["http:", "https:"].includes(url.protocol) ||
        !url.hostname ||
        url.username ||
        url.password ||
        url.search ||
        url.hash
      )
        throw new Error();
    } catch {
      setError(
        "Enter an HTTP or HTTPS endpoint without credentials, query parameters, or a fragment.",
      );
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
