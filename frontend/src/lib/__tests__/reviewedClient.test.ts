/** Phase 5 D smoke fix: runSet propagation in patchReviewed URL. */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { patchReviewed } from "../reviewedClient";

const OK_HASH = "sha256:" + "a".repeat(64);
const NEW_HASH = "sha256:" + "b".repeat(64);

function manifestStub(runHash: string) {
  return {
    schema_version: "1.0.0",
    episode_id: "ep0",
    run_hash: runHash,
  };
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("patchReviewed — runSet query param (S-RS)", () => {
  it("appends ?run_set= when runSet is provided", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      new Response(JSON.stringify(manifestStub(NEW_HASH)), {
        status: 200,
        headers: { "ETag": `"${NEW_HASH}"`, "Content-Type": "application/json" },
      }),
    );
    await patchReviewed({
      apiBase: "/api/runs/",
      runName: "ep0__abc",
      segmentId: "seg-001",
      reviewed: true,
      ifMatchRunHash: OK_HASH,
      runSet: "so101_phase4_v5",
    });
    const url = vi.mocked(globalThis.fetch).mock.calls[0][0] as string;
    expect(url).toBe("/api/runs/ep0__abc/segments/seg-001/reviewed?run_set=so101_phase4_v5");
  });

  it("does not append ?run_set= when runSet is '.'", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      new Response(JSON.stringify(manifestStub(NEW_HASH)), {
        status: 200,
        headers: { "ETag": `"${NEW_HASH}"`, "Content-Type": "application/json" },
      }),
    );
    await patchReviewed({
      apiBase: "/api/runs/",
      runName: "ep0__abc",
      segmentId: "seg-001",
      reviewed: true,
      ifMatchRunHash: OK_HASH,
      runSet: ".",
    });
    const url = vi.mocked(globalThis.fetch).mock.calls[0][0] as string;
    expect(url).toBe("/api/runs/ep0__abc/segments/seg-001/reviewed");
  });

  it("does not append ?run_set= when runSet is undefined", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      new Response(JSON.stringify(manifestStub(NEW_HASH)), {
        status: 200,
        headers: { "ETag": `"${NEW_HASH}"`, "Content-Type": "application/json" },
      }),
    );
    await patchReviewed({
      apiBase: "/api/runs/",
      runName: "ep0__abc",
      segmentId: "seg-001",
      reviewed: true,
      ifMatchRunHash: OK_HASH,
    });
    const url = vi.mocked(globalThis.fetch).mock.calls[0][0] as string;
    expect(url).toBe("/api/runs/ep0__abc/segments/seg-001/reviewed");
  });
});
