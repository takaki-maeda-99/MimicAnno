/** Phase 5 B r1 T13.5: labelset fetch + module-scope cache. */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  loadLabelset,
  __resetLabelsetCacheForTests,
} from "../labelsetClient";

const docA = {
  labels: [
    { id: "idle", requires_object: false },
    { id: "grasp_object", requires_object: true },
  ],
  labels_yaml_sha256: "sha256:" + "a".repeat(64),
};

const docB = {
  labels: [{ id: "different", requires_object: false }],
  labels_yaml_sha256: "sha256:" + "b".repeat(64),
};

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
  __resetLabelsetCacheForTests();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("loadLabelset", () => {
  it("returns parsed labelset on first call", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      new Response(JSON.stringify(docA), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const r = await loadLabelset("/api/runs/");
    expect(r).toEqual(docA);
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
  });

  it("caches by apiBase — second call does not re-fetch", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      new Response(JSON.stringify(docA), { status: 200 }),
    );
    await loadLabelset("/api/runs/");
    await loadLabelset("/api/runs/");
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
  });

  it("different apiBase triggers a fresh fetch", async () => {
    vi.mocked(globalThis.fetch)
      .mockResolvedValueOnce(
        new Response(JSON.stringify(docA), { status: 200 }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(docB), { status: 200 }),
      );
    await loadLabelset("/api/runs/");
    const second = await loadLabelset("/api/runs-v2/");
    expect(second).toEqual(docB);
    expect(globalThis.fetch).toHaveBeenCalledTimes(2);
  });

  it("requests /api/labelset (sibling of /api/runs/)", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      new Response(JSON.stringify(docA), { status: 200 }),
    );
    await loadLabelset("/api/runs/");
    const url = vi.mocked(globalThis.fetch).mock.calls[0][0] as string;
    expect(url).toBe("/api/labelset");
  });
});
