// Sample content: the example lab, reference cases, step and run-plan templates
// that work for any instrument, check helpers shaped like the backend's
// checks.py, and the view builders. Pure data and functions, no DOM.
import type {
  Action, CheckResult, Command, Document, Experiment, Instrument, Lab, Parameter, ReferenceCase,
  RunPlan, RunStep, RunStepView, Setting, SettingView, StepView, ProcedureStep,
} from "../types.ts";

/** Same content as lab-factory/examples/uvvis-lab.json. Fresh object each call. */
export function sampleLab(): Lab {
  return {
    id: "emory-biophys",
    name: "Emory Biophysics",
    instruments: [
      {
        id: "uvvis-1",
        name: "UV-visible spectrophotometer",
        model: "SP-550",
        firmware: "2.3.1",
        notes: "Teaching instrument for absorbance measurements.",
        parameters: [
          { name: "wavelength", unit: "nm", minimum: 400, maximum: 700 },
          { name: "temperature", unit: "K", minimum: 278.15, maximum: 303.15 },
          { name: "integration_time", unit: "s", minimum: 0.1, maximum: 10 },
        ],
        commands: [
          { name: "read_absorbance", required: ["wavelength"], optional: ["integration_time"] },
          { name: "set_temperature", required: ["temperature"], optional: [] },
        ],
      },
    ],
    documents: [
      {
        id: "sop-cuvette",
        kind: "sop",
        title: "Cuvette handling",
        source: "Teaching lab SOP",
        text: "Rinse the cuvette and keep the optical faces clean.",
      },
    ],
  };
}

/** Same content as lab-factory/examples/b12-experiment.json, plus project_id. */
export function sampleB12Experiment(): Experiment {
  return {
    id: "b12-vial-a",
    lab_id: "emory-biophys",
    project_id: "b12-quantification",
    title: "Vitamin B12 absorbance",
    goal: "Measure absorbance of the reference solution in vial A.",
    instrument_ids: ["uvvis-1"],
    documents: [
      {
        id: "b12-protocol",
        kind: "sop",
        title: "Vial A protocol",
        source: "Experiment notebook",
        text: "Use the labeled reference solution in vial A.",
      },
    ],
  };
}

export const REFERENCE_CASES: ReferenceCase[] = [
  {
    name: "Clean decay",
    input: { k: 0.01, a0: 0.8, a_end: 0.05, noise: 0, seed: 1 },
    expect: { decay: true, rate_constant_per_s: 0.01 },
    rel_tol: 0.01,
  },
  {
    name: "Noisy decay",
    input: { k: 0.01, a0: 0.8, a_end: 0.05, noise: 0.005, seed: 2 },
    expect: { decay: true, rate_constant_per_s: 0.01 },
    rel_tol: 0.05,
  },
  {
    name: "No reaction",
    input: { k: 0, a0: 0.6, a_end: 0.6, noise: 0.003, seed: 3 },
    expect: { decay: false },
    rel_tol: 0.05,
  },
];

/** The reference cases as a fresh copy, for records that must not share objects. */
export function referenceCases(): ReferenceCase[] {
  return REFERENCE_CASES.map((c) => ({ ...c, input: { ...c.input }, expect: { ...c.expect } }));
}

// A value inside the parameter's limits: the midpoint, rounded to 2 decimals and clamped.
function inRangeValue(parameter: Parameter): number {
  const mid = Math.round(((parameter.minimum + parameter.maximum) / 2) * 100) / 100;
  return Math.min(parameter.maximum, Math.max(parameter.minimum, mid));
}

function commandSettings(instrument: Instrument, command: Command): Setting[] {
  const settings: Setting[] = [];
  for (const name of command.required) {
    const parameter = instrument.parameters.find((p) => p.name === name);
    if (parameter) settings.push({ parameter: name, value: inRangeValue(parameter), unit: parameter.unit });
  }
  return settings;
}

function words(name: string): string {
  return name.replace(/[_-]+/g, " ").replace(/\d+/g, "").trim();
}

/**
 * Procedure steps that pass every check for any instrument: one preparation step,
 * one step per command with its required settings at in-range values, and a
 * closing step. Step texts carry no instrument values or units, and every step
 * cites one of the given citations (rotating through them).
 */
