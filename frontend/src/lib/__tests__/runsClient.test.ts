/** S-RS T7: fetchRunSets unit tests. */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fetchRunSets } from "../runsClient";

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchRunSets", () => {
  it("returns entries on 200", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(
        JSON.stringify([
          { name: "so101_phase4_v5", label: "so101_phase4_v5" },
          { name: "piper_phase4_v5", label: "piper_phase4_v5" },
        ]),
        { status: 200 },
      ),
    );
    const result = await fetchRunSets();
    expect(result).toHaveLength(2);
    expect(result[0].name).toBe("so101_phase4_v5");
  });

  it("returns [] on non-200 status", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response("{}", { status: 503 }));
    const result = await fetchRunSets();
    expect(result).toEqual([]);
  });

  it("returns [] on network error", async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new Error("network"));
    const result = await fetchRunSets();
    expect(result).toEqual([]);
  });
});
