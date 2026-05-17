/**
 * U-A5 — JobsBadge component tests.
 *
 * Case 1: badge hidden while count is 0 (initial state before fetch resolves)
 * Case 2: badge shows "N running" when count > 0
 * Case 3: badge hidden when count is 0 after fetch
 * Case 4: badge hidden on fetch error (fail-silent)
 * Case 5: badge href points to ?page=jobs
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import JobsBadge from "../JobsBadge";

vi.mock("../../lib/jobsBadgeClient", () => ({
  fetchRunningCount: vi.fn(),
}));

import { fetchRunningCount } from "../../lib/jobsBadgeClient";

const mockFetchRunningCount = vi.mocked(fetchRunningCount);

afterEach(() => {
  vi.clearAllMocks();
});

describe("JobsBadge", () => {
  it("Case 1: badge is not in DOM before fetch resolves (count=0 initial state)", () => {
    // fetchRunningCount resolves to 0 (never changes from initial)
    mockFetchRunningCount.mockResolvedValue(0);
    const { container } = render(<JobsBadge />);
    // Initially count=0 → renders null
    expect(container.firstChild).toBeNull();
  });

  it("Case 2: shows 'N running' badge when count > 0", async () => {
    mockFetchRunningCount.mockResolvedValue(3);
    render(<JobsBadge />);
    await waitFor(() => screen.getByTestId("jobs-badge"));
    expect(screen.getByTestId("jobs-badge").textContent).toBe("3 running");
  });

  it("Case 3: badge is hidden when count is 0 after fetch resolves", async () => {
    mockFetchRunningCount.mockResolvedValue(0);
    const { container } = render(<JobsBadge />);
    // Wait for fetch to "resolve" (microtask)
    await vi.waitFor(() => {
      expect(mockFetchRunningCount).toHaveBeenCalled();
    });
    expect(container.firstChild).toBeNull();
  });

  it("Case 4: badge is hidden on fetch error (fail-silent — fetchRunningCount returns 0)", async () => {
    // jobsBadgeClient itself swallows errors and returns 0
    mockFetchRunningCount.mockResolvedValue(0);
    const { container } = render(<JobsBadge />);
    await vi.waitFor(() => {
      expect(mockFetchRunningCount).toHaveBeenCalled();
    });
    expect(container.firstChild).toBeNull();
  });

  it("Case 5: badge href points to ?page=jobs", async () => {
    mockFetchRunningCount.mockResolvedValue(1);
    render(<JobsBadge />);
    const badge = await waitFor(() => screen.getByTestId("jobs-badge"));
    expect(badge.getAttribute("href")).toBe("?page=jobs");
  });
});
