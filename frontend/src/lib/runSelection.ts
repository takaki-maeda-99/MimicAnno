import type { IndexEntry } from "./manifest";

export type RunSelection =
  | { kind: "none"; episodeId: string; runHashShort: string | undefined }
  | { kind: "single"; entry: IndexEntry }
  | { kind: "multiple"; chosen: IndexEntry; alternatives: IndexEntry[] };

export function selectRun(
  entries: IndexEntry[],
  episodeId: string,
  runHashShort: string | undefined,
): RunSelection {
  let pool = entries.filter((e) => e.episode_id === episodeId);
  if (runHashShort !== undefined) {
    pool = pool.filter((e) => e.run_hash_short === runHashShort);
  }
  if (pool.length === 0) {
    return { kind: "none", episodeId, runHashShort };
  }
  if (pool.length === 1) {
    return { kind: "single", entry: pool[0] };
  }
  // Newest by generated_at desc; ties broken by run_hash lex desc (deterministic).
  const sorted = [...pool].sort((a, b) => {
    if (a.generated_at !== b.generated_at) {
      return a.generated_at < b.generated_at ? 1 : -1;
    }
    return a.run_hash < b.run_hash ? 1 : -1;
  });
  const [chosen, ...alternatives] = sorted;
  return { kind: "multiple", chosen, alternatives };
}
