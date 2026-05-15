/** S-RS: run-set listing client (api mode only). */

export type RunSetEntry = { name: string; label: string };

/** Fetch available run-sets from the server. Only valid in api mode.
 *  Returns [] on any error so callers can treat it as "no switcher needed".
 */
export async function fetchRunSets(): Promise<RunSetEntry[]> {
  try {
    const r = await fetch("/api/run-sets");
    if (!r.ok) return [];
    return (await r.json()) as RunSetEntry[];
  } catch {
    return [];
  }
}