export function procedureTemplate(instrument: Instrument, citations: string[]): ProcedureStep[] {
  const cite = (index: number): string[] => (citations.length === 0 ? [] : [citations[index % citations.length]]);
  const steps: ProcedureStep[] = [
    {
      text: "Prepare the sample as described in the cited source.",
      citations: cite(0),
      amounts: [{ what: "sample", value: 1, unit: "mL" }],
    },
  ];
  instrument.commands.forEach((command, i) => {
    const action: Action = {
      instrument_id: instrument.id,
      command: command.name,
      settings: commandSettings(instrument, command),
    };
    steps.push({ text: `Use ${words(command.name)} on the prepared sample.`, citations: cite(i + 1), action });
  });
  steps.push({ text: "Record the result and clean up as described in the cited source.", citations: cite(instrument.commands.length + 1) });
  return steps;
}

/** A run plan that passes every check: one step per command, required settings at in-range values. */
export function runPlanTemplate(instrument: Instrument): RunPlan {
  return {
    instrument_id: instrument.id,
    steps: instrument.commands.map((command): RunStep => ({
      command: command.name,
      settings: commandSettings(instrument, command),
    })),
  };
}

const TEXT_VALUE = /\d+(\.\d+)?\s*(nm|mL|uL|s|min|h|K|degC|°C)\b/g;

const KNOWN_AMOUNT_UNITS = ["mL", "uL", "L", "mg", "g", "ug", "mM", "uM", "M", "mg/L"];

function commandResults(
  prefix: string, instrumentId: string, instruments: Instrument[], commandName: string,
  settings: Setting[], thorough: boolean,
): CheckResult[] {
  const instrument = instruments.find((i) => i.id === instrumentId);
  const command = instrument?.commands.find((c) => c.name === commandName);
  const results: CheckResult[] = [];
  if (thorough) {
    const problems: string[] = [];
    if (!instrument) problems.push(`unknown instrument ${instrumentId}`);
    else if (!command) problems.push(`unknown command ${commandName} on ${instrumentId}`);
    else {
      for (const name of command.required) {
        if (!settings.some((s) => s.parameter === name)) problems.push(`missing required setting ${name}`);
      }
    }
    results.push({
      name: prefix + "command",
      passed: problems.length === 0,
      detail: problems.length ? problems.join("; ") : `${commandName} has all required settings`,
    });
  }
  for (const setting of settings) {
    const parameter = instrument?.parameters.find((p) => p.name === setting.parameter);
    const label = `${setting.value} ${setting.unit}`;
    let error: string | null = null;
    if (!instrument) error = `unknown instrument ${instrumentId}`;
    else if (!parameter) error = `unknown parameter ${setting.parameter}`;
    else if (!command) error = `unknown command ${commandName} on ${instrumentId}`;
    else if (!command.required.includes(setting.parameter) && !command.optional.includes(setting.parameter)) {
      error = `${setting.parameter} not accepted by ${command.name}`;
    } else if (settings.filter((s) => s.parameter === setting.parameter).length > 1) {
      error = `duplicate setting ${setting.parameter}`;
    } else if (setting.unit !== parameter.unit) error = `unknown unit ${setting.unit} for ${parameter.name}`;
    else if (setting.value > parameter.maximum) error = `${label} is above the maximum ${parameter.maximum} ${parameter.unit}`;
    else if (setting.value < parameter.minimum) error = `${label} is below the minimum ${parameter.minimum} ${parameter.unit}`;
    results.push({ name: prefix + setting.parameter, passed: error === null, detail: error ?? `${label} is within limits` });
  }
  return results;
}

/**
 * Check results for a procedure, named and worded like checks.py. With
 * `thorough` false only the citation, amount and setting checks are emitted
 * (the seeded WO-1 uses this); with true the full backend set is emitted
 * (text values, instrument listed, command), as the other orders do.
 */
