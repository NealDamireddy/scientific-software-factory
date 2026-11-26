// Whether the lab settings form may be used. Pure, so it runs under node --test.
// Until the stored sign-off rule has loaded, the form is disabled: saving then would write the
// defaults over a rule nobody has seen.

export type SettingsLoad = { status: "loading" } | { status: "loaded" } | { status: "failed"; error: string };
export type SettingsLoadEvent = { type: "loaded" } | { type: "failed"; error: string } | { type: "retry" };

export const INITIAL_LOAD: SettingsLoad = { status: "loading" };

export function settingsLoad(state: SettingsLoad, event: SettingsLoadEvent): SettingsLoad {
  switch (event.type) {
    case "loaded":
      return { status: "loaded" };
    case "failed":
      // A rule already on screen stays usable; only a first load that fails blocks the form.
      return state.status === "loaded" ? state : { status: "failed", error: event.error };
    case "retry":
      return state.status === "loaded" ? state : { status: "loading" };
  }
}

export function settingsEditable(state: SettingsLoad): boolean {
  return state.status === "loaded";
}

export function canSaveSettings(state: SettingsLoad, pending: boolean): boolean {
  return settingsEditable(state) && !pending;
}
