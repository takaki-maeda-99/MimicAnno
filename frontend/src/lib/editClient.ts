/**
 * Phase 5 B r1 T13 — PATCH client for /api/runs/{name}/segments/{segment_id}.
 *
 * Returns a tagged union — no thrown exceptions on HTTP failure (network /
 * JSON-parse failures still throw and are caught by RunViewer's error path).
 *
 * Optimistic-locking contract (server-side):
 *   - Request: `If-Match: "<run_hash>"` (RFC 7232 quoted)
 *   - 200: response body is the new full Manifest; `ETag: "<new_run_hash>"`
 *   - 412: `{error:"etag_mismatch", message:…}` — client should refetch
 *   - 400 sub-codes: `invalid_label` / `invalid_segment` / `invalid_body`
 *   - 404: `run_not_found`
 *
 * The 10-second default timeout (review NEW CONCERN #1) keeps the
 * single-in-flight UI lock from wedging if the server hangs.
 */
import type { Manifest } from "./manifest";

export type PatchResult =
  | { kind: "ok"; runHash: string; manifest: Manifest }
  | { kind: "conflict"; errorCode: string; serverMessage: string }
  | { kind: "invalid"; errorCode: string; serverMessage: string }
  | { kind: "not_found"; errorCode: string; serverMessage: string }
  | {
      kind: "error";
      httpStatus: number;
      errorCode: string | null;
      message: string;
    };

const DEFAULT_TIMEOUT_MS = 10_000;

async function readErrorEnvelope(
  resp: Response,
): Promise<{ error: string | null; message: string }> {
  try {
    const body = (await resp.json()) as unknown;
    if (
      body !== null &&
      typeof body === "object" &&
      "error" in body &&
      "message" in body
    ) {
      const b = body as { error: unknown; message: unknown };
      return {
        error: typeof b.error === "string" ? b.error : null,
        message: typeof b.message === "string" ? b.message : "",
      };
    }
    return { error: null, message: JSON.stringify(body) };
  } catch {
    return { error: null, message: resp.statusText || `HTTP ${resp.status}` };
  }
}

function stripETag(raw: string | null): string | null {
  if (raw === null) return null;
  // Tolerate weak ETags defensively (W/"…"). Server never emits them today.
  const m = raw.match(/^W?\/?"(.+)"$/);
  return m ? m[1] : null;
}

export async function patchSegmentPhase(args: {
  apiBase: string;
  runName: string;
  segmentId: string;
  newPhase: string;
  ifMatchRunHash: string;
  runSet?: string;
  signal?: AbortSignal;
  timeoutMs?: number;
  clientEditDurationMs?: number | null;
}): Promise<PatchResult> {
  const {
    apiBase,
    runName,
    segmentId,
    newPhase,
    ifMatchRunHash,
    runSet,
    signal,
    timeoutMs = DEFAULT_TIMEOUT_MS,
    clientEditDurationMs,
  } = args;

  const runSetQs = runSet && runSet !== "." ? `?run_set=${encodeURIComponent(runSet)}` : "";
  const url = `${apiBase}${encodeURIComponent(runName)}/segments/${encodeURIComponent(segmentId)}${runSetQs}`;
  const timeoutCtl = new AbortController();
  const timer = setTimeout(() => timeoutCtl.abort(), timeoutMs);
  // Compose user signal + timeout into a single signal.
  if (signal) {
    if (signal.aborted) timeoutCtl.abort();
    else signal.addEventListener("abort", () => timeoutCtl.abort(), { once: true });
  }

  const bodyObj: Record<string, unknown> = { phase: newPhase };
  if (clientEditDurationMs != null) {
    bodyObj.client_edit_duration_ms = clientEditDurationMs;
  }

  let resp: Response;
  try {
    resp = await fetch(url, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        "If-Match": `"${ifMatchRunHash}"`,
      },
      body: JSON.stringify(bodyObj),
      signal: timeoutCtl.signal,
    });
  } finally {
    clearTimeout(timer);
  }

  if (resp.status === 200) {
    const runHash = stripETag(resp.headers.get("ETag"));
    if (runHash === null || !runHash.startsWith("sha256:")) {
      return {
        kind: "error",
        httpStatus: 200,
        errorCode: null,
        message: `200 response missing valid ETag header (got ${resp.headers.get("ETag")})`,
      };
    }
    const manifest = (await resp.json()) as Manifest;
    return { kind: "ok", runHash, manifest };
  }

  const env = await readErrorEnvelope(resp);
  const errorCode = env.error ?? "";
  const message = env.message;

  if (resp.status === 412) {
    return { kind: "conflict", errorCode, serverMessage: message };
  }
  if (resp.status === 400) {
    return { kind: "invalid", errorCode, serverMessage: message };
  }
  if (resp.status === 404) {
    return { kind: "not_found", errorCode, serverMessage: message };
  }
  return {
    kind: "error",
    httpStatus: resp.status,
    errorCode: env.error,
    message,
  };
}



/**
 * Extract the canonical run name from a manifest URL.
 *
 * Works for both `/api/runs/<name>/manifest.json` (api mode) and
 * `/runs/<name>/manifest.json` (static mode). Query string and hash
 * are ignored because `URL.pathname` excludes them.
 *
 * Throws if the path doesn't end with `/manifest.json` — callers
 * shouldn't be passing anything else, and a silent fallback would
 * mask real bugs.
 */
export function runNameFromManifestUrl(manifestUrl: string): string {
  const u = new URL(manifestUrl);
  const m = u.pathname.match(/\/([^/]+)\/manifest\.json$/);
  if (!m) {
    throw new Error(
      `cannot extract run name from manifest URL: ${manifestUrl}`,
    );
  }
  return m[1];
}
