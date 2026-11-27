import { readFileSync } from "node:fs";
import { stripTypeScriptTypes } from "node:module";
import { join } from "node:path";
import { expect, test } from "playwright/test";
import { goto } from "./helpers.ts";
import type { Page } from "playwright/test";

const webDir = join(import.meta.dirname, "..");
const analysisCode = readFileSync(join(webDir, "python", "analysis.py"), "utf8");
const simulationCode = readFileSync(join(webDir, "python", "simulation.py"), "utf8");
// lib/runtime/runner.ts has no imports, so with its types stripped it runs as a page module.
const runnerModule = stripTypeScriptTypes(readFileSync(join(webDir, "lib", "runtime", "runner.ts"), "utf8"));

const LOAD_PREFIX = "The analysis runtime couldn't load: ";
const TIMEOUT_MESSAGE = "The analysis runtime didn't respond within 60 s. Reload the page and try again.";

// Opens the page with createPythonRunner on window, and counts the workers it starts.
async function openWithRunner(page: Page): Promise<void> {
  await goto(page, "/");
  await page.addScriptTag({
    type: "module",
    content: `${runnerModule}
const Base = window.Worker;
window.__workers = 0;
window.Worker = class extends Base { constructor(...args) { super(...args); window.__workers += 1; } };
window.__createPythonRunner = createPythonRunner;`,
  });
  await page.waitForFunction(() => "__createPythonRunner" in window);
}

