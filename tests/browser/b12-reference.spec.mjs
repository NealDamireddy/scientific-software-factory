import { expect, test } from "playwright/test";
import { checkedReport, disagreement } from "../../app/b12/demo/reference.mjs";

const reference = { sample_id: "vial-A", calibration_id: "c1", status: "ok", concentration_mg_l: 11.9985 };

test("hosted B12 result is shown only when it matches the instrument's calculation", () => {
  const analysis = { output: { ...reference, concentration_mg_l: 11.9985 + 1e-9 } };
  expect(checkedReport(analysis, reference)).toBe(analysis);
  for (const output of [
    { ...reference, concentration_mg_l: -12.1 },
    { ...reference, concentration_mg_l: null },
    { ...reference, status: "review" },
    { ...reference, sample_id: "vial-B" },
    undefined,
  ]) {
    expect(disagreement(output, reference)).not.toBeNull();
    expect(() => checkedReport({ output }, reference)).toThrow(/not shown/);
  }
  expect(() => checkedReport({ output: reference }, undefined)).toThrow(/reference/);
  const withheld = { ...reference, status: "review", concentration_mg_l: null };
  expect(disagreement(withheld, withheld)).toBeNull();
});
