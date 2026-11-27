import test from "node:test";
import assert from "node:assert/strict";
import { POST } from "./api/experiment-review/route.ts";

const localHeaders = { origin: "http://localhost:3100", host: "localhost:3100", "content-type": "application/json" };

function send(headers, body = "{}") {
  return POST(new Request("http://localhost:3100/api/experiment-review", { method: "POST", headers, body }));
}

test("local delivery rejects hosted, cross-origin, proxied, and oversized requests before dispatch", async () => {
  const original = process.env.LAB_LOCAL_EXPERIMENT_WORKER;
  try {
    delete process.env.LAB_LOCAL_EXPERIMENT_WORKER;
    assert.equal((await send(localHeaders)).status, 403);
    process.env.LAB_LOCAL_EXPERIMENT_WORKER = "1";
    assert.equal((await send({ ...localHeaders, origin: "http://outside.invalid" })).status, 403);
    assert.equal((await send({ ...localHeaders, "x-forwarded-for": "192.0.2.1" })).status, 403);
    assert.equal((await send({ ...localHeaders, "x-forwarded-host": "outside.invalid" })).status, 403);
    assert.equal((await send({ ...localHeaders, "content-type": "text/plain" })).status, 415);
    assert.equal((await send(localHeaders, "x".repeat(160 * 1024 + 1))).status, 413);
  } finally {
    if (original === undefined) delete process.env.LAB_LOCAL_EXPERIMENT_WORKER;
    else process.env.LAB_LOCAL_EXPERIMENT_WORKER = original;
  }
});