// Mirrors syntheticReadings in lib/readings.ts, with the SAMPLE_READINGS parameters.
function mulberry32(seed: number): () => number {
  let a = seed;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function sampleReadings(): { time_s: number[]; absorbance: number[] } {
  const [k, a0, aEnd, noise] = [0.0085, 0.8, 0.05, 0.004];
  const rand = mulberry32(7);
  const time_s: number[] = [];
  const absorbance: number[] = [];
  for (let i = 0; i <= 60; i += 1) {
    const t = i * 10;
    time_s.push(t);
    absorbance.push(Math.round((aEnd + (a0 - aEnd) * Math.exp(-k * t) + noise * (2 * rand() - 1)) * 1e4) / 1e4);
  }
  return { time_s, absorbance };
}

test("the self-hosted worker runs the analysis on the sample readings", async ({ page }) => {
  await goto(page, "/");
  const reply = await page.evaluate(
    ({ code, readings }) =>
      new Promise<{ id: number; ok: boolean; value?: { decay: boolean; rate_constant_per_s: number }; error?: string }>(
        (resolve, reject) => {
          const worker = new Worker("/runtime/python-worker.mjs", { type: "module" });
          worker.addEventListener("message", (event) => resolve(event.data));
          worker.addEventListener("error", () => reject(new Error("The worker failed to start.")));
          worker.postMessage({ id: 1, code, entry: "analyze", args: { readings } });
        },
      ),
    { code: analysisCode, readings: sampleReadings() },
  );
  expect(reply.error).toBeUndefined();
  expect(reply.id).toBe(1);
  expect(reply.ok).toBe(true);
  expect(reply.value?.decay).toBe(true);
  expect(Math.abs((reply.value?.rate_constant_per_s ?? 0) / 0.0085 - 1)).toBeLessThan(0.03);
});

type RunnerWindow = Window & {
  __workers: number;
  __createPythonRunner: (options?: { workerUrl?: string; timeoutMs?: number }) => {
    run(code: string, entry: string, args: unknown): Promise<unknown>;
    dispose(): void;
  };
};

test("a worker URL that 404s gives the load error and the page stays usable", async ({ page }) => {
  await openWithRunner(page);
  const message = await page.evaluate(async () => {
    const runner = (window as unknown as RunnerWindow).__createPythonRunner({ workerUrl: "/runtime/missing-worker.mjs" });
    try {
      await runner.run("x = 1", "analyze", {});
      return "resolved";
    } catch (error) {
      return (error as Error).message;
    } finally {
      runner.dispose();
    }
  });
  expect(message.startsWith(LOAD_PREFIX)).toBe(true);
  expect(message.length).toBeGreaterThan(LOAD_PREFIX.length);
  await expect(page.getByRole("main")).toBeVisible();
});

test("a worker that never answers gives the timeout error, then the next run starts a fresh worker", async ({ page }) => {
  await openWithRunner(page);
  const outcome = await page.evaluate(async () => {
    const w = window as unknown as RunnerWindow;
    const stub = URL.createObjectURL(new Blob(["self.onmessage = () => {};"], { type: "text/javascript" }));
    const runner = w.__createPythonRunner({ workerUrl: stub, timeoutMs: 200 });
    const messages: string[] = [];
    for (let i = 0; i < 2; i += 1) {
      try {
        await runner.run("x = 1", "analyze", {});
        messages.push("resolved");
      } catch (error) {
        messages.push((error as Error).message);
      }
    }
    runner.dispose();
    return { messages, workers: w.__workers };
  });
  expect(outcome.messages).toEqual([TIMEOUT_MESSAGE, TIMEOUT_MESSAGE]);
  expect(outcome.workers).toBe(2);
  await expect(page.getByRole("main")).toBeVisible();
});

test("the runner surfaces Python errors verbatim and returns simulation results", async ({ page }) => {
  await openWithRunner(page);
  const outcome = await page.evaluate(
    async ({ analysis, simulation }) => {
      const runner = (window as unknown as RunnerWindow).__createPythonRunner();
      let error = "resolved";
      try {
        await runner.run(analysis, "analyze", { readings: { time_s: [0, 10, 20, 30], absorbance: [0.8, 0.7, 0.6, 0.5] } });
      } catch (e) {
        error = (e as Error).message;
      }
      const simulated = (await runner.run(simulation, "simulate", {})) as {
        series: { label: string; points: number[][] }[];
      };
      runner.dispose();
      return {
        error,
        labels: simulated.series.map((s) => s.label),
        lengths: simulated.series.map((s) => s.points.length),
        first: simulated.series[0].points[0],
      };
    },
    { analysis: analysisCode, simulation: simulationCode },
  );
  expect(outcome.error).toBe("The analysis needs at least 5 readings.");
  expect(outcome.labels).toEqual(["0.5 mM", "1.0 mM", "2.0 mM"]);
  expect(outcome.lengths).toEqual([61, 61, 61]);
  expect(outcome.first[0]).toBe(0);
  expect(outcome.first[1]).toBeCloseTo(0.8, 9);
});

// Analysis code runs on readings that must stay in the browser: the worker takes network access away
// from it once Pyodide has loaded, and no request it attempts reaches the server.
test("analysis code can't send readings out of the browser, and later runs still work", async ({ page }) => {
  await openWithRunner(page);
  const leaked: string[] = [];
  page.on("request", (request) => { if (request.url().includes("leak")) leaked.push(request.url()); });
  const outcome = await page.evaluate(
    async ({ analysis, simulation, readings }) => {
      const runner = (window as unknown as RunnerWindow).__createPythonRunner();
      const attempt = async (code: string) => {
        try {
          return `resolved: ${JSON.stringify(await runner.run(code, "attempt", {}))}`;
        } catch (e) {
          return (e as Error).message;
        }
      };
      const messages = [
        await attempt("import js\ndef attempt():\n    js.fetch('/leak?fetch=1')\n    return 'sent'"),
        await attempt("import js\ndef attempt():\n    r = js.XMLHttpRequest.new()\n    r.open('GET', '/leak?xhr=1')\n    r.send()\n    return 'sent'"),
        await attempt("import js\ndef attempt():\n    js.WebSocket.new('ws://127.0.0.1:1/leak')\n    return 'sent'"),
        await attempt("import js\ndef attempt():\n    js.EventSource.new('/leak?sse=1')\n    return 'sent'"),
        await attempt("import js\ndef attempt():\n    js.importScripts('/leak?import=1')\n    return 'sent'"),
        await attempt("import js\ndef attempt():\n    js.Object.getPrototypeOf(js).fetch('/leak?proto=1')\n    return 'sent'"),
        await attempt("import js\ndef attempt():\n    js.Worker.new('/leak?worker=1')\n    return 'sent'"),
        // Fonts fetch their url() sources, so a FontFace load and the font set are both refused.
        await attempt("import js\ndef attempt():\n    js.FontFace.new('x', \"url('/leak?font=1')\").load()\n    return 'sent'"),
        await attempt("import js\ndef attempt():\n    js.self.fonts.add(js.self.fonts)\n    return 'sent'"),
        // Code built from a string could reach dynamic import(), which requests a module from any URL.
        await attempt("import js\ndef attempt():\n    js.eval(\"import('/leak?eval=1')\")\n    return 'sent'"),
        await attempt("import js\ndef attempt():\n    js.Function.new(\"return import('/leak?function=1')\")()\n    return 'sent'"),
        await attempt("import js\ndef attempt():\n    js.setTimeout(\"import('/leak?timer=1')\", 0)\n    return 'sent'"),
      ];
      const analyzed = (await runner.run(analysis, "analyze", { readings })) as { decay: boolean };
      const simulated = (await runner.run(simulation, "simulate", {})) as { series: unknown[] };
      const again = (await runner.run(analysis, "analyze", { readings })) as { decay: boolean };
      runner.dispose();
      return { messages, decay: analyzed.decay, series: simulated.series.length, again: again.decay };
    },
    { analysis: analysisCode, simulation: simulationCode, readings: sampleReadings() },
  );
  for (const message of outcome.messages) expect(message).toContain("Network access is not available to analysis code.");
  expect(outcome.decay).toBe(true);
  expect(outcome.series).toBe(3);
  expect(outcome.again).toBe(true);
  // Give any request that slipped out a moment to show up: wait for a round trip of our own.
  await page.evaluate(() => fetch("/").then((r) => r.text()));
  expect(leaked).toEqual([]);
});
