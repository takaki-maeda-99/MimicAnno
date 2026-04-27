const MAX_ATTEMPTS = 3;
const BACKOFF_MS = 100;

export async function fetchRetry(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
    // Network errors and AbortError propagate immediately — no retry.
    // This is intentional: 5xx and network failures indicate real bugs in
    // Phase 1 (no proxy in front of the dev server), and abort means the
    // caller has already moved on (URL change race in RunViewer).
    const r = await fetch(input, init);
    if (r.status === 404) {
      if (attempt < MAX_ATTEMPTS) {
        await new Promise((resolve) => setTimeout(resolve, BACKOFF_MS));
        continue;
      }
      throw new Error(`fetchRetry: 404 after ${MAX_ATTEMPTS} attempts: ${String(input)}`);
    }
    if (!r.ok) {
      throw new Error(`fetchRetry: HTTP ${r.status}: ${String(input)}`);
    }
    return r;
  }
  throw new Error("fetchRetry: unreachable");
}
