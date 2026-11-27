"use client";

import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import {
  AlignLeft,
  ArrowDownRight,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  ArrowUpRight,
  BookOpen,
  BookText,
  Check,
  ChevronDown,
  ChevronRight,
  CircleDot,
  Cable,
  Blocks,
  FileText,
  FlaskConical,
  Folder,
  Menu,
  Plus,
  Search,
  SlidersHorizontal,
  SquareMinus,
  SquarePlus,
  Download,
} from "lucide-react";
import {
  ResourceForm,
  type KnowledgeRecord,
  type InstrumentRecord,
} from "./resource-form";
import {
  defaultExtensions,
  ExtensionPage,
  HarnessSettings,
  type ExtensionState,
} from "./extensions";
import Modal from "./modal";
import {
  builtinSkills,
  normalizeExtensions,
  buildAgentContext,
} from "./extension-model";
import ExperimentDetail from "./experiment-detail";
import { deliverReview, recordDelivery } from "./worker-delivery";
import {
  advanceWorkspace,
  createDraft,
  initialExperiments,
  type Experiment,
} from "./simulation";
import "./workspace.css";

const baseProjects = ["Coomassie reduction", "B12 quantification"];
const key = "emory.research.workspace.v1";
const demoInstrument: InstrumentRecord = {
  id: "uv-vis",
  name: "UV–Vis spectrometer",
  measurement: "Absorbance spectroscopy",
  location: "",
};
const sampleArticles: KnowledgeRecord[] = [
  {
    title: "Reading an absorbance time course",
    category: "Method note",
    topic: "Coomassie reduction",
    description: "How to interpret a changing absorbance signal over time.",
    paragraphs: [
      "A time course shows how the sample’s absorbance changes during one recorded interval. Read the horizontal axis as elapsed time and the vertical axis as absorbance.",
      "In the illustrative Coomassie record, the trace declines quickly at first, then flattens. Review the point table alongside the plot to distinguish the shape of the signal from the spacing of the readings.",
    ],
  },
  {
    title: "Understanding a calibration range",
    category: "Analysis guide",
    topic: "B12 quantification",
    description:
      "Why a sample outside the standards needs another measurement.",
    paragraphs: [
      "Calibration standards define the range in which a sample reading can be interpreted. When the sample falls outside that range, the workspace withholds its concentration.",
      "In the B12 simulation, a reviewer can approve a diluted repeat or request a change. Both measurements remain in the evidence record so another researcher can follow the decision.",
    ],
  },
  {
    title: "Tracing a result to its evidence",
    category: "Workspace guide",
    topic: "Evidence",
    description:
      "Follow the readings, method, and review history behind a result.",
    paragraphs: [
      "Open an experiment to inspect the readings and method associated with the run. The evidence view keeps decisions beside the data they concern.",
      "Replaying a fixture uses the same illustrative inputs. Compare the repeat with the original record when investigating a difference.",
    ],
  },
];
type DialogName =
  | "search"
  | "project"
  | "settings"
  | "reset"
  | "mode"
  | "add-instrument"
  | "add-knowledge"
  | null;
type Popup = "instrument" | "project" | "workspace" | null;
type Saved = {
  extensions: ExtensionState;
  knowledge: KnowledgeRecord[];
  instruments: InstrumentRecord[];
  projects: string[];
  experiments: Experiment[];
  objective: string;
  selectedProject: string;
};
const initial: Saved = {
  extensions: defaultExtensions,
  knowledge: [],
  instruments: [],
  projects: baseProjects,
  experiments: initialExperiments,
  objective: "",
  selectedProject: "",
};
const pretty = (s: string) =>
  String(s)
    .replace(/[-_]/g, " ")
    .replace(/^./, (x) => x.toUpperCase());
const routeFor = (section: string, item: string) =>
  section + "/" + encodeURIComponent(item);
