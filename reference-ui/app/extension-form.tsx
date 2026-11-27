import { useState, type FormEvent } from "react";
import {
  isValidEndpoint,
  type CustomConnector,
  type CustomSkill,
} from "./extension-model";

export const endpointError =
  "Enter an HTTP or HTTPS endpoint without credentials, query parameters, or a fragment.";

type FormProps =
  | {
      kind: "connector";
      record?: CustomConnector;
      save: (entry: CustomConnector) => void;
    }
  | { kind: "skill"; record?: CustomSkill; save: (entry: CustomSkill) => void };

export function ExtensionForm(
  props: FormProps & { names: string[]; cancel: () => void },
) {
  const [error, setError] = useState<{ field: string; message: string } | null>(
    null,
  );
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const field = (key: string) => String(data.get(key) ?? "").trim();
    const fail = (key: string, message: string) => {
      setError({ field: key, message });
      const input = form.elements.namedItem(key);
      if (input instanceof HTMLElement) input.focus();
    };
    const name = field("name");
    if (!name) return fail("name", "Enter a name.");
    if (
      props.names.some(
        (existing) => existing.toLowerCase() === name.toLowerCase(),
      )
    )
      return fail("name", "This name is already in use.");
    if (props.kind === "connector") {
      const endpoint = field("endpoint");
      if (!isValidEndpoint(endpoint)) return fail("endpoint", endpointError);
      props.save({
        id: props.record?.id ?? crypto.randomUUID(),
        name,
        endpoint,
        description: field("description"),
      });
    } else {
      const whenToUse = field("whenToUse"),
        instructions = field("instructions");
      if (!whenToUse)
        return fail("whenToUse", "Describe when this skill should be used.");
      if (!instructions)
        return fail("instructions", "Enter instructions for this skill.");
      props.save({
        id: props.record?.id ?? crypto.randomUUID(),
        name,
        whenToUse,
        instructions,
      });
    }
  }
  function fieldProps(field: string) {
    return {
      name: field,
      "aria-invalid": error?.field === field || undefined,
      "aria-describedby":
        error?.field === field ? "ext-field-error" : undefined,
    };
  }
  return (
    <form
      className="ext-form"
      onSubmit={submit}
      onChange={() => setError(null)}
    >
      <label className="ws-field">
        Name
        <input
          {...fieldProps("name")}
          autoFocus
          required
          maxLength={80}
          defaultValue={props.record?.name}
          placeholder={
            props.kind === "connector"
              ? "e.g. Spectroscopy archive"
              : "e.g. Peak assignment"
          }
        />
      </label>
      {props.kind === "connector" ? (
        <>
          <label className="ws-field">
            MCP endpoint
            <input
              {...fieldProps("endpoint")}
              required
              type="url"
              maxLength={512}
              autoComplete="off"
              spellCheck={false}
              defaultValue={props.record?.endpoint}
              placeholder="https://example.org/mcp"
            />
          </label>
          <label className="ws-field">
            Description (optional)
            <textarea
              name="description"
              rows={3}
              maxLength={500}
              defaultValue={props.record?.description}
              placeholder="What does this connector provide?"
            />
          </label>
          <p className="ext-help">
            Connections are simulated in this workspace.
          </p>
        </>
      ) : (
        <>
          <label className="ws-field">
            When to use
            <input
              {...fieldProps("whenToUse")}
              required
              maxLength={240}
              defaultValue={props.record?.whenToUse}
              placeholder="e.g. Reviewing a spectrum"
            />
          </label>
          <label className="ws-field">
            Instructions
            <textarea
              {...fieldProps("instructions")}
              required
              rows={5}
              maxLength={8000}
              defaultValue={props.record?.instructions}
              placeholder="Describe how to complete this task."
            />
          </label>
        </>
      )}
      {error && (
        <p role="alert" id="ext-field-error">
          {error.message}
        </p>
      )}
      <div className="ws-actions">
        <button type="button" className="ws-button" onClick={props.cancel}>
          Cancel
        </button>
        <button type="submit" className="ws-button primary">
          {props.record ? "Save changes" : "Add " + props.kind}
        </button>
      </div>
    </form>
  );
}
