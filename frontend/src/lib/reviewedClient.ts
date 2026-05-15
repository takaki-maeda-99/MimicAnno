/**
 * Phase 5 B r3 — reviewed-toggle HTTP client (spec §5.1).
 *
 * Tagged-union result mirrors boundaryClient / editClient patterns.
 */
import type { Manifest } from "./manifest";

export type ReviewedPatchResult =
  | { kind: "ok"; runHash: string; manifest: Manifest }
  | { kind: "conflict"; errorCode: string; serverMessage: string }
  | { kind: "no_change"; serverMessage: string }
  | { kind: "invalid"; errorCode: string; serverMessage: string }
  | { kind: "error"; httpStatus: number; errorCode: string | null; message: string };

export async function patchReviewed(args: {
  apiBase: string;
  runName: string;
  segmentId: string;
  reviewed: boolean;
  ifMatchRunHash: string;
  signal?: AbortSignal;
  timeoutMs?: number;
}): Promise<ReviewedPatchResult> {
  const { apiBase, runName, segmentId, reviewed, ifMatchRunHash, signal, timeoutMs = 10_000 } = args;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const combinedSignal = signal
    ? (AbortSignal as { any?: (s: AbortSignal[]) => AbortSignal }).any?.([signal, controller.signal]) ?? controller.signal
    : controller.signal;

  const url = `${apiBase}/api/runs/${encodeURIComponent(runName)}/segments/${encodeURIComponent(segmentId)}/reviewed`;

  try {
    const resp = await fetch(url, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        "If-Match": `"${ifMatchRunHash}"`,
      },
      body: JSON.stringify({ reviewed }),
      signal: combinedSignal,
    });

    clearTimeout(timer);

    let json: Record<string, unknown> | null = null;
    try {
      json = await resp.json();
    } catch {
      // non-JSON body
    }

    const errorCode = (json?.error as string) ?? null;
    const serverMessage = (json?.message as string) ?? resp.statusText;

    if (resp.ok) {
      const manifest = json as unknown as Manifest;
      const runHash = (json?.run_hash as string) ?? "";
      return { kind: "ok", runHash, manifest };
    }
    if (resp.status === 412) {
      return { kind: "conflict", errorCode: errorCode ?? "etag_mismatch", serverMessage };
    }
    if (resp.status === 400 && errorCode === "no_change") {
      return { kind: "no_change", serverMessage };
    }
    if (resp.status === 400) {
      return { kind: "invalid", errorCode: errorCode ?? "invalid_body", serverMessage };
    }
    return { kind: "error", httpStatus: resp.status, errorCode, message: serverMessage };
  } catch (err) {
    clearTimeout(timer);
    const message = err instanceof Error ? err.message : String(err);
    return { kind: "error", httpStatus: 0, errorCode: null, message };
  }
}
