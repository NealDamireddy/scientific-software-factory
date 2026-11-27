import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

import { RUNTIME_TIMEOUT_MESSAGE, createPythonRunner, runtimeLoadMessage } from "./runner.ts";

type Listener = (event: unknown) => void;
type Reply = (worker: FakeWorker, message: { id: number; code: string; entry: string; args: unknown }) => void;

class FakeWorker {
  static instances: FakeWorker[] = [];
  static reply: Reply = () => {};

  url: string;
  options: unknown;
  posted: unknown[] = [];
  terminated = false;
  listeners = new Map<string, Listener[]>();

  constructor(url: string, options: unknown) {
    this.url = url;
    this.options = options;
    FakeWorker.instances.push(this);
  }

  addEventListener(type: string, listener: Listener): void {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }

  removeEventListener(type: string, listener: Listener): void {
    this.listeners.set(type, (this.listeners.get(type) ?? []).filter((l) => l !== listener));
  }

  postMessage(message: { id: number; code: string; entry: string; args: unknown }): void {
    this.posted.push(message);
    queueMicrotask(() => FakeWorker.reply(this, message));
  }

  terminate(): void {
    this.terminated = true;
  }

  emit(type: string, event: unknown): void {
    if (this.terminated) return;
    for (const listener of this.listeners.get(type) ?? []) listener(event);
  }
}

const original = (globalThis as { Worker?: unknown }).Worker;

beforeEach(() => {
  FakeWorker.instances = [];
  FakeWorker.reply = () => {};
  (globalThis as { Worker?: unknown }).Worker = FakeWorker;
});

afterEach(() => {
  (globalThis as { Worker?: unknown }).Worker = original;
});

test("the runtime messages are the exact copy", () => {
  assert.equal(RUNTIME_TIMEOUT_MESSAGE, "The analysis runtime didn't respond within 60 s. Reload the page and try again.");
  assert.equal(runtimeLoadMessage("network down"), "The analysis runtime couldn't load: network down");
});

test("creating a runner starts no worker until the first run", () => {
  const runner = createPythonRunner();
  assert.equal(FakeWorker.instances.length, 0);
  runner.dispose();
});

test("a run posts the code to one module worker and resolves with its value", async () => {
  FakeWorker.reply = (worker, message) =>
    worker.emit("message", { data: { id: message.id, ok: true, value: { entry: message.entry, args: message.args } } });
  const runner = createPythonRunner();
  assert.deepEqual(await runner.run("code", "analyze", { readings: { time_s: [0] } }), {
    entry: "analyze",
    args: { readings: { time_s: [0] } },
  });
  assert.deepEqual(await runner.run("code", "simulate", {}), { entry: "simulate", args: {} });
  assert.equal(FakeWorker.instances.length, 1);
  assert.equal(FakeWorker.instances[0].url, "/runtime/python-worker.mjs");
  assert.deepEqual(FakeWorker.instances[0].options, { type: "module" });
  runner.dispose();
});

test("a Python error rejects with the Python message verbatim", async () => {
  FakeWorker.reply = (worker, message) =>
    worker.emit("message", { data: { id: message.id, ok: false, error: "The analysis needs at least 5 readings." } });
  const runner = createPythonRunner();
  await assert.rejects(runner.run("code", "analyze", {}), {
    message: "The analysis needs at least 5 readings.",
  });
  assert.equal(FakeWorker.instances[0].terminated, false);
  runner.dispose();
});

test("a worker that never replies rejects with the timeout copy and the next run uses a fresh worker", async () => {
  const runner = createPythonRunner({ timeoutMs: 50 });
  await assert.rejects(runner.run("code", "analyze", {}), { message: RUNTIME_TIMEOUT_MESSAGE });
  assert.equal(FakeWorker.instances.length, 1);
  assert.equal(FakeWorker.instances[0].terminated, true);

  FakeWorker.reply = (worker, message) => worker.emit("message", { data: { id: message.id, ok: true, value: 42 } });
  assert.equal(await runner.run("code", "analyze", {}), 42);
  assert.equal(FakeWorker.instances.length, 2);
  runner.dispose();
});

test("a worker error event rejects with the load copy and the next run uses a fresh worker", async () => {
  FakeWorker.reply = (worker) => worker.emit("error", { message: "Failed to fetch /runtime/pyodide.mjs" });
  const runner = createPythonRunner({ workerUrl: "/missing.mjs", timeoutMs: 1000 });
  await assert.rejects(runner.run("code", "analyze", {}), {
    message: "The analysis runtime couldn't load: Failed to fetch /runtime/pyodide.mjs",
  });
  assert.equal(FakeWorker.instances[0].url, "/missing.mjs");
  assert.equal(FakeWorker.instances[0].terminated, true);

  FakeWorker.reply = (worker) => worker.emit("error", {});
  await assert.rejects(runner.run("code", "analyze", {}), (error: unknown) => {
    assert.ok(error instanceof Error);
    assert.match(error.message, /^The analysis runtime couldn't load: \S/);
    return true;
  });
  assert.equal(FakeWorker.instances.length, 2);
  runner.dispose();
});

test("a load failure reported by the worker rejects with the load copy", async () => {
  FakeWorker.reply = (worker, message) =>
    worker.emit("message", { data: { id: message.id, ok: false, load_error: "pyodide.asm.wasm is missing" } });
  const runner = createPythonRunner();
  await assert.rejects(runner.run("code", "analyze", {}), {
    message: "The analysis runtime couldn't load: pyodide.asm.wasm is missing",
  });
  assert.equal(FakeWorker.instances[0].terminated, true);
  runner.dispose();
});

test("dispose terminates the worker and rejects pending runs", async () => {
  const runner = createPythonRunner({ timeoutMs: 10_000 });
  const pending = runner.run("code", "analyze", {});
  runner.dispose();
  await assert.rejects(pending);
  assert.equal(FakeWorker.instances[0].terminated, true);
});
