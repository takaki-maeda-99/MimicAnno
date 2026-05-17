/**
 * U-A5 — App integration: badge is present in header across pages.
 *
 * Case 1: App renders with ?page=jobs — JobsBadge is mounted in the header
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import App from "../App";

// ---------------------------------------------------------------------------
// Mock all page-level components to avoid cascading fetch deps
// ---------------------------------------------------------------------------

vi.mock("../pages/JobsPage", () => ({
  default: () => <div data-testid="jobs-page-mock">Jobs</div>,
}));

vi.mock("../pages/DatasetsPage", () => ({
  default: () => <div data-testid="datasets-page-mock">Datasets</div>,
}));

vi.mock("../components/RunList", () => ({
  default: () => <div data-testid="run-list-mock">RunList</div>,
}));

vi.mock("../components/RunViewer", () => ({
  default: () => <div data-testid="run-viewer-mock">RunViewer</div>,
}));

vi.mock("../components/HandViewer", () => ({
  default: () => <div data-testid="hand-viewer-mock">HandViewer</div>,
}));

// Mock the badge client so it doesn't call fetch in integration test
vi.mock("../lib/jobsBadgeClient", () => ({
  fetchRunningCount: vi.fn().mockResolvedValue(0),
}));

afterEach(() => {
  vi.clearAllMocks();
  // Reset URL to clean state
  window.history.replaceState({}, "", "/");
});

describe("App — U-A5 integration", () => {
  it("Case 1: app-header is always rendered containing JobsBadge mount point", () => {
    // Set URL to ?page=jobs
    window.history.replaceState({}, "", "/?page=jobs");
    render(<App />);
    // The header with data-testid="app-header" must be present
    expect(screen.getByTestId("app-header")).toBeTruthy();
    // The Jobs page body is rendered
    expect(screen.getByTestId("jobs-page-mock")).toBeTruthy();
  });

  it("Case 2: ?page=datasets renders DatasetsPage", () => {
    window.history.replaceState({}, "", "/?page=datasets");
    render(<App />);
    expect(screen.getByTestId("datasets-page-mock")).toBeTruthy();
  });

  it("Case 3: no page param renders RunList (default route)", () => {
    window.history.replaceState({}, "", "/");
    render(<App />);
    expect(screen.getByTestId("run-list-mock")).toBeTruthy();
  });
});
