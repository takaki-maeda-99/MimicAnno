/**
 * Phase 5 B r2 T11 — PATCH client for
 * /api/runs/{name}/boundaries/{boundary_id}.
 *
 * Same tagged-union contract as editClient.ts:
 *   - 200: response body is the new full Manifest + ETag header
 *   - 412: etag_mismatch — spring the handle back, set staleRun flag
 *   - 400: invalid_boundary / invalid_frame / invalid_body
 *   - 404: run_not_found
 *   - 10s timeout to prevent UI lock-up on a hung server
 */
import type { Manifest } from "./manifest";

export type BoundaryPatchResult =
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
  const m = raw.match(/^W?\/?"(.+)"$/);
  return m ? m[1] : null;
}

export async function patchBoundaryFrame(args: {
  apiBase: string;
  runName: string;
  boundaryId: string;
  newFrame: number;
  ifMatchRunHash: string;
  signal?: AbortSignal;
  timeoutMs?: number;
}): Promise<BoundaryPatchResult> {
  const {
    apiBase,
    runName,
    boundaryId,
    newFrame,
    ifMatchRunHash,
    signal,
    timeoutMs = DEFAULT_TIMEOUT_MS,
  } = args;

  const url = `${apiBase}${encodeURIComponent(runName)}/boundaries/${encodeURIComponent(boundaryId)}`;
  const timeoutCtl = new AbortController();
  const timer = setTimeout(() => timeoutCtl.abort(), timeoutMs);
  if (signal) {
    if (signal.aborted) timeoutCtl.abort();
    else signal.addEventListener("abort", () => timeoutCtl.abort(), { once: true });
  }

  let resp: Response;
  try {
    resp = await fetch(url, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        "If-Match": `"${ifMatchRunHash}"`,
      },
      body: JSON.stringify({ frame: newFrame }),
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
