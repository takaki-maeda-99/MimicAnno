/**
 * U-A1 followup — App routing integration tests.
 *
 * Verifies that App.tsx routes to the correct page component based on the
 * ?page= URL parameter (URL-param convention, consistent with existing
 * ?run= / ?hand= / ?run_set= dispatch).
 *
 * Cases:
 *   1. ?page=datasets → renders DatasetsPage (datasets-loading testid visible)
 *   2. ?page=jobs → renders JobsPage (jobs-loading testid visible)
 *   3. No page param, no run/hand → renders RunList
 *   4. ?page= unknown value → falls back to RunList
 *   5. ?page=datasets doesn't break existing ?run= flow (run= takes priority)
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import App from "../App";

// ---------------------------------------------------------------------------
// Mocks: all heavy components + API clients
// ---------------------------------------------------------------------------

vi.mock("../components/RunList", () => ({
  default: () => <div data-testid="run-list-mock">RunList</div>,
}));

vi.mock("../components/RunViewer", () => ({
  default: () => <div data-testid="run-viewer-mock">RunViewer</div>,
}));

vi.mock("../components/HandViewer", () => ({
  default: () => <div data-testid="hand-viewer-mock">HandViewer</div>,
}));

vi.mock("../lib/catalogClient", () => ({
  fetchDatasets: vi.fn(() => new Promise(() => { /* never resolves */ })),
  fetchDataset: vi.fn(),
  postJob: vi.fn(),
  deleteJob: vi.fn(),
  fetchJobs: vi.fn(() => new Promise(() => { /* never resolves */ })),
  fetchJob: vi.fn(),
}));

// ---------------------------------------------------------------------------
// URL helpers
// ---------------------------------------------------------------------------

function setSearchParams(params: Record<string, string>) {
  const url = new URL("http://localhost/");
  for (const [k, v] of Object.entries(params)) {
    url.searchParams.set(k, v);
  }
  Object.defineProperty(window, "location", {
    value: new URL(url.href),
    writable: true,
    configurable: true,
  });
}

beforeEach(() => {
  // Reset to bare URL
  Object.defineProperty(window, "location", {
    value: new URL("http://localhost/"),
    writable: true,
    configurable: true,
  });
});

afterEach(() => {
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("App routing — ?page= URL param dispatch", () => {
  it("Case 1: ?page=datasets renders DatasetsPage (shows datasets-loading)", async () => {
    setSearchParams({ page: "datasets" });
    render(<App />);
    // DatasetsPage shows datasets-loading while fetchDatasets is pending
    await waitFor(() => screen.getByTestId("datasets-loading"));
    expect(screen.queryByTestId("run-list-mock")).toBeNull();
    expect(screen.queryByTestId("run-viewer-mock")).toBeNull();
  });

  it("Case 2: ?page=jobs renders JobsPage (shows jobs-loading)", async () => {
    setSearchParams({ page: "jobs" });
    render(<App />);
    await waitFor(() => screen.getByTestId("jobs-loading"));
    expect(screen.queryByTestId("run-list-mock")).toBeNull();
  });

  it("Case 3: no page param and no run/hand → renders RunList", () => {
    // default URL: no params
    render(<App />);
    expect(screen.getByTestId("run-list-mock")).toBeTruthy();
  });

  it("Case 4: unknown ?page= value → falls back to RunList", () => {
    setSearchParams({ page: "unknown-page" });
    render(<App />);
    expect(screen.getByTestId("run-list-mock")).toBeTruthy();
  });

  it("Case 5: ?run= present alongside ?page= → RunViewer wins (existing flow preserved)", () => {
    setSearchParams({ run: "ep_001", page: "datasets" });
    render(<App />);
    expect(screen.getByTestId("run-viewer-mock")).toBeTruthy();
    expect(screen.queryByTestId("datasets-loading")).toBeNull();
  });
});
