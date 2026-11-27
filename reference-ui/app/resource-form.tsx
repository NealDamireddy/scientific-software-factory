import { useState, type FormEvent } from "react";
import "./resource-form.css";

export type InstrumentRecord = {
  id: string;
  name: string;
  measurement: string;
  location: string;
};

export type KnowledgeRecord = {
  title: string;
  category: string;
  topic: string;
  description: string;
  paragraphs: string[];
};

type ResourceFormProps =
  | { kind: "instrument"; onSave: (record: InstrumentRecord) => void }
  | { kind: "knowledge"; onSave: (record: KnowledgeRecord) => void };

export function ResourceForm(
  props: ResourceFormProps & { names: string[]; onCancel: () => void },
) {
  const [error, setError] = useState("");
  const isInstrument = props.kind === "instrument";
  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const field = (key: string) => String(data.get(key) ?? "").trim();
    const name = field("name");
    if (!name || !field("detail")) {
      setError(
        isInstrument
          ? "Enter an instrument name and measurement."
          : "Enter a title and note.",
      );
      return;
    }
    if (
      props.names.some(
        (existing) => existing.toLowerCase() === name.toLowerCase(),
      )
    ) {
      setError(
        isInstrument
          ? "An instrument with that name already exists."
          : "A knowledge entry with that title already exists.",
      );
      return;
    }
    if (props.kind === "instrument") {
      props.onSave({
        id: crypto.randomUUID(),
        name,
        measurement: field("detail"),
        location: field("topic"),
      });
    } else {
      props.onSave({
        title: name,
        category: field("category"),
        topic: field("topic") || "General",
        description: "",
        paragraphs: field("detail")
          .split(/\n\s*\n/)
          .map((s) => s.trim())
          .filter(Boolean),
      });
    }
  }
  return (
    <form
      className="ws-resourceform"
      onSubmit={save}
      onChange={() => setError("")}
    >
      <label className="ws-field">
        {isInstrument ? "Instrument name" : "Title"}
        <input
          name="name"
          autoFocus
          required
          maxLength={100}
          placeholder={
            isInstrument
              ? "e.g. Plate reader"
              : "e.g. Reading a calibration plot"
          }
        />
      </label>
      {!isInstrument && (
        <label className="ws-field">
          Category
          <select name="category">
            <option>Method note</option>
            <option>Analysis guide</option>
            <option>Lab reference</option>
          </select>
        </label>
      )}
      {isInstrument && (
        <label className="ws-field">
          Measurement
          <input
            name="detail"
            required
            maxLength={160}
            placeholder="e.g. Fluorescence intensity"
          />
        </label>
      )}
      <label className="ws-field">
        {isInstrument ? "Location (optional)" : "Topic (optional)"}
        <input
          name="topic"
          maxLength={100}
          placeholder={
            isInstrument ? "e.g. Optical bench 2" : "e.g. Spectroscopy"
          }
        />
      </label>
      {!isInstrument && (
        <label className="ws-field">
          Note
          <textarea
            name="detail"
            required
            rows={5}
            placeholder="Write the reference material for your lab…"
            maxLength={30000}
          />
        </label>
      )}
      {isInstrument && (
        <p className="ws-formhint">
          This adds an inventory record to your workspace.
        </p>
      )}
      {error && <p role="alert">{error}</p>}
      <div className="ws-actions">
        <button className="ws-button" type="button" onClick={props.onCancel}>
          Cancel
        </button>
        <button className="ws-button primary" type="submit">
          {isInstrument ? "Add instrument" : "Save knowledge"}
        </button>
      </div>
    </form>
  );
}
