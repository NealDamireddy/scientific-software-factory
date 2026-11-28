export type LibraryEntry = {
  id: number; source_id: string; scope: string; revision: number; kind: string; title: string;
  origin: string; digest: string; bytes: number; contributed_by: string; created_at: string; document_id: string;
};

export const scopeLabel = (scope: string) => scope === "shared" ? "Shared with all labs" : "This lab only";

export const shareable = (entry: LibraryEntry, entries: LibraryEntry[]) =>
  entry.scope !== "shared" && !entries.some(e => e.scope === "shared" && e.source_id === entry.source_id && e.digest === entry.digest);

export function formatBytes(bytes: number) {
  if (bytes < 1024) return bytes + " B";
  const kb = bytes / 1024;
  return (kb < 10 ? kb.toFixed(1) : String(Math.round(kb))) + " KB";
}
