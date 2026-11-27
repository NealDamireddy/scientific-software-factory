import { execFile } from "node:child_process";
import path from "node:path";

export const runtime = "nodejs";

const MAX_BYTES = 160 * 1024;
const loopback = new Set(["127.0.0.1", "localhost", "::1", "[::1]", "::ffff:127.0.0.1"]);
const error = (message: string, status: number) => Response.json({ error: message }, { status });

function isLocalRequest(request: Request) {
  if (process.env.LAB_LOCAL_EXPERIMENT_WORKER !== "1" || process.env.VERCEL) return false;
  const origin = request.headers.get("origin");
  if (!origin) return false;
  try {
    const parsed = new URL(origin);
    const forwardedHost = request.headers.get("x-forwarded-host");
    const forwardedFor = request.headers.get("x-forwarded-for");
    return ["http:", "https:"].includes(parsed.protocol) && loopback.has(parsed.hostname)
      && parsed.origin === origin && parsed.host === request.headers.get("host")
      && (!forwardedHost || forwardedHost === parsed.host)
      && (!forwardedFor || forwardedFor.split(",").every(ip => loopback.has(ip.trim())));
  } catch {
    return false;
  }
}

async function readBriefing(request: Request) {
  if (Number(request.headers.get("content-length")) > MAX_BYTES || !request.body) return null;
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let bytes = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) return Buffer.concat(chunks, bytes);
      bytes += value.length;
      if (bytes > MAX_BYTES) {
        await reader.cancel();
        return null;
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
}

function deliver(briefing: Buffer): Promise<Response> {
  return new Promise(resolve => {
    const child = execFile("python3", ["-m", "lab_codex_worker.experiment_review"], {
      cwd: path.resolve(process.cwd(), "../lab-factory/src"),
      timeout: 190_000,
      maxBuffer: 256 * 1024,
    }, (failure, output) => {
      if (!failure) {
        try {
          const result = JSON.parse(output);
          if ([200, 400, 409, 503].includes(result.status) && result.body) {
            resolve(Response.json(result.body, { status: result.status, headers: { "Cache-Control": "no-store" } }));
            return;
          }
        } catch {
          // Treat an unreadable worker response as a failed delivery.
        }
      }
      resolve(error("Could not reach the local coding worker. Check Python and Codex CLI sign-in, then retry.", 503));
    });
    child.stdin?.on("error", () => { /* execFile reports failed launches in its callback. */ });
    child.stdin?.end(briefing);
  });
}

export async function POST(request: Request) {
  if (!isLocalRequest(request)) {
    return error("Coding-agent delivery requires the workspace running on localhost.", 403);
  }
  if (request.headers.get("content-type")?.split(";")[0].trim() !== "application/json") {
    return error("Send the experiment briefing as JSON.", 415);
  }
  const briefing = await readBriefing(request);
  if (!briefing) return error("The experiment briefing is missing or exceeds 160 KiB.", 413);
  return deliver(briefing);
}
