/**
 * U-A5 — jobsBadgeClient tests.
 *
 * Case 1: fetchRunningCount returns count on success
 * Case 2: fetchRunningCount returns 0 on network error
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { fetchRunningCount } from "../jobsBadgeClient";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("fetchRunningCount", () => {
  it("Case 1: returns count of running jobs on success", async () => {
    const jobs = [
      { job_id: "j_001", status: "running" },
      { job_id: "j_002", status: "running" },
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => jobs,
      }),
    );

    const count = await fetchRunningCount();

    expect(count).toBe(2);
    expect(vi.mocked(fetch)).toHaveBeenCalledWith("/api/jobs?status=running");
  });

  it("Case 2: returns 0 on network error (fail-silent)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new Error("Network error")),
    );

    const count = await fetchRunningCount();

    expect(count).toBe(0);
  });

  it("Case 3: returns 0 on non-ok HTTP response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
      }),
    );

    const count = await fetchRunningCount();

    expect(count).toBe(0);
  });
});
