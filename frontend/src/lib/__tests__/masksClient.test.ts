/** U-A4 FT1-FT5: masksClient unit tests. */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fetchMasksMeta, maskPngUrl } from "../masksClient";
import type { MasksMeta } from "../masksClient";

const META: MasksMeta = {
  run_set: "rs1",
  canonical: "ep0",
  frame_count: 3,
  shape: [240, 320],
  tracks: [
    {
      track_id: "obj:object:block:0",
      prompt: "block",
      role: "object",
      color: "#1f77b4",
      first_frame: 0,
      last_frame: 10,
    },
  ],
};

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

// FT1: fetchMasksMeta returns MasksMeta on 200
describe("fetchMasksMeta", () => {
  it("FT1: returns MasksMeta on 200 response", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(JSON.stringify(META), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    const result = await fetchMasksMeta("http://localhost:5173", "ep0", "rs1");
    expect(result).toEqual(META);
  });

  // FT2: fetchMasksMeta returns null on 204
  it("FT2: returns null on 204 (no sidecar)", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response(null, { status: 204 }));
    const result = await fetchMasksMeta("http://localhost:5173", "ep0", "rs1");
    expect(result).toBeNull();
  });

  // FT3: fetchMasksMeta throws on error status
  it("FT3: throws on non-2xx error status", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response(null, { status: 404 }));
    await expect(
      fetchMasksMeta("http://localhost:5173", "ep0", "rs1"),
    ).rejects.toThrow("404");
  });

  // FT4: URL contains encoded run_set and canonical
  it("FT4: encodes run_set and runName in URL", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(JSON.stringify(META), { status: 200 }),
    );
    await fetchMasksMeta("http://localhost:5173", "ep 0", "rs 1");
    const url = vi.mocked(fetch).mock.calls[0][0] as string;
    expect(url).toContain("ep%200");
    expect(url).toContain("rs%201");
  });
});

// FT5: maskPngUrl builds correct URL
describe("maskPngUrl", () => {
  it("FT5: builds URL with frame number and run_set", () => {
    const url = maskPngUrl("http://localhost:5173", "ep0", 42, "rs1");
    expect(url).toBe(
      "http://localhost:5173/api/runs/ep0/masks/42?run_set=rs1",
    );
  });
});
