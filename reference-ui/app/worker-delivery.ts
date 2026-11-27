import type { Experiment, Run, RunContext } from "./simulation";

type Skill = RunContext["skills"][number];
type ReceivedSkill = { id: string; name: string; version: string };
export type WorkerDelivery =
  | { id: string; status: "pending" }
  | { id: string; status: "failed"; error: string }
  | {
      id: string;
      status: "received";
      receivedAt: string;
      skills: ReceivedSkill[];
      review: string;
    };

export function localWorkerHost(host: string) {
  return ["localhost", "127.0.0.1", "[::1]"].includes(host);
}

export async function skillVersion(skill: Skill) {
  const canonical = JSON.stringify([
    skill.id, skill.name, skill.whenToUse, skill.instructions, skill.stage ?? null,
  ]);
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(canonical));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export async function deliverReview(
  id: string, context: RunContext, hostname: string, send: typeof fetch = fetch,
): Promise<WorkerDelivery> {
  try {
    if (!localWorkerHost(hostname))
      throw new Error("Open this workspace on localhost to use the coding worker.");
    const skills = context.skills.map(({ id, name, whenToUse, instructions, stage }) => ({
      id, name, whenToUse, instructions, ...(stage ? { stage } : {}),
    }));
    const response = await send("/api/experiment-review", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ deliveryId: id, briefing: context.briefing, skills }),
    });
    const data = await response.json().catch(() => null);
    if (!response.ok) throw new Error(typeof data?.error === "string" ? data.error :
      `The coding worker returned HTTP ${response.status}.`);
    const versions = await Promise.all(skills.map(skillVersion));
    if (data?.deliveryId !== id || !Array.isArray(data.skills) ||
        data.skills.length !== skills.length ||
        !skills.every((skill, index) => data.skills.some((item: ReceivedSkill | null) =>
          item?.id === skill.id && item.name === skill.name && item.version === versions[index])) ||
        typeof data.receivedAt !== "string" || !Number.isFinite(Date.parse(data.receivedAt)) ||
        typeof data.review !== "string" || !data.review.trim()) {
      throw new Error("The worker receipt could not be verified against this run’s skills.");
    }
    return {
      id, status: "received", receivedAt: data.receivedAt,
      skills: skills.map(({ id, name }, index) => ({ id, name, version: versions[index] })),
      review: data.review,
    };
  } catch (error) {
    return { id, status: "failed", error: error instanceof Error ? error.message : "Could not reach the coding worker." };
  }
}

// A response can arrive after a repeat, simulation step, or workspace reset.
export function recordDelivery(experiments: Experiment[], result: WorkerDelivery): Experiment[] {
  return experiments.map((experiment) => {
    const index = experiment.runs.findIndex((run) =>
      run.workerDelivery?.id === result.id && run.workerDelivery.status === "pending");
    if (index < 0) return experiment;
    const runs = [...experiment.runs];
    runs[index] = { ...runs[index], workerDelivery: result };
    return { ...experiment, runs };
  });
}

export function deliveryLabel(run: Run) {
  switch (run.workerDelivery?.status) {
    case "received": return "Worker receipt verified";
    case "failed": return "Worker receipt unavailable";
    case "pending": return "Waiting for worker receipt";
    default: return "No worker receipt recorded";
  }
}
