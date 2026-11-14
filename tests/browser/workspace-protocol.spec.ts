import { test, expect } from "playwright/test";
import { createFixtureClient } from "../../app/workspace/fixture";

test("fixture rejects forged protocol fields at save, approval and submission", async () => {
  const store = new Map<string, string>();
  const original = Object.getOwnPropertyDescriptor(globalThis, "sessionStorage");
  Object.defineProperty(globalThis, "sessionStorage", {configurable: true, value: {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => store.set(key, value),
  }});
  try {
    const api = createFixtureClient();
    const id = "visible-assay";
    const spec = (await api.read(id)).specifications[0];
    for (const override of [{outputs:["invented_output"]}, {validation_criteria:["No numerical checks required"]}, {units:{...spec.units, concentration:"mol/L"}}]) {
      await expect(api.saveSpecification(id, {...spec, ...override}, spec.revision)).rejects.toMatchObject({status:422});
    }
    expect((await api.read(id)).specifications).toHaveLength(2);
    // Simulate a record persisted by the previous fixture implementation.
    const [key, raw] = Array.from(store.entries())[0];
    const saved = JSON.parse(raw);
    saved.snapshot.specifications[0].outputs = ["invented_output"];
    store.set(key, JSON.stringify(saved));
    await expect(api.submit(id, spec, "retry")).rejects.toMatchObject({status:422});
    saved.snapshot.specifications[0].approval = null;
    saved.snapshot.specifications[0].status = "draft";
    store.set(key, JSON.stringify(saved));
    await expect(api.approve(id, spec, spec.approval!.confirmed_fields)).rejects.toMatchObject({status:422});
  } finally {
    if (original) Object.defineProperty(globalThis, "sessionStorage", original);
    else Reflect.deleteProperty(globalThis, "sessionStorage");
  }
});
