import assert from "node:assert/strict";
import { test } from "node:test";

import { parseRoute, routeHref } from "./route.ts";
import type { Route } from "./route.ts";

const forms: [string, Route][] = [
  ["#/projects/p/experiments/e?order=run%20%231",
    { view: "experiment", projectId: "p", experimentId: "e", orderId: "run #1" }],
  ["#/", { view: "home" }],
  ["#/lab", { view: "lab" }],
  ["#/settings", { view: "settings" }],
  ["#/skills", { view: "skills" }],
  ["#/skills?skill=plot-style", { view: "skills", skill: "plot-style" }],
  ["#/skills?skill=new", { view: "skills", skill: "new" }],
  ["#/connectors", { view: "connectors" }],
  ["#/agents", { view: "agents" }],
  ["#/projects/coomassie-reduction", { view: "project", projectId: "coomassie-reduction" }],
  ["#/projects/coomassie-reduction/experiments/coomassie-run-1",
    { view: "experiment", projectId: "coomassie-reduction", experimentId: "coomassie-run-1" }],
];

for (const [hash, route] of forms) {
  test(`${hash} parses and round-trips`, () => {
    assert.deepEqual(parseRoute(hash), route);
    assert.equal(routeHref(route), hash);
    assert.deepEqual(parseRoute(routeHref(route)), route);
  });

  test(`${hash} with ?doc= round-trips`, () => {
    const withDoc = { ...route, doc: "sop-cuvette" } as Route;
    const href = routeHref(withDoc);
    assert.equal(href, hash + (hash.includes("?") ? "&" : "?") + "doc=sop-cuvette");
    assert.deepEqual(parseRoute(href), withDoc);
  });
}

test("the empty hash and a bare # are home", () => {
  assert.deepEqual(parseRoute(""), { view: "home" });
  assert.deepEqual(parseRoute("#"), { view: "home" });
});

test("unrecognized routes go home", () => {
  assert.deepEqual(parseRoute("#/nonsense"), { view: "home" });
  assert.deepEqual(parseRoute("#/projects"), { view: "home" });
  assert.deepEqual(parseRoute("#/projects/a/experiments"), { view: "home" });
  assert.deepEqual(parseRoute("#/projects/a/b/c"), { view: "home" });
  assert.deepEqual(parseRoute("#/lab/extra"), { view: "home" });
});

test("ids are URI-decoded and re-encoded", () => {
  assert.deepEqual(parseRoute("#/projects/my%20project/experiments/run%201"),
    { view: "experiment", projectId: "my project", experimentId: "run 1" });
  assert.deepEqual(parseRoute("#/lab?doc=a%20doc"), { view: "lab", doc: "a doc" });
  assert.equal(routeHref({ view: "project", projectId: "my project" }), "#/projects/my%20project");
  assert.equal(routeHref({ view: "lab", doc: "a doc" }), "#/lab?doc=a%20doc");
});

test("a malformed escape does not throw", () => {
  assert.deepEqual(parseRoute("#/projects/%E0%A4%A"), { view: "project", projectId: "%E0%A4%A" });
});

test("a skill parameter outside the skills view is ignored", () => {
  assert.deepEqual(parseRoute("#/lab?skill=x"), { view: "lab" });
});

test("a trailing slash is tolerated", () => {
  assert.deepEqual(parseRoute("#/settings/"), { view: "settings" });
});
