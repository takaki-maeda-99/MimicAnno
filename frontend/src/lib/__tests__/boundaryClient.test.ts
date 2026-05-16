/** Phase 5 D smoke fix: runSet propagation in patchBoundaryFrame URL. */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { patchBoundaryFrame } from "../boundaryClient";

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

describe("patchBoundaryFrame — runSet query param (S-RS)", () => {
  it("appends ?run_set= when runSet is provided", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      new Response(JSON.stringify(manifestStub(NEW_HASH)), {
        status: 200,
        headers: { "ETag": `"${NEW_HASH}"`, "Content-Type": "application/json" },
      }),
    );
    await patchBoundaryFrame({
      apiBase: "/api/runs/",
      runName: "ep0__abc",
      boundaryId: "seg-002",
      newFrame: 100,
      ifMatchRunHash: OK_HASH,
      runSet: "so101_phase4_v5",
    });
    const url = vi.mocked(globalThis.fetch).mock.calls[0][0] as string;
    expect(url).toBe("/api/runs/ep0__abc/boundaries/seg-002?run_set=so101_phase4_v5");
  });

  it("does not append ?run_set= when runSet is '.'", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      new Response(JSON.stringify(manifestStub(NEW_HASH)), {
        status: 200,
        headers: { "ETag": `"${NEW_HASH}"`, "Content-Type": "application/json" },
      }),
    );
    await patchBoundaryFrame({
      apiBase: "/api/runs/",
      runName: "ep0__abc",
      boundaryId: "seg-002",
      newFrame: 100,
      ifMatchRunHash: OK_HASH,
      runSet: ".",
    });
    const url = vi.mocked(globalThis.fetch).mock.calls[0][0] as string;
    expect(url).toBe("/api/runs/ep0__abc/boundaries/seg-002");
  });

  it("does not append ?run_set= when runSet is undefined", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      new Response(JSON.stringify(manifestStub(NEW_HASH)), {
        status: 200,
        headers: { "ETag": `"${NEW_HASH}"`, "Content-Type": "application/json" },
      }),
    );
    await patchBoundaryFrame({
      apiBase: "/api/runs/",
      runName: "ep0__abc",
      boundaryId: "seg-002",
      newFrame: 100,
      ifMatchRunHash: OK_HASH,
    });
    const url = vi.mocked(globalThis.fetch).mock.calls[0][0] as string;
    expect(url).toBe("/api/runs/ep0__abc/boundaries/seg-002");
  });
});
