"use client";

import { useId, useRef, useState, type ChangeEvent, type ReactNode } from "react";

import { approvalMatches, contractOutputs } from "./api";
import type {
  FieldErrors,
  Instrument,
  Lab,
  Pin,
  Project,
  Revision,
  Snapshot,
  Specification,
  SpecInput,
  WorkspaceClient,
} from "./api";

type Props = {
  editProject: () => void;
  section: "context" | "specification";
  client: WorkspaceClient;
  projectId: string;
  snapshot: Snapshot;
  operate: <T>(action: () => Promise<T>) => Promise<T | undefined>;
  errors: FieldErrors;
};

type FieldProps = {
  label: string;
  value: string | number;
  onChange?: (value: string) => void;
  error?: string;
  multiline?: boolean;
  readOnly?: boolean;
  type?: "text" | "number";
  min?: number;
  max?: number;
  step?: number | "any";
};

function Field({ label, value, onChange, error, multiline, ...rest }: FieldProps) {
  const id = useId();
  const common = {
    id,
    value,
    "aria-invalid": Boolean(error),
    "aria-describedby": error ? id + "-error" : undefined,
    onChange: (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange?.(event.target.value),
  };
  return (
    <div className="workspace-field">
      <label htmlFor={id}>{label}</label>
      {multiline ? (
        <textarea {...common} readOnly={rest.readOnly} rows={2} />
      ) : (
        <input {...common} {...rest} />
      )}
      {error && (
        <small className="field-error" id={id + "-error"}>
          {error}
        </small>
      )}
    </div>
  );
}

function Select({
  label,
  value,
  onChange,
  children,
  error,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  children: ReactNode;
  error?: string;
}) {
  const id = useId();
  return (
    <div className="workspace-field">
      <label htmlFor={id}>{label}</label>
      <select
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={Boolean(error)}
        aria-describedby={error ? id + "-error" : undefined}
      >
        {children}
      </select>
      {error && (
        <small className="field-error" id={id + "-error"}>
          {error}
        </small>
      )}
    </div>
  );
}

function lines(value: string) {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

function latest<T extends { revision: number }>(records: T[]) {
  return records.reduce<T | undefined>(
    (last, item) => (!last || item.revision > last.revision ? item : last),
    undefined,
  );
}

function contextPin({ lab_id, project_id, revision, sha256 }: Pin): Pin {
  return { lab_id, project_id, revision, sha256 };
}

function RevisionSelect<T>({
  label,
  records,
  selected,
  select,
}: {
  label: string;
  records: Revision<T>[];
  selected?: Revision<T>;
  select: (record: Revision<T>) => void;
}) {
  return (
    <Select
      label={label}
      value={selected ? String(selected.revision) : ""}
      onChange={(value) => {
        const record = records.find((row) => row.revision === Number(value));
        if (record) select(record);
      }}
    >
      {!selected && <option value="">New context</option>}
      {records.map((row) => (
        <option key={row.revision} value={row.revision}>
          Revision {row.revision}
        </option>
      ))}
    </Select>
  );
}

function blankInstrument(lab_id: string): Instrument {
  return { lab_id, instrument_id: "", profile_id: "", profile_sha256: "" };
}

function labForm(record?: Revision<Lab>) {
  const lab = record?.payload;
  return {
    record,
    lab_id: lab?.lab_id ?? "",
    name: lab?.name ?? "",
    instruments: lab?.instruments ?? [blankInstrument("")],
    approved_libraries: lab?.approved_libraries.join("\n") ?? "",
    operating_restrictions: lab?.operating_restrictions.join("\n") ?? "",
  };
}

function LabEditor({ snapshot, client, projectId, operate, errors }: Props) {
  const [form, set] = useState(() => labForm(latest(snapshot.labs)));
  const [message, setMessage] = useState("");
  const update = (patch: Partial<typeof form>) => {
    set({ ...form, ...patch });
    setMessage("");
  };
  const instrumentChange = (index: number, key: keyof Instrument, value: string) =>
    update({
      instruments: form.instruments.map((item, i) => (i === index ? { ...item, [key]: value } : item)),
    });
  async function save() {
    setMessage("");
    const payload: Lab = {
      schema_version: 1,
      name: form.name,
      lab_id: form.lab_id,
      instruments: form.instruments.map((item) => ({ ...item, lab_id: form.lab_id })),
      approved_libraries: lines(form.approved_libraries),
      operating_restrictions: lines(form.operating_restrictions),
    };
    const result = await operate(() => client.saveLab(projectId, payload, form.record?.revision ?? 0));
    if (result) {
      set(labForm(result));
      setMessage("Saved lab revision " + result.revision + ".");
    }
  }
  return (
    <form
      className="workspace-card"
      aria-label="Lab context"
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
    >
      <h2>Lab context</h2>
        <Field label="Lab name" value={form.name} onChange={(name) => update({ name })} error={errors.name} />
      <div className="field-grid">
        <Field
          label="Approved libraries (one per line)"
          value={form.approved_libraries}
          multiline
          onChange={(approved_libraries) => update({ approved_libraries })}
          error={errors.approved_libraries}
        />
        <Field
          label="Operating restrictions (one per line)"
          value={form.operating_restrictions}
          multiline
          onChange={(operating_restrictions) => update({ operating_restrictions })}
          error={errors.operating_restrictions}
        />
      </div>
      <details className="technical"><summary>Lab revisions and instrument profiles</summary>
      <RevisionSelect
        label="Lab revision"
        records={snapshot.labs}
        selected={form.record}
        select={(record) => {
          set(labForm(record));
          setMessage("");
        }}
      />
      <div className="field-grid">
        <Field
          label="Lab ID"
          value={form.lab_id}
          readOnly={!!form.record}
          onChange={(lab_id) => update({ lab_id })}
          error={errors.lab_id}
        />
      </div>
      {form.instruments.map((item, index) => (
        <fieldset key={index}>
          <legend>Instrument {index + 1}</legend>
          <div className="field-grid">
            {(["instrument_id", "profile_id", "profile_sha256"] as const).map((key, i) => (
              <Field
                key={key}
                label={["Instrument ID", "Profile ID", "Profile digest (SHA-256)"][i]}
                value={item[key]}
                onChange={(value) => instrumentChange(index, key, value)}
                error={errors[`instruments.${index}.${key}`]}
              />
            ))}
          </div>
          {form.instruments.length > 1 && (
            <button
              type="button"
              onClick={() => update({ instruments: form.instruments.filter((_, i) => i !== index) })}
            >
              Remove instrument {index + 1}
            </button>
          )}
        </fieldset>
      ))}
      <button
        type="button"
        onClick={() => update({ instruments: [...form.instruments, blankInstrument(form.lab_id)] })}
      >
        Add instrument
      </button>
      </details>
      <div className="actions">
        <button>Save lab revision</button>
        <span role="status">{message}</span>
      </div>
    </form>
  );
}

function projectForm(record?: Revision<Project>) {
  const p = record?.payload;
  return {
    record,
    lab_id: p?.lab_id ?? "",
    instrument_id: p?.instrument_id ?? "",
    scientific_objective: p?.scientific_objective ?? "",
    protocol_id: p?.protocol_id ?? "",
    protocol_revision: p ? String(p.protocol_revision) : "",
    units: p?.units ?? { concentration: "", wavelength: "", path_length: "" },
    analysis_method: p?.analysis_method ?? "",
    validation_criteria: p?.validation_criteria.join("\n") ?? "",
  };
}

function ProjectEditor({ snapshot, client, projectId, operate, errors }: Props) {
  const [form, set] = useState(() => projectForm(latest(snapshot.projects)));
  const [message, setMessage] = useState("");
  const update = (patch: Partial<typeof form>) => {
    set({ ...form, ...patch });
    setMessage("");
  };
  async function save() {
    setMessage("");
    const { record, ...values } = form;
    const payload = {
      ...record?.payload,
      ...values,
      schema_version: 1,
      project_id: projectId,
      protocol_revision: Number(form.protocol_revision),
      validation_criteria: lines(form.validation_criteria),
    };
    const result = await operate(() => client.saveProject(projectId, payload, record?.revision ?? 0));
    if (result) {
      set(projectForm(result));
      setMessage("Saved project revision " + result.revision + ".");
    }
  }
  return (
    <form
      className="workspace-card"
      aria-label="Project context"
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
    >
      <h2>Project context</h2>
        <Field
          label="Scientific objective" multiline
          value={form.scientific_objective}
          onChange={(scientific_objective) => update({ scientific_objective })}
          error={errors.scientific_objective}
        />
        <Field
          label="Analysis method" multiline
          value={form.analysis_method}
          onChange={(analysis_method) => update({ analysis_method })}
          error={errors.analysis_method}
        />
        <Field
          label="Validation criteria (one per line)"
          multiline
          value={form.validation_criteria}
          onChange={(validation_criteria) => update({ validation_criteria })}
          error={errors.validation_criteria}
        />
      <details className="technical"><summary>Project revisions, instrument and protocol</summary>
      <RevisionSelect
        label="Project revision"
        records={snapshot.projects}
        selected={form.record}
        select={(record) => {
          set(projectForm(record));
          setMessage("");
        }}
      />
      <div className="field-grid">
        <Field label="Project ID" readOnly value={projectId} onChange={() => {}} />
        <Field
          label="Project lab ID"
          value={form.lab_id}
          readOnly={!!form.record}
          onChange={(lab_id) => update({ lab_id })}
          error={errors.lab_id}
        />
        <Field
          label="Project instrument ID"
          value={form.instrument_id}
          onChange={(instrument_id) => update({ instrument_id })}
          error={errors.instrument_id}
        />
        <Field
          label="Protocol ID"
          value={form.protocol_id}
          onChange={(protocol_id) => update({ protocol_id })}
          error={errors.protocol_id}
        />
        <Field
          label="Protocol revision"
          value={form.protocol_revision}
          type="number"
          min={1}
          step={1}
          onChange={(protocol_revision) => update({ protocol_revision })}
          error={errors.protocol_revision}
        />
        {(["concentration", "wavelength", "path_length"] as const).map((unit, i) => (
          <Field
            key={unit}
            label={["Concentration unit", "Wavelength unit", "Path length unit"][i]}
            value={form.units[unit]}
            onChange={(value) => update({ units: { ...form.units, [unit]: value } })}
            error={errors["units." + unit]}
          />
        ))}
      </div></details>
      <div className="actions">
        <button>Save project revision</button>
        <span role="status">{message}</span>
      </div>
    </form>
  );
}

function specForm(project?: Pin, spec?: Specification) {
  return {
    record: spec,
    projectRevision: spec?.project.revision ?? project?.revision,
    experiment_type: spec?.experiment_type ?? "concentration",
    sample_ids: spec?.sample_ids.join("\n") ?? "",
    standards: (spec?.standards ?? []).map((s) => ({
      sample_id: s.sample_id,
      level: String(s.known_concentration ?? ""),
    })),
    calibration: spec?.calibration?.sha256 ?? "",
    wavelength: String(spec?.settings.wavelength_nm ?? ""),
    replicates: String(spec ? spec.settings.replicates ?? "" : 3),
    pathLength: String(spec ? spec.settings.path_length_mm ?? "" : 10),
    interval: String(spec?.schedule?.interval_s ?? ""),
    points: String(spec?.schedule?.point_count ?? ""),
  };
}

function confirmFields(spec: Specification) {
  const fields = ["experiment_type", "settings", "sample_ids", "units", "outputs", "validation_criteria"];
  if (spec.standards.length) fields.push("standards");
  if (spec.calibration) fields.push("calibration");
  if (spec.schedule) fields.push("schedule");
  return fields.sort();
}

function SpecificationEditor({ editProject, snapshot, client, projectId, operate, errors }: Props) {
  const [form, set] = useState(() => specForm(latest(snapshot.projects)));
  const [dirty, setDirty] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [message, setMessage] = useState("");
  const submission = useRef("");
  const [submitted, setSubmitted] = useState(false);
  const record = form.record;
  const project = snapshot.projects.find((row) =>
    row.project_id === projectId &&
    row.revision === (record?.project.revision ?? form.projectRevision) &&
    (!record || (row.sha256 === record.project.sha256 && row.lab_id === record.project.lab_id)),
  );
  const lab = snapshot.labs.find(
    (row) =>
      row.lab_id === project?.lab_id &&
      row.revision === project?.lab_revision &&
      row.sha256 === project.lab_sha256,
  );
  const instrument = lab?.payload.instruments.find(
    (item) => item.instrument_id === project?.payload.instrument_id,
  );
  // Reopening a saved revision must show exactly what its digest covered.
  const reviewing = dirty ? undefined : record;
  const outputs = reviewing?.outputs ?? contractOutputs(form.experiment_type);
  const criteria = reviewing?.validation_criteria ?? project?.payload.validation_criteria ?? [];
  const units = reviewing?.units ?? project?.payload.units;
  const course = form.experiment_type === "time_course";

  function open(spec?: Specification) {
    set(specForm(latest(snapshot.projects), spec));
    setDirty(false);
    setConfirmed(false);
    setMessage("");
    submission.current = "";
    setSubmitted(false);
  }
  function update(patch: Partial<typeof form>) {
    set({ ...form, ...patch });
    setDirty(true);
    setConfirmed(false);
    setMessage("");
  }
  function applyProtocol() {
    if (!project) return;
    const protocol = project.payload;
    update({
      sample_ids: (protocol.sample_ids ?? []).join("\n"),
      standards: course
        ? []
        : (protocol.standards ?? []).map((s) => ({
            sample_id: s.sample_id,
            level: String(s.known_concentration ?? ""),
          })),
    });
  }
  async function save() {
    setMessage("");
    if (!lab || !project || !instrument) {
      setMessage("Select a saved project revision and its registered lab instrument.");
      return;
    }
    const payload: SpecInput = {
      ...(record && { specification_id: record.specification_id }),
      lab: record?.lab ?? contextPin(lab),
      project: record?.project ?? contextPin(project),
      instrument: record?.instrument ?? instrument,
      experiment_type: form.experiment_type,
      sample_ids: lines(form.sample_ids),
      units: project.payload.units,
      outputs: contractOutputs(form.experiment_type),
      validation_criteria: project.payload.validation_criteria,
      standards: course
        ? []
        : form.standards.map((s) => ({ sample_id: s.sample_id, known_concentration: s.level ? Number(s.level) : null })),
      calibration: snapshot.calibrations.find((row) => row.sha256 === form.calibration) ?? null,
      settings: {
        operation: "measure-absorbance",
        wavelength_nm: form.wavelength ? Number(form.wavelength) : null,
        path_length_mm: form.pathLength ? Number(form.pathLength) : null,
        replicates: form.replicates ? Number(form.replicates) : null,
      },
      schedule:
        course && (form.interval || form.points)
          ? { interval_s: form.interval ? Number(form.interval) : null, point_count: form.points ? Number(form.points) : null }
          : null,
    };
    const saved = await operate(() => client.saveSpecification(projectId, payload, record?.revision ?? 0));
    if (saved) {
      open(saved);
      setMessage("Saved unapproved draft revision " + saved.revision + ".");
    }
  }
  async function approve() {
    if (!record || dirty || !confirmed) return;
    setMessage("");
    const approved = await operate(() => client.approve(projectId, record, confirmFields(record)));
    if (approved) {
      open(approved);
      setMessage("Approved revision " + approved.revision + ".");
    }
  }
  async function submit() {
    if (!record || !approvalMatches(record) || dirty || submitted) return;
    submission.current ||= crypto.randomUUID();
    const key = submission.current;
    setMessage("");
    const result = await operate(() => client.submit(projectId, record, key));
    if (result) {
      setSubmitted(true);
      setMessage("Submitted run " + result.run_id + ".");
    }
  }
  const approved = approvalMatches(record) && !dirty;
  const staleApproval = !!record?.approval && !approvalMatches(record);
  const unresolved = !dirty ? record?.unresolved_fields ?? {} : {};
  const reviewErrors = { ...unresolved, ...errors };
  return (
    <section className="workspace-card" aria-label="Experiment specification">
      <h1>Experiment specification</h1>
      <p className="objective">{project?.payload.scientific_objective}</p>
      <p>{course ? "Produce a calibrated concentration series over time with replicate SD and review findings." : "Produce calibrated concentrations with replicate SD and review findings for each sample."}</p>
      <Select
        label="Saved specification"
        value={record?.sha256 ?? ""}
        onChange={(value) => open(snapshot.specifications.find((s) => s.sha256 === value))}
      >
        <option value="">New specification</option>
        {snapshot.specifications.map((s) => (
          <option key={s.sha256} value={s.sha256}>
            {s.specification_id} · revision {s.revision} · {s.status}
          </option>
        ))}
      </Select>
      <form
        noValidate
        aria-label="Specification fields"
        onSubmit={(event) => {
          event.preventDefault();
          void save();
        }}
      >
        <div className="field-grid">
          {record ? (
            <Field label="Specification project revision" readOnly
              value={record.project.project_id + " · revision " + record.project.revision} />
          ) : (
            <Select
              label="Specification project revision"
              value={String(form.projectRevision ?? "")}
              onChange={(value) => update({ projectRevision: Number(value) || undefined })}
              error={reviewErrors.project}
            >
              <option value="">Select a project revision</option>
              {snapshot.projects.map((p) => (
                <option key={p.revision} value={p.revision}>
                  {p.project_id} · revision {p.revision}
                </option>
              ))}
            </Select>
          )}
          <Select
            label="Experiment type"
            value={form.experiment_type}
            error={reviewErrors.experiment_type}
            onChange={(value) =>
              update({ experiment_type: value as SpecInput["experiment_type"] })
            }
          >
            <option value="concentration">Concentration</option>
            <option value="time_course">Time course</option>
            {!(["concentration", "time_course"] as string[]).includes(form.experiment_type) && (
              <option value={form.experiment_type}>Unsupported type · {form.experiment_type}</option>
            )}
          </Select>
        </div>
        <h3>What will you measure?</h3>
        <p>{course ? "Approval requires samples, wavelength, a frozen calibration, interval and point count." : "Confirm samples, wavelength and calibration before approval."}</p>
        <button type="button" disabled={!project} onClick={applyProtocol}>
          Use project protocol
        </button>
        <div className="field-grid">
          <Field
            label="Sample IDs (one per line)"
            multiline
            value={form.sample_ids}
            onChange={(sample_ids) => update({ sample_ids })}
            error={reviewErrors.sample_ids}
          />
        </div>
        <fieldset>
          <legend>Measurement settings</legend>
          <div className="field-grid">
            <Field
              label="Wavelength (nm)"
              type="number"
              step="any"
              value={form.wavelength}
              onChange={(wavelength) => update({ wavelength })}
              error={reviewErrors["settings.wavelength_nm"]}
            />
            <Field
              label="Replicates"
              type="number"
              value={form.replicates}
              min={1}
              max={10}
              onChange={(replicates) => update({ replicates })}
              error={reviewErrors["settings.replicates"]}
            />
            <Field
              label="Path length (mm)"
              type="number"
              step="any"
              value={form.pathLength}
              onChange={(pathLength) => update({ pathLength })}
              error={reviewErrors["settings.path_length_mm"]}
            />
            {course && (
              <>
                <Field
                  label="Interval (seconds)"
                  type="number"
                  min={1}
                  max={3600}
                  step="any"
                  value={form.interval}
                  onChange={(interval) => update({ interval })}
                  error={reviewErrors["schedule.interval_s"]}
                />
                <Field
                  label="Point count"
                  type="number"
                  min={2}
                  max={100}
                  step={1}
                  value={form.points}
                  onChange={(points) => update({ points })}
                  error={reviewErrors["schedule.point_count"]}
                />
              </>
            )}
          </div>
        </fieldset>
        <Select
          label={course ? "Frozen calibration" : "Frozen calibration (optional)"}
          value={form.calibration}
          onChange={(calibration) => update({ calibration })}
          error={reviewErrors.calibration}
        >
          <option value="">{course ? "Select a calibration" : "No saved calibration"}</option>
          {snapshot.calibrations.map((c) => (
            <option key={c.sha256} value={c.sha256}>
              {c.id} · {c.unit} · {c.settings.wavelength_nm} nm
            </option>
          ))}
        </Select>
        {!course && (
          <fieldset>
            <legend>Calibration standards</legend>
            {form.standards.map((s, index) => (
              <div className="field-grid" key={index}>
                <Field
                  label={`Standard ${index + 1} sample ID`}
                  value={s.sample_id}
                  onChange={(sample_id) =>
                    update({
                      standards: form.standards.map((row, i) => (i === index ? { ...row, sample_id } : row)),
                    })
                  }
                />
                <Field
                  label={`Standard ${index + 1} concentration (${units?.concentration || "unit unspecified"})`}
                  type="number"
                  step="any"
                  value={s.level}
                  onChange={(level) =>
                    update({
                      standards: form.standards.map((row, i) => (i === index ? { ...row, level } : row)),
                    })
                  }
                />
                <button
                  type="button"
                  onClick={() => update({ standards: form.standards.filter((_, i) => i !== index) })}
                >
                  Remove standard {index + 1}
                </button>
              </div>
            ))}
            {reviewErrors.standards && <p className="field-error">{reviewErrors.standards}</p>}
            <button
              type="button"
              onClick={() => update({ standards: [...form.standards, { sample_id: "", level: "" }] })}
            >
              Add standard
            </button>
          </fieldset>
        )}
        <h3>What should the app produce?</h3>
        <p>{outputs.map(key => ({ calibration_id: "Calibration reference", sample_id: "Sample ID", concentration_mg_l: "Concentration", replicate_sd_mg_l: "Replicate SD", review_reason: "Review reason", timestamp: "Measurement time" }[key] ?? key)).join(" · ")}</p>
        <details className="technical"><summary>Output schema keys</summary><code>{outputs.join(", ")}</code></details>
        {reviewErrors.outputs && <p className="field-error">{reviewErrors.outputs}</p>}
        <h3>When should it flag a result?</h3>
        <p>Inherited validation criteria</p>
        <ul>{criteria.map((criterion,i) => <li key={i}>{criterion}</li>)}</ul>
        {reviewErrors.validation_criteria && <p className="field-error">{reviewErrors.validation_criteria}</p>}
        <p>Protocol units · {[units?.concentration, units?.wavelength, units?.path_length].filter(Boolean).join(" · ") || "Unspecified"}</p>
        {Object.entries(reviewErrors).filter(([key]) => key.startsWith("units.")).map(([key, reason]) => <p key={key} className="field-error">{key.slice(6)} · {reason}</p>)}
        <button type="button" onClick={editProject}>Edit project protocol</button>
        {project && (
          <details className="technical"><summary>Inherited protocol and revision details</summary><dl>
            <dt>Project digest</dt>
            <dd>
              <code>{project.sha256}</code>
            </dd>
            <dt>Lab revision</dt>
            <dd>
              {project.lab_id} · {project.lab_revision} · <code>{project.lab_sha256}</code>
            </dd>
            <dt>Instrument profile</dt>
            <dd>
              {instrument?.instrument_id} · {instrument?.profile_id} ·{" "}
              <code>{instrument?.profile_sha256}</code>
            </dd>
            <dt>Protocol</dt>
            <dd>
              {project.payload.protocol_id} · revision {project.payload.protocol_revision}
            </dd>
            <dt>Analysis method</dt>
            <dd>{project.payload.analysis_method}</dd>
          </dl></details>
        )}
        <div className="actions">
          <button>Save draft</button>
        </div>
      </form>
      {record && (
        <section aria-label="Revision approval">
          <h3>
            {dirty
              ? "Unsaved changes · approval required"
              : approved
                ? "Approved specification"
                : staleApproval
                  ? "Approval does not match this revision"
                  : "Draft awaiting approval"}
          </h3>
          <details className="technical"><summary>Revision and approval details</summary><dl>
            <dt>Saved specification</dt>
            <dd>
              {record.specification_id} · revision {record.revision} · <code>{record.sha256}</code>
            </dd>
            <dt>Pinned project</dt>
            <dd>
              {record.project.project_id} · revision {record.project.revision} ·{" "}
              <code>{record.project.sha256}</code>
            </dd>
            <dt>Pinned lab</dt>
            <dd>
              {record.lab.lab_id} · revision {record.lab.revision} · <code>{record.lab.sha256}</code>
            </dd>
            {record.approval && (
              <>
                <dt>Saved approval</dt>
                <dd>
                  {record.approval.actor} · <time>{record.approval.approved_at}</time>
                </dd>
                <dt>Approved digest</dt>
                <dd>
                  <code>{record.approval.specification_sha256}</code>
                </dd>
              </>
            )}
          </dl></details>
          {Object.keys(unresolved).length > 0 && <div aria-label="Unresolved scientific fields" role="region">
            <h4>Resolve before approval</h4>
            <ul>{Object.entries(unresolved).map(([field, reason]) => <li key={field}>{field} · {reason}</li>)}</ul>
          </div>}
          {!approvalMatches(record) && (
            <label className="confirm-fields">
              <input
                type="checkbox"
                checked={confirmed}
                disabled={dirty || Object.keys(unresolved).length > 0}
                onChange={(event) => setConfirmed(event.target.checked)}
              />
              Confirm scientific fields for this revision
              {course && ` (including interval ${form.interval} s and ${form.points} points)`}
            </label>
          )}
          <div className="actions">
            {!approvalMatches(record) && (
              <button type="button" disabled={dirty || !confirmed} onClick={approve}>
                Approve revision
              </button>
            )}
            <button type="button" disabled={!approved || submitted} onClick={submit}>
              Submit experiment
            </button>
          </div>
        </section>
      )}
      <p role="status">{message}</p>
    </section>
  );
}

function FactValue({label,value}: {label:string; value?:string}) {
  return <div><dt>{label}</dt><dd>{value || "Unspecified"}</dd></div>;
}

export default function Editors(props: Props) {
  return (
    <>
      <div hidden={props.section !== "context"}>
        <section className="context-lead"><h1>Lab &amp; project</h1>
          <p>{latest(props.snapshot.projects)?.payload.scientific_objective}</p>
          <dl><FactValue label="Instrument" value={latest(props.snapshot.projects)?.payload.instrument_id}/>
          <FactValue label="Analysis method" value={latest(props.snapshot.projects)?.payload.analysis_method}/>
          <FactValue label="Operating restrictions" value={latest(props.snapshot.labs)?.payload.operating_restrictions.join(" · ")}/></dl>
        </section>
        <ProjectEditor {...props} />
        <LabEditor {...props} />
      </div>
      <div hidden={props.section !== "specification"}>
        <SpecificationEditor {...props} />
      </div>
    </>
  );
}