function decode(s: string) {
  try {
    return decodeURIComponent(s);
  } catch {
    return s;
  }
}
function ChartMark({ rising }: { rising: boolean }) {
  return (
    <span className="ws-chartmark" aria-hidden>
      <svg
        viewBox="0 0 36 36"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.1"
      >
        <path d="M4 4v26h28" />
        <path d={rising ? "M8 25l6-6 6-7 9-7" : "M8 9l5 6 6 4 5 2 7 1"} />
      </svg>
    </span>
  );
}
export default function Workspace() {
  const [saved, setSaved] = useState<Saved>(initial);
  const [loaded, setLoaded] = useState(false);
  const [route, setRoute] = useState("home");
  const [dialog, setDialog] = useState<DialogName>(null);
  const [popup, setPopup] = useState<Popup>(null);
  const [drawer, setDrawer] = useState(false);
  const [query, setQuery] = useState("");
  const [listQuery, setListQuery] = useState("");
  const [filter, setFilter] = useState("All statuses");
  const [projectName, setProjectName] = useState("");
  const [projectError, setProjectError] = useState("");
  const [composerError, setComposerError] = useState("");
  const [projectOrigin, setProjectOrigin] = useState(false);
  const objectiveRef = useRef<HTMLTextAreaElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const openerRef = useRef<HTMLButtonElement>(null);
  const [section, encoded = ""] = route.split("/");
  const item = decode(encoded);
  const project = section === "project" ? item : "";
  const experiment = saved.experiments.find((e) => e.id === item);
  const articles = [...saved.knowledge, ...sampleArticles];
  const instruments = [demoInstrument, ...saved.instruments];
  const instrument = instruments.find((record) => record.id === item);
  const visibleInstruments = instruments.filter((record) =>
    [record.name, record.measurement, record.location]
      .join(" ")
      .toLowerCase()
      .includes(listQuery.trim().toLowerCase()),
  );
  const visibleArticles = articles.filter((record) =>
    [
      record.title,
      record.topic,
      record.category,
      record.description,
      ...record.paragraphs,
    ]
      .join(" ")
      .toLowerCase()
      .includes(listQuery.trim().toLowerCase()),
  );
  const article = articles.find((a) => a.title === item);
  const activeRun = saved.experiments.find((e) => e.status === "Running");
  const activeRunId = activeRun?.id;
  const activeStep = activeRun?.runs.at(-1)?.step;
  useEffect(() => {
    if (!loaded || !activeRunId) return;
    const timer = window.setTimeout(
      () =>
        setSaved((old) => ({
          ...old,
          experiments: advanceWorkspace(old.experiments),
        })),
      1000,
    );
    return () => window.clearTimeout(timer);
  }, [loaded, activeRunId, activeStep]);
  const dispatched = useRef(new Set<string>());
  useEffect(() => {
    if (!loaded) return;
    const pending = new Set<string>();
    for (const experiment of saved.experiments) {
      for (const run of experiment.runs) {
        const delivery = run.workerDelivery;
        if (delivery?.status !== "pending" || !run.agentContext) continue;
        pending.add(delivery.id);
        if (dispatched.current.has(delivery.id)) continue;
        dispatched.current.add(delivery.id);
        void deliverReview(delivery.id, run.agentContext, window.location.hostname)
          .then((result) => setSaved((old) => ({
            ...old, experiments: recordDelivery(old.experiments, result),
          })));
      }
    }
    for (const id of dispatched.current) {
      if (!pending.has(id)) dispatched.current.delete(id);
    }
  }, [loaded, saved.experiments]);
  const update = (patch: Partial<Saved>) =>
    setSaved((old) => ({ ...old, ...patch }));
  useEffect(() => {
    try {
      const raw = localStorage.getItem(key);
      if (raw) {
        const v = JSON.parse(raw);
        if (Array.isArray(v.projects) && Array.isArray(v.experiments))
          setSaved({
            ...initial,
            ...v,
            extensions: normalizeExtensions(v.extensions),
          });
      }
    } catch {}
    const onLocation = () => {
      setRoute(location.hash.slice(1) || "home");
      setPopup(null);
      setDialog(null);
      setDrawer(false);
      setListQuery("");
      setFilter("All statuses");
    };
    onLocation();
    setLoaded(true);
    window.addEventListener("hashchange", onLocation);
    window.addEventListener("popstate", onLocation);
    return () => {
      window.removeEventListener("hashchange", onLocation);
      window.removeEventListener("popstate", onLocation);
    };
  }, []);
  useEffect(() => {
    if (loaded)
      try {
        localStorage.setItem(key, JSON.stringify(saved));
      } catch {}
  }, [saved, loaded]);
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        if (document.querySelector("dialog[open]:not(.ws-searchmodal)")) return;
        setDialog((d) => (d === "search" ? null : "search"));
        setQuery("");
        setPopup(null);
        setDrawer(false);
      }
      if (e.key === "Escape") {
        setPopup(null);
        setDrawer(false);
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, []);
  useEffect(() => {
    if (!popup) return;
    const close = (e: PointerEvent) => {
      if (!(e.target as HTMLElement).closest("[data-popup]")) setPopup(null);
    };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [popup]);
  useEffect(() => {
    if (drawer) openerRef.current?.focus();
  }, [drawer]);
  useEffect(() => {
    if (!popup) return;
    const first = document.querySelector<HTMLButtonElement>(
      ".ws-dropdown button",
    );
    first?.focus();
  }, [popup]);
  function go(next: string) {
    if (next !== (window.location.hash.slice(1) || "home")) {
      window.history.pushState(null, "", "#" + next);
    }
    setRoute(next);
    setPopup(null);
    setDialog(null);
    setDrawer(false);
    setListQuery("");
    setFilter("All statuses");
    window.scrollTo(0, 0);
  }
  function show(name: DialogName) {
    setPopup(null);
    setDrawer(false);
    setDialog(name);
    setQuery("");
  }
  function newProject(fromComposer: boolean) {
    setProjectOrigin(fromComposer);
    setProjectName("");
    setProjectError("");
    show("project");
  }
  function compose(proj?: string) {
    if (proj) update({ selectedProject: proj });
    setComposerError("");
    go("home");
    requestAnimationFrame(() => objectiveRef.current?.focus());
  }
  function submit() {
    const title = saved.objective.trim();
    if (!title) {
      setComposerError("Describe your research objective to start.");
      objectiveRef.current?.focus();
      return;
    }
    const selected =
      saved.selectedProject ||
      (/b12|calibration|vitamin/i.test(title)
        ? baseProjects[1]
        : baseProjects[0]);
    const draft = createDraft(title, selected);
    setSaved((old) => ({
      ...old,
      experiments: [draft, ...old.experiments.filter((e) => e.id !== draft.id)],
      objective: "",
      selectedProject: "",
    }));
    setComposerError("");
    go(routeFor("experiment", draft.id));
  }
  useEffect(() => {
    const listener = (event: KeyboardEvent) => {
      if (
        route === "home" &&
        !dialog &&
        (event.ctrlKey || event.metaKey) &&
        event.key === "Enter"
      ) {
        event.preventDefault();
        submit();
      }
    };
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  });
  function saveProject(event: FormEvent) {
    event.preventDefault();
    const name = projectName.trim();
    if (
      !name ||
      saved.projects.some((p) => p.toLowerCase() === name.toLowerCase())
    ) {
      setProjectError(
        name ? "A project already uses this name." : "Enter a project name.",
      );
      return;
    }
    setSaved((old) => ({
      ...old,
      projects: [...old.projects, name],
      selectedProject: projectOrigin ? name : old.selectedProject,
    }));
    if (projectOrigin) {
      setDialog(null);
      objectiveRef.current?.focus();
    } else go(routeFor("project", name));
  }
  const nav = (
    label: string,
    icon: ReactNode,
    active: boolean,
    action: () => void,
    tail?: ReactNode,
  ) => (
    <button
      key={label}
      className={"ws-navitem " + (active ? "is-active" : "")}
      aria-current={active ? "page" : undefined}
      onClick={action}
    >
      {icon}
      <span>{label}</span>
      {tail}
    </button>
  );
  const popupContent = (children: ReactNode) => (
    <div
      className="ws-dropdown"
      ref={menuRef}
      onKeyDown={(e) => {
        if (e.key === "ArrowDown" || e.key === "ArrowUp") {
          e.preventDefault();
          const buttons = Array.from(
            e.currentTarget.querySelectorAll("button"),
          );
          const index = buttons.indexOf(
            document.activeElement as HTMLButtonElement,
          );
          buttons[
            (index + (e.key === "ArrowDown" ? 1 : -1) + buttons.length) %
              buttons.length
          ]?.focus();
        }
        if (e.key === "Escape") {
          e.currentTarget.parentElement?.querySelector("button")?.focus();
        }
      }}
    >
      {children}
    </div>
  );
  const row = (e: Experiment) => (
    <button
      key={e.id}
      className="ws-experiment-row"
      onClick={() => go(routeFor("experiment", e.id))}
    >
      <ChartMark rising={/b12/i.test(e.kind + e.title + e.project)} />
      <span className="ws-row-copy">
        <strong>{e.title}</strong>
        <small>
          {e.project} <span>·</span> UV–Vis
        </small>
      </span>
      <span className="ws-row-status">
        <i
          className={
            /verified|complete/i.test(e.status)
              ? "green"
              : /review|change/i.test(e.status)
                ? "amber"
                : ""
          }
        />
        {pretty(e.status)}
      </span>
      <ChevronRight className="ws-row-arrow" size={23} />
    </button>
  );
  const headerName: Record<string, string> = {
    connectors: "Connectors",
    skills: "Skills",
    home: "Overview",
    experiments: "All experiments",
    project: "Projects",
    experiment: "Experiment",
    instruments: "Instruments",
    instrument: "Instruments",
    knowledge: "Lab knowledge",
    article: "Lab knowledge",
  };
  const results = [
    { label: "Connectors", group: "Workspace", to: "connectors" },
    { label: "Skills", group: "Workspace", to: "skills" },
    ...saved.extensions.customConnectors.map((record) => ({
      label: record.name,
      group: "Connector",
      to: routeFor("connectors", record.id),
    })),
    ...[...builtinSkills, ...saved.extensions.customSkills].map((record) => ({
      label: record.name,
      group: "Skill",
      to: routeFor("skills", record.id),
    })),
    ...saved.experiments.map((e) => ({
      label: e.title,
      group: "Experiment",
      to: routeFor("experiment", e.id),
    })),
    ...saved.projects.map((p) => ({
      label: p,
      group: "Project",
      to: routeFor("project", p),
    })),
    ...instruments.map((record) => ({
      label: record.name,
      group: "Instrument",
      to: routeFor("instrument", record.id),
    })),
    ...articles.map((a) => ({
      label: a.title,
      group: "Knowledge",
      to: routeFor("article", a.title),
    })),
  ].filter((r) =>
    (r.label + " " + r.group).toLowerCase().includes(query.toLowerCase()),
  );
  return (
    <div className="ws-app">
      {drawer && (
        <button
          className="ws-scrim"
          aria-label="Close navigation"
          onClick={() => setDrawer(false)}
        />
      )}
      <aside
        className={"ws-sidebar " + (drawer ? "is-open" : "")}
        aria-label="Workspace navigation"
        onKeyDown={(e) => {
          if (drawer && e.key === "Tab") {
            const items = Array.from(
              e.currentTarget.querySelectorAll<HTMLButtonElement>("button"),
            );
            if (e.shiftKey && document.activeElement === items[0]) {
              e.preventDefault();
              items.at(-1)?.focus();
            } else if (!e.shiftKey && document.activeElement === items.at(-1)) {
              e.preventDefault();
              items[0]?.focus();
            }
          }
        }}
      >
        <div className="ws-brand-wrap" data-popup>
          <button
            className="ws-brand"
            ref={openerRef}
            aria-expanded={popup === "workspace"}
            onClick={() =>
              setPopup((p) => (p === "workspace" ? null : "workspace"))
            }
          >
            <span className="ws-logo" aria-hidden>
              <i />
              <i />
              <i />
            </span>
            <span>
              <strong>Emory Biophysics</strong>
              <small>Research workspace</small>
            </span>
            <ChevronDown size={23} />
          </button>
          {popup === "workspace" &&
            popupContent(
              <>
                <span className="ws-drop-label">Workspace</span>
                <button onClick={() => setPopup(null)}>
                  Emory Biophysics
                  <Check size={16} />
                </button>
                <button onClick={() => show("settings")}>
                  Workspace settings
                  <SlidersHorizontal size={16} />
                </button>
              </>,
            )}
        </div>
        <nav className="ws-primary" aria-label="Main navigation">
          {nav(
            "Search",
            <Search />,
            false,
            () => show("search"),
            <kbd>⌘ K</kbd>,
          )}
          {nav("New experiment", <SquarePlus />, section === "home", () =>
            compose(),
          )}
          {nav(
            "All experiments",
            <AlignLeft />,
            section === "experiments",
            () => go("experiments"),
          )}
        </nav>
        <div className="ws-projects">
          <div className="ws-projecthead">
            <span>Projects</span>
            <button
              className="ws-iconbutton"
              title="Create project"
              aria-label="Create project"
              onClick={() => newProject(false)}
            >
              <Plus size={20} />
            </button>
          </div>
          <nav aria-label="Project navigation">
            {saved.projects.map((p) =>
              nav(p, <Folder />, project === p, () =>
                go(routeFor("project", p)),
              ),
            )}
          </nav>
        </div>
        <div className="ws-bottom">
          <nav aria-label="Workspace resources">
            {nav(
              "Instruments",
              <SquareMinus />,
              section === "instrument" || section === "instruments",
              () => go("instruments"),
            )}
            {nav(
              "Lab knowledge",
              <BookText />,
              section === "knowledge" || section === "article",
              () => go("knowledge"),
            )}
            {nav("Connectors", <Cable />, section === "connectors", () =>
              go("connectors"),
            )}
            {nav("Skills", <Blocks />, section === "skills", () =>
              go("skills"),
            )}
            {nav("Settings", <CircleDot />, dialog === "settings", () =>
              show("settings"),
            )}
          </nav>
          <button className="ws-account" onClick={() => show("settings")}>
            <span className="ws-avatar">R</span>
            <span>
              Researcher<small>Demo workspace</small>
            </span>
          </button>
        </div>
      </aside>
      <main className="ws-main">
        <header className="ws-topbar">
          <button
            className="ws-iconbutton ws-mobilemenu"
            aria-label="Open navigation"
            onClick={() => setDrawer(true)}
          >
            <Menu />
          </button>
          <span>{headerName[section] || "Overview"}</span>
          <button className="ws-mode" onClick={() => show("mode")}>
            <i />
            Simulation mode
          </button>
        </header>
        {section === "connectors" || section === "skills" ? (
          <ExtensionPage
            key={section}
            section={section}
            selectedId={item}
            value={saved.extensions}
            onChange={(extensions) => update({ extensions })}
            openSettings={() => show("settings")}
          />
        ) : section === "home" ? (
          <div className="ws-home">
            <h1>What are you investigating?</h1>
            <div
              className={"ws-composer " + (composerError ? "has-error" : "")}
            >
              <textarea
                aria-label="Research objective"
                ref={objectiveRef}
                value={saved.objective}
                placeholder="Describe an experiment, analysis, or research objective..."
                onChange={(e) => {
                  update({ objective: e.target.value });
                  setComposerError("");
                }}
              />
              <div className="ws-composerfoot">
                <div className="ws-selectorwrap" data-popup>
                  <button
                    className="ws-selector"
                    aria-expanded={popup === "instrument"}
                    onClick={() =>
                      setPopup((p) =>
                        p === "instrument" ? null : "instrument",
                      )
                    }
                  >
                    <FlaskConical />
                    <span>UV–Vis spectrometer</span>
                    <ChevronDown className="ws-caret" />
                  </button>
                  {popup === "instrument" &&
                    popupContent(
                      <>
                        <span className="ws-drop-label">
                          {activeRun
                            ? "Instrument in use"
                            : "Available instruments"}
                        </span>
                        <button onClick={() => setPopup(null)}>
                          UV–Vis spectrometer
                          <Check size={16} />
                        </button>
                        <button onClick={() => go("instruments")}>
                          View instruments
                          <ArrowUpRight size={16} />
                        </button>
                      </>,
                    )}
                </div>
                <div className="ws-selectorwrap" data-popup>
                  <button
                    className="ws-selector"
                    aria-expanded={popup === "project"}
                    onClick={() =>
                      setPopup((p) => (p === "project" ? null : "project"))
                    }
                  >
                    <Folder />
                    <span>{saved.selectedProject || "Project"}</span>
                    <ChevronDown className="ws-caret" />
                  </button>
                  {popup === "project" &&
                    popupContent(
                      <>
                        <span className="ws-drop-label">Choose project</span>
                        {saved.projects.map((p) => (
                          <button
                            key={p}
                            onClick={() => {
                              update({ selectedProject: p });
                              setPopup(null);
                            }}
                          >
                            {p}
                            {saved.selectedProject === p && <Check size={16} />}
                          </button>
                        ))}
                        <button onClick={() => newProject(true)}>
                          <Plus size={16} />
                          Create project
                        </button>
                      </>,
                    )}
                </div>
                <button
                  className="ws-submit"
                  aria-label="Start experiment draft"
                  title="Review experiment draft"
                  onClick={submit}
                >
                  <ArrowUp />
                </button>
              </div>
            </div>
            <div className="ws-composerhint">
              <span role="status">
                {composerError ||
                  (activeRun ? "Instrument in use" : "1 instrument available")}
              </span>
              <span>⌘ ↵ to start</span>
            </div>
            <section className="ws-recent">
              <div className="ws-sectionhead">
                <h2>Recent experiments</h2>
                <button onClick={() => go("experiments")}>
                  View all <ArrowUpRight size={19} />
                </button>
              </div>
              {saved.experiments.slice(0, 3).map(row)}
            </section>
          </div>
        ) : section === "experiment" && experiment ? (
          <ExperimentDetail
            key={experiment.id}
            experiment={experiment}
            extensions={saved.extensions}
            instrumentBusy={!!activeRun && activeRun.id !== experiment.id}
            onBack={() => go("experiments")}
            onChange={(change) =>
              setSaved((old) => ({
                ...old,
                experiments: old.experiments.map((e) =>
                  e.id === experiment.id ? change(e) : e,
                ),
              }))
            }
          />
        ) : section === "experiments" || section === "project" ? (
          <div className="ws-page">
            <div className="ws-pagehead">
              <div>
                <div className="ws-eyebrow">
                  {project ? "Project" : "Workspace"}
                </div>
                <h1>{project || "All experiments"}</h1>
              </div>
              <button
                className="ws-button primary"
                onClick={() => compose(project)}
              >
                <Plus size={17} />
                New experiment
              </button>
            </div>
            <div className="ws-toolbar">
              <label className="ws-inputgroup">
                <Search size={17} />
                <input
                  aria-label="Search experiments"
                  placeholder="Find an experiment…"
                  value={listQuery}
                  onChange={(e) => setListQuery(e.target.value)}
                />
              </label>
              <select
                aria-label="Filter by status"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
              >
                <option>All statuses</option>
                {[...new Set(saved.experiments.map((e) => e.status))].map(
                  (s) => (
                    <option key={s} value={s}>
                      {pretty(s)}
                    </option>
                  ),
                )}
              </select>
            </div>
            {(() => {
              const matches = saved.experiments.filter(
                (e) =>
                  (!project || e.project === project) &&
                  e.title.toLowerCase().includes(listQuery.toLowerCase()) &&
                  (filter === "All statuses" || e.status === filter),
              );
              return matches.length ? (
                matches.map(row)
              ) : (
                <div className="ws-empty">
                  <Folder size={30} />
                  <h3>
                    {listQuery || filter !== "All statuses"
                      ? "No matching experiments"
                      : "Your project is ready"}
                  </h3>
                  <p>
                    {listQuery || filter !== "All statuses"
                      ? "Try a different title or status."
                      : "Start the first experiment in this project."}
                  </p>
                  <button
                    className="ws-button"
                    onClick={() =>
                      listQuery || filter !== "All statuses"
                        ? (setListQuery(""), setFilter("All statuses"))
                        : compose(project)
                    }
                  >
                    {listQuery || filter !== "All statuses"
                      ? "Clear filters"
                      : "New experiment"}
                  </button>
                </div>
              );
            })()}
          </div>
        ) : section === "instruments" ? (
          <div className="ws-page">
            <div className="ws-eyebrow">Workspace</div>
            <div className="ws-pagehead">
              <h1>Instruments</h1>
              <button
                className="ws-button primary"
                onClick={() => show("add-instrument")}
              >
                <Plus size={16} />
                Add instrument
              </button>
            </div>
            <p className="ws-lede">
              Browse equipment in this research workspace.
            </p>
            <div className="ws-toolbar">
              <label className="ws-inputgroup">
                <Search size={17} />
                <input
                  aria-label="Search instruments"
                  placeholder="Find an instrument…"
                  value={listQuery}
                  onChange={(e) => setListQuery(e.target.value)}
                />
              </label>
            </div>
            <div className="ws-sectionhead">
              <h2>Workspace instruments</h2>
              <span>
                {visibleInstruments.length}{" "}
                {visibleInstruments.length === 1 ? "instrument" : "instruments"}
              </span>
            </div>
            {visibleInstruments.map((record) => (
              <button
                key={record.id}
                className="ws-resource"
                onClick={() => go(routeFor("instrument", record.id))}
              >
                <span className="ws-resourceicon">
                  <FlaskConical />
                </span>
                <span>
                  <strong>{record.name}</strong>
                  <small>{record.measurement}</small>
                </span>
                {record.id === demoInstrument.id ? (
                  <span className={"ws-status " + (activeRun ? "busy" : "")}>
                    <i />
                    {activeRun ? "In use" : "Available"}
                  </span>
                ) : (
                  <span className="ws-status">Inventory only</span>
                )}
                <ChevronRight size={20} />
              </button>
            ))}
            {!visibleInstruments.length && (
              <p className="ws-lede">No matching instruments.</p>
            )}
          </div>
        ) : section === "instrument" && instrument ? (
          <div className="ws-page">
            <button className="ws-back" onClick={() => go("instruments")}>
              <ArrowLeft size={15} />
              Instruments
            </button>
            <div className="ws-pagehead">
              <div>
                <div className="ws-eyebrow">Instrument profile</div>
                <h1>{instrument.name}</h1>
              </div>
              {instrument.id === demoInstrument.id && (
                <button className="ws-button primary" onClick={() => compose()}>
                  <Plus size={16} />
                  New experiment
                </button>
              )}
            </div>
            <p className="ws-lede">
              {instrument.id === demoInstrument.id
                ? "Simulated absorbance measurements for time courses and concentration analysis."
                : "Workspace inventory record. Experiment simulation is available for the demo UV–Vis spectrometer."}
            </p>
            <dl className="ws-definitions">
              <div>
                <dt>Instrument status</dt>
                <dd>
                  {instrument.id === demoInstrument.id ? (
                    <span className={"ws-status " + (activeRun ? "busy" : "")}>
                      <i />
                      {activeRun ? "In use" : "Available"}
                    </span>
                  ) : (
                    "Inventory only"
                  )}
                </dd>
              </div>
              <div>
                <dt>Measurement</dt>
                <dd>
                  {instrument.id === demoInstrument.id
                    ? "UV–visible absorbance"
                    : instrument.measurement}
                </dd>
              </div>
              <div>
                <dt>Data source</dt>
                <dd>
                  {instrument.id === demoInstrument.id
                    ? "Illustrative simulation"
                    : "Workspace inventory"}
                </dd>
              </div>
              {instrument.location && (
                <div>
                  <dt>Location</dt>
                  <dd>{instrument.location}</dd>
                </div>
              )}
            </dl>
            {instrument.id === demoInstrument.id && (
              <>
                <div className="ws-sectionhead">
                  <h2>Recent experiments</h2>
                </div>
                {saved.experiments.slice(0, 3).map(row)}
              </>
            )}
          </div>
        ) : section === "knowledge" ? (
          <div className="ws-page">
            <div className="ws-eyebrow">Workspace</div>
            <div className="ws-pagehead">
              <h1>Lab knowledge</h1>
              <button
                className="ws-button primary"
                onClick={() => show("add-knowledge")}
              >
                <Plus size={16} />
                Add knowledge
              </button>
            </div>
            <p className="ws-lede">
              Method notes and interpretation guides for your workspace.
            </p>
            <div className="ws-toolbar">
              <label className="ws-inputgroup">
                <Search size={17} />
                <input
                  aria-label="Search lab knowledge"
                  placeholder="Find a method or guide…"
                  value={listQuery}
                  onChange={(e) => setListQuery(e.target.value)}
                />
              </label>
            </div>
            {visibleArticles.map((a) => (
              <button
                className="ws-resource"
                key={a.title}
                onClick={() => go(routeFor("article", a.title))}
              >
                <span className="ws-resourceicon">
                  <BookOpen />
                </span>
                <span>
                  <strong>{a.title}</strong>
                  <small>
                    {a.category} · {a.topic}
                  </small>
                </span>
                <ChevronRight className="ws-end" size={20} />
              </button>
            ))}
            {!visibleArticles.length && (
              <p className="ws-lede">No matching guides.</p>
            )}
          </div>
        ) : section === "article" && article ? (
          <article className="ws-page ws-article">
            <button className="ws-back" onClick={() => go("knowledge")}>
              <ArrowLeft size={15} />
              Lab knowledge
            </button>
            <div className="ws-eyebrow">{article.category}</div>
            <h1>{article.title}</h1>
            {article.description && (
              <p className="ws-lede">{article.description}</p>
            )}
            <div className="ws-articlemeta">
              <FileText size={15} />
              {sampleArticles.includes(article)
                ? "Illustrative reference"
                : "Workspace note"}{" "}
              <span>·</span> {article.topic}
            </div>
            {article.paragraphs.map((p, i) => (
              <p key={i} className="ws-note-paragraph">
                {p}
              </p>
            ))}
            <button
              className="ws-button"
              onClick={() =>
                go(
                  baseProjects.includes(article.topic)
                    ? routeFor("project", article.topic)
                    : "experiments",
                )
              }
            >
              Explore related experiments
              <ArrowRight size={16} />
            </button>
          </article>
        ) : (
          <div className="ws-page">
            <h1>Record unavailable</h1>
            <button className="ws-button" onClick={() => go("home")}>
              Return to overview
            </button>
          </div>
        )}
      </main>
      {dialog === "search" && (
        <Modal
          title="Search workspace"
          close={() => setDialog(null)}
          className="ws-searchmodal"
        >
          <label className="ws-inputgroup">
            <Search size={19} />
            <input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search experiments, projects, and guides…"
              aria-label="Search workspace records"
              onKeyDown={(e) => {
                if (e.key === "Enter" && results[0]) go(results[0].to);
                if (e.key === "ArrowDown") {
                  e.preventDefault();
                  document
                    .querySelector<HTMLButtonElement>(
                      ".ws-searchresults button",
                    )
                    ?.focus();
                }
              }}
            />
          </label>
          <div className="ws-searchresults">
            {results.map((r) => (
              <button key={r.to} onClick={() => go(r.to)}>
                <span>{r.label}</span>
                <small>{r.group}</small>
                <ArrowDownRight size={14} />
              </button>
            ))}
            {!results.length && <p>No results for “{query}”.</p>}
          </div>
        </Modal>
      )}
      {dialog === "add-instrument" && (
        <Modal title="Add instrument" close={() => setDialog(null)}>
          <ResourceForm
            kind="instrument"
            names={instruments.map((i) => i.name)}
            onCancel={() => setDialog(null)}
            onSave={(record) => {
              setSaved((old) => ({
                ...old,
                instruments: [...old.instruments, record],
              }));
              go(routeFor("instrument", record.id));
            }}
          />
        </Modal>
      )}
      {dialog === "add-knowledge" && (
        <Modal title="Add lab knowledge" close={() => setDialog(null)}>
          <ResourceForm
            kind="knowledge"
            names={articles.map((a) => a.title)}
            onCancel={() => setDialog(null)}
            onSave={(record) => {
              setSaved((old) => ({
                ...old,
                knowledge: [record, ...old.knowledge],
              }));
              go(routeFor("article", record.title));
            }}
          />
        </Modal>
      )}
      {dialog === "project" && (
        <Modal title="Create project" close={() => setDialog(null)}>
          <form onSubmit={saveProject}>
            <label className="ws-field">
              Project name
              <input
                autoFocus
                value={projectName}
                onChange={(e) => {
                  setProjectName(e.target.value);
                  setProjectError("");
                }}
                placeholder="e.g. Absorbance studies"
                maxLength={72}
              />
            </label>
            {projectError && <p role="alert">{projectError}</p>}
            <div className="ws-actions">
              <button
                type="button"
                className="ws-button"
                onClick={() => setDialog(null)}
              >
                Cancel
              </button>
              <button className="ws-button primary">Create project</button>
            </div>
          </form>
        </Modal>
      )}
      {dialog === "settings" && (
        <Modal
          title="Workspace settings"
          close={() => setDialog(null)}
          className="ws-settings-modal"
        >
          <HarnessSettings
            value={saved.extensions}
            onChange={(extensions) => update({ extensions })}
          />
          <section className="ws-agent-context">
            <h3>Coding agent handoff</h3>
            <p>
              On localhost, starting a run sends the experiment briefing and enabled
              skills to your signed-in Codex worker. Evidence keeps its review and
              the skill versions it received. Connector settings stay in the workspace.
            </p>
            <button
              className="ws-button"
              onClick={() => {
                const file = new Blob(
                  [
                    JSON.stringify(
                      buildAgentContext(saved.extensions),
                      null,
                      2,
                    ) + "\n",
                  ],
                  { type: "application/json" },
                );
                const url = URL.createObjectURL(file);
                const link = document.createElement("a");
                link.href = url;
                link.download = "workspace-agent-context.json";
                link.click();
                window.setTimeout(() => URL.revokeObjectURL(url), 1000);
              }}
            >
              <Download size={16} />
              Download agent context
            </button>
          </section>
          <dl className="ws-definitions">
            <div>
              <dt>Workspace</dt>
              <dd>Emory Biophysics</dd>
            </div>
            <div>
              <dt>Profile</dt>
              <dd>Researcher</dd>
            </div>
            <div>
              <dt>Storage</dt>
              <dd>This browser</dd>
            </div>
          </dl>
          <p>
            Resetting restores the two sample experiments and clears local
            changes.
          </p>
          <button className="ws-button" onClick={() => show("reset")}>
            Reset demo workspace
          </button>
        </Modal>
      )}
      {dialog === "reset" && (
        <Modal title="Reset demo workspace?" close={() => setDialog(null)}>
          <p>
            This clears your local projects, drafts, and review decisions and
            restores the illustrative records.
          </p>
          <div className="ws-actions">
            <button className="ws-button" onClick={() => show("settings")}>
              Cancel
            </button>
            <button
              className="ws-button primary"
              onClick={() => {
                setSaved(initial);
                go("home");
              }}
            >
              Reset workspace
            </button>
          </div>
        </Modal>
      )}
      {dialog === "mode" && (
        <Modal title="Simulation mode" close={() => setDialog(null)}>
          <p>
            Experiments use illustrative readings from a simulated UV–Vis
            spectrometer. Projects and review decisions are saved in this
            browser.
          </p>
          <div className="ws-actions">
            <button
              className="ws-button primary"
              onClick={() => setDialog(null)}
            >
              Got it
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}
