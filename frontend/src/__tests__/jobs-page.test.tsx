/**
 * U-A1 F3 — JobsPage vitest cases.
 *
 * Case 1: Renders job list from mocked GET /api/jobs
 * Case 2: Status badge colors (status badge rendered)
 * Case 3: Click job → fetches job detail
 * Case 4: Cancel button fires DELETE /api/jobs/{id}
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import JobsPage from "../pages/JobsPage";

// ---------------------------------------------------------------------------
// catalogClient mock
// ---------------------------------------------------------------------------

vi.mock("../lib/catalogClient", () => ({
  fetchDatasets: vi.fn(),
  fetchDataset: vi.fn(),
  postJob: vi.fn(),
  deleteJob: vi.fn(),
  fetchJobs: vi.fn(),
  fetchJob: vi.fn(),
}));

import { fetchJobs, fetchJob, deleteJob } from "../lib/catalogClient";

const mockFetchJobs = vi.mocked(fetchJobs);
const mockFetchJob = vi.mocked(fetchJob);
const mockDeleteJob = vi.mocked(deleteJob);

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const JOBS = [
  {
    job_id: "j_20260517_120000_aaaa",
    status: "done",
    dataset: "SO101",
    progress_pct: 100,
    current_episode_idx: null,
    started_at: "2026-05-17T12:00:01Z",
    finished_at: "2026-05-17T12:30:00Z",
    run_canonicals: ["episode_000000__abc123"],
  },
  {
    job_id: "j_20260517_130000_bbbb",
    status: "running",
    dataset: "SO101",
    progress_pct: 50,
    current_episode_idx: 2,
    started_at: "2026-05-17T13:00:01Z",
    finished_at: null,
    run_canonicals: [],
  },
];

const JOB_DETAIL = {
  job_id: "j_20260517_130000_bbbb",
  status: "running",
  kind: "annotate",
  dataset: "SO101",
  episode_indices: [0, 1, 2, 3],
  run_set: "so101_test_run",
  variant: "4B",
  gpu_index: 0,
  robot_config: "configs/robot/so101.yaml",
  pipeline_config: "configs/pipeline/phase4.yaml",
  queued_at: "2026-05-17T13:00:00Z",
  started_at: "2026-05-17T13:00:01Z",
  finished_at: null,
  progress_pct: 50,
  current_episode_idx: 2,
  run_canonicals: [],
  log_tail: ["[Phase 1] ep 0 done", "[Phase 1] ep 1 done"],
  log_url: "/api/jobs/j_20260517_130000_bbbb/log",
  error: null,
};

beforeEach(() => {
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// F3 — Jobs page
// ---------------------------------------------------------------------------

describe("JobsPage — F3 job list", () => {
  it("Case 1: renders job list from mocked fetchJobs", async () => {
    mockFetchJobs.mockResolvedValue(JOBS);
    render(<JobsPage />);
    expect(screen.getByTestId("jobs-loading")).toBeTruthy();
    await waitFor(() => screen.getByTestId("jobs-page"));
    expect(screen.getByTestId("job-id-j_20260517_120000_aaaa")).toBeTruthy();
    expect(screen.getByTestId("job-id-j_20260517_130000_bbbb")).toBeTruthy();
  });

  it("Case 2: status badges are rendered with correct status", async () => {
    mockFetchJobs.mockResolvedValue(JOBS);
    render(<JobsPage />);
    await waitFor(() => screen.getByTestId("jobs-page"));
    // Two badges: done and running
    expect(screen.getByTestId("status-badge-done")).toBeTruthy();
    expect(screen.getByTestId("status-badge-running")).toBeTruthy();
  });

  it("Case 3: click job → fetches job detail and shows detail panel", async () => {
    mockFetchJobs.mockResolvedValue(JOBS);
    mockFetchJob.mockResolvedValue(JOB_DETAIL);
    render(<JobsPage />);
    await waitFor(() => screen.getByTestId("jobs-page"));
    fireEvent.click(screen.getByTestId("detail-btn-j_20260517_130000_bbbb"));
    await waitFor(() => screen.getByTestId("job-detail-panel"));
    expect(mockFetchJob).toHaveBeenCalledWith("j_20260517_130000_bbbb");
    expect(screen.getByTestId("job-log-tail")).toBeTruthy();
  });

  it("Case 4: cancel button fires deleteJob", async () => {
    mockFetchJobs.mockResolvedValue(JOBS);
    mockFetchJob.mockResolvedValue(JOB_DETAIL);
    mockDeleteJob.mockResolvedValue(undefined);
    render(<JobsPage />);
    await waitFor(() => screen.getByTestId("jobs-page"));
    fireEvent.click(screen.getByTestId("detail-btn-j_20260517_130000_bbbb"));
    await waitFor(() => screen.getByTestId("job-detail-panel"));
    fireEvent.click(screen.getByTestId("cancel-job-btn"));
    await waitFor(() => expect(mockDeleteJob).toHaveBeenCalledWith("j_20260517_130000_bbbb"));
  });
});
