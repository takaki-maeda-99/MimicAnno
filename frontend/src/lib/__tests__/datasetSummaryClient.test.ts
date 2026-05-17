/**
 * U-A2 — datasetSummaryClient vitest cases.
 *
 * Case 1: Happy path — mock fetch → assert parsed response
 * Case 2: Error — non-200 response → rejects with error message
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fetchDatasetSummary, type DatasetSummary } from "../datasetSummaryClient";

const MOCK_SUMMARY: DatasetSummary = {
  run_set: "so101_phase4_v5",
  ep_count: 33,
  annotated_ep_count: 17,
  label_distribution: { approach_object: 42, grasp: 17 },
  segment_count_stats: { mean: 4.5, min: 2, max: 9 },
  reviewed_rate: 0.18,
  per_episode: [
    { idx: 0, canonical: "episode_000000__abc123", segment_count: 5, reviewed_count: 3, label_diversity: 3 },
    { idx: 1, canonical: "episode_000001__def456", segment_count: 4, reviewed_count: 4, label_diversity: 2 },
  ],
};

describe("fetchDatasetSummary", () => {
  let originalFetch: typeof globalThis.fetch;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("Case 1: happy path — parses response correctly", async () => {
    globalThis.fetch = vi.fn().mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve(MOCK_SUMMARY),
    } as unknown as Response);

    const result = await fetchDatasetSummary("SO101", "so101_phase4_v5");
    expect(result.run_set).toBe("so101_phase4_v5");
    expect(result.ep_count).toBe(33);
    expect(result.annotated_ep_count).toBe(17);
    expect(result.label_distribution["approach_object"]).toBe(42);
    expect(result.segment_count_stats.mean).toBe(4.5);
    expect(result.reviewed_rate).toBe(0.18);
    expect(result.per_episode).toHaveLength(2);

    // Verify the URL includes run_set param
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/api/datasets/SO101/summary?run_set=so101_phase4_v5",
    );
  });

  it("Case 2: no run_set param → URL without query string", async () => {
    globalThis.fetch = vi.fn().mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve(MOCK_SUMMARY),
    } as unknown as Response);

    await fetchDatasetSummary("SO101");
    expect(globalThis.fetch).toHaveBeenCalledWith("/api/datasets/SO101/summary");
  });

  it("Case 3: non-200 response → rejects with error message", async () => {
    globalThis.fetch = vi.fn().mockResolvedValueOnce({
      ok: false,
      status: 404,
      json: () => Promise.resolve({ message: "dataset 'X' not found" }),
    } as unknown as Response);

    await expect(fetchDatasetSummary("X")).rejects.toThrow("dataset 'X' not found");
  });
});
