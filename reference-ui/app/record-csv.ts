export type Observation = {
  row: number;
  sample: string;
  measurement: string;
  value: number | null;
  unit: string;
};

export const maxFileBytes = 1024 * 1024;
export const maxObservations = 1000;
const columns = ["sample", "measurement", "value", "unit"] as const;
const decimal = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i;

export function finiteDecimal(raw: string): number | null {
  const value = raw.trim();
  const numeric = Number(value);
  return decimal.test(value) && Number.isFinite(numeric) ? numeric : null;
}

/** Physical source line numbers are retained even for quoted multiline fields. */
export function parseRecordCsv(content: string): Observation[] {
  if (content.length > maxFileBytes)
    throw new Error("Choose a CSV file of 1 MB or less.");
  const text = content.replace(/^\uFEFF/, "").replace(/\r\n?/g, "\n");
  const observations: Observation[] = [];
  let headers: string[] | undefined;
  let fields: string[] = [],
    field = "";
  let line = 1,
    start = 1,
    quoted = false,
    closed = false;
  function endRow() {
    fields.push(field.trim());
    // Only physically blank lines are separators. An empty record still carries evidence.
    if (fields.length > 1 || fields[0] || closed) {
      if (!headers) {
        headers = fields;
        if (
          headers.length !== columns.length ||
          columns.some((col) => !headers!.includes(col))
        ) {
          throw new Error(
            "Use exactly these four column names: sample, measurement, value, unit.",
          );
        }
      } else {
        if (fields.length !== columns.length)
          throw new Error("Row " + start + " must contain four columns.");
        if (observations.length >= maxObservations)
          throw new Error("Choose a file with 1,000 data rows or fewer.");
        const get = (key: (typeof columns)[number]) =>
          fields[headers!.indexOf(key)];
        const raw = get("value");
        const value = finiteDecimal(raw);
        if (raw && value === null)
          throw new Error(
            "Row " +
              start +
              " has an invalid value. Enter a finite number or leave the cell empty.",
          );
        observations.push({
          row: start,
          sample: get("sample"),
          measurement: get("measurement"),
          value,
          unit: get("unit"),
        });
      }
    }
    fields = [];
    field = "";
    closed = false;
  }
  for (let index = 0; index < text.length; index++) {
    const ch = text[index];
    if (quoted) {
      if (ch === '"') {
        if (text[index + 1] === '"') {
          field += '"';
          index++;
        } else {
          quoted = false;
          closed = true;
        }
      } else {
        field += ch;
        if (ch === "\n") line++;
      }
      continue;
    }
    if (ch === "\n") {
      endRow();
      start = ++line;
      continue;
    }
    if (ch === ",") {
      if (fields.length >= columns.length - 1)
        throw new Error("Row " + start + " has extra columns.");
      fields.push(field.trim());
      field = "";
      closed = false;
      continue;
    }
    if (closed) {
      if (!/[ \t]/.test(ch))
        throw new Error(
          "Unexpected text after a closing quote on row " + start + ".",
        );
      continue;
    }
    if (ch === '"') {
      if (field.length)
        throw new Error("Unexpected quotation mark on row " + start + ".");
      quoted = true;
      continue;
    }
    field += ch;
  }
  if (quoted)
    throw new Error(
      "A quoted field starting on row " + start + " is incomplete.",
    );
  endRow();
  if (!observations.length)
    throw new Error("Include a header and at least one data row.");
  return observations;
}
