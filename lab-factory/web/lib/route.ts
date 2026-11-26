// Hash routes for the one-page app. Pure: no DOM access, so it runs under node --test.

type Doc = { doc?: string };

export type Route = Doc & (
  | { view: "home" }
  | { view: "lab" }
  | { view: "settings" }
  | { view: "skills"; skill?: string }
  | { view: "connectors" }
  | { view: "agents" }
  | { view: "project"; projectId: string }
  | { view: "experiment"; projectId: string; experimentId: string; orderId?: string }
);

const SIMPLE = ["lab", "settings", "skills", "connectors", "agents"] as const;

function decode(part: string): string {
  try {
    return decodeURIComponent(part);
  } catch {
    return part;
  }
}

function readQuery(query: string): Map<string, string> {
  const params = new Map<string, string>();
  for (const pair of query.split("&")) {
    if (pair === "") continue;
    const eq = pair.indexOf("=");
    const key = decode(eq === -1 ? pair : pair.slice(0, eq));
    const value = decode(eq === -1 ? "" : pair.slice(eq + 1));
    if (!params.has(key)) params.set(key, value);
  }
  return params;
}

function pathRoute(segments: string[]): Route {
  if (segments.length === 0) return { view: "home" };
  const [first, ...rest] = segments;
  if (rest.length === 0) {
    const simple = SIMPLE.find((v) => v === first);
    if (simple) return { view: simple };
  }
  if (first === "projects" && rest.length === 1) return { view: "project", projectId: decode(rest[0]) };
  if (first === "projects" && rest.length === 3 && rest[1] === "experiments") {
    return { view: "experiment", projectId: decode(rest[0]), experimentId: decode(rest[2]) };
  }
  return { view: "home" };
}

export function parseRoute(hash: string): Route {
  let text = hash.startsWith("#") ? hash.slice(1) : hash;
  const q = text.indexOf("?");
  const query = q === -1 ? "" : text.slice(q + 1);
  text = q === -1 ? text : text.slice(0, q);
  const segments = text.split("/").filter((s) => s !== "");
  const route = pathRoute(segments);
  const params = readQuery(query);
  const skill = params.get("skill");
  if (route.view === "skills" && skill) route.skill = skill;
  const orderId = params.get("order");
  if (route.view === "experiment" && orderId) route.orderId = orderId;
  const doc = params.get("doc");
  if (doc) route.doc = doc;
  return route;
}

export function routeHref(route: Route): string {
  const enc = encodeURIComponent;
  let path: string;
  switch (route.view) {
    case "home": path = "/"; break;
    case "project": path = `/projects/${enc(route.projectId)}`; break;
    case "experiment": path = `/projects/${enc(route.projectId)}/experiments/${enc(route.experimentId)}`; break;
    default: path = `/${route.view}`;
  }
  const query: string[] = [];
  if (route.view === "skills" && route.skill) query.push(`skill=${enc(route.skill)}`);
  if (route.view === "experiment" && route.orderId) query.push(`order=${enc(route.orderId)}`);
  if (route.doc) query.push(`doc=${enc(route.doc)}`);
  return "#" + path + (query.length > 0 ? "?" + query.join("&") : "");
}