export function procedureResults(
  steps: ProcedureStep[], documents: Document[], instruments: Instrument[], thorough: boolean,
): CheckResult[] {
  const results: CheckResult[] = [];
  steps.forEach((step, index) => {
    const prefix = `step ${index + 1}: `;
    const errors: string[] = [];
    for (const id of step.citations) {
      const count = documents.filter((d) => d.id === id).length;
      if (count === 0) errors.push(`unknown document ${id}`);
      else if (count > 1) errors.push(`ambiguous document ${id} in pinned context`);
    }
    if (step.citations.length === 0) errors.push("no citation");
    results.push({
      name: prefix + "citations",
      passed: errors.length === 0,
      detail: (errors.length ? errors : step.citations).join(", "),
    });
    if (thorough) {
      const matches = step.text.match(TEXT_VALUE) ?? [];
      results.push({
        name: prefix + "text values",
        passed: matches.length === 0,
        detail: matches.length
          ? `${matches.join(", ")}: put instrument values in the action and hand-measured values in amounts`
          : "no matching numeric unit expressions",
      });
    }
    for (const amount of step.amounts ?? []) {
      const known = KNOWN_AMOUNT_UNITS.includes(amount.unit);
      results.push({
        name: prefix + `amount ${amount.what}`,
        passed: known,
        detail: known ? `known unit ${amount.unit}` : `unknown unit ${amount.unit}`,
      });
    }
    if (step.action) {
      const action = step.action;
      if (thorough) {
        const listed = instruments.some((i) => i.id === action.instrument_id);
        results.push({
          name: prefix + "instrument listed",
          passed: listed,
          detail: listed ? `${action.instrument_id} is listed` : `unknown instrument ${action.instrument_id} in the pinned lab or experiment`,
        });
      }
      results.push(...commandResults(prefix, action.instrument_id, instruments, action.command, action.settings, thorough));
    }
  });
  return results;
}

/** Check results for a run plan, named like checks.py (`instrument listed`, `step N: command`, `step N: <parameter>`). */
export function runPlanResults(plan: RunPlan, instruments: Instrument[]): CheckResult[] {
  const listed = instruments.some((i) => i.id === plan.instrument_id);
  const results: CheckResult[] = [{
    name: "instrument listed",
    passed: listed,
    detail: listed ? `${plan.instrument_id} is listed` : `unknown instrument ${plan.instrument_id} in the pinned lab or experiment`,
  }];
  plan.steps.forEach((step, index) => {
    results.push(...commandResults(`step ${index + 1}: `, plan.instrument_id, instruments, step.command, step.settings, true));
  });
  return results;
}

function settingViews(instrumentId: string, settings: Setting[], instruments: Instrument[]): SettingView[] {
  const instrument = instruments.find((i) => i.id === instrumentId);
  return settings.map((setting) => {
    const parameter = instrument?.parameters.find((p) => p.name === setting.parameter);
    return {
      parameter: setting.parameter,
      display: `${setting.value} ${setting.unit}`,
      canonical: {
        value: setting.value,
        unit: parameter?.unit ?? setting.unit,
        minimum: parameter?.minimum ?? setting.value,
        maximum: parameter?.maximum ?? setting.value,
      },
    };
  });
}

function failuresFor(prefix: string, results: CheckResult[]): CheckResult[] {
  return results.filter((r) => !r.passed && r.name.startsWith(prefix)).map((r) => ({ ...r }));
}

/** Step views for a procedure. `documents` are the lab, project and experiment documents; unresolvable citations are left out of `sources`. */
export function procedureViews(
  steps: ProcedureStep[], results: CheckResult[], documents: Document[], instruments: Instrument[],
): StepView[] {
  return steps.map((step, index) => {
    const number = index + 1;
    const sources: { id: string; title: string }[] = [];
    for (const id of step.citations) {
      const doc = documents.find((d) => d.id === id);
      if (doc) sources.push({ id, title: doc.title });
    }
    return {
      number,
      text: step.text,
      sources,
      settings: step.action ? settingViews(step.action.instrument_id, step.action.settings, instruments) : [],
      unchecked: (step.amounts ?? []).map((a) => `${a.what} ${a.value} ${a.unit}`),
      failures: failuresFor(`step ${number}: `, results),
    };
  });
}

export function runPlanViews(plan: RunPlan, results: CheckResult[], instruments: Instrument[]): RunStepView[] {
  return plan.steps.map((step, index) => {
    const number = index + 1;
    return {
      number,
      instrument_id: plan.instrument_id,
      command: step.command,
      settings: settingViews(plan.instrument_id, step.settings, instruments),
      failures: failuresFor(`step ${number}: `, results),
    };
  });
}
