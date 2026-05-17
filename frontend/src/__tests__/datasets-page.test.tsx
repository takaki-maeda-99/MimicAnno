/**
 * U-A1 F1+F2 — DatasetsPage vitest cases.
 *
 * F1: Dataset list rendering
 *   Case 1: Renders dataset list from mocked GET /api/datasets
 *   Case 2: Shows ep_count and annotated_ep_count per row
 *   Case 3: Loading state while fetching
 *   Case 4: Click row → fetches GET /api/datasets/{name}, shows episode table
 *   Case 5: Error state on fetch failure
 *
 * F2: AnnotateModal
 *   Case 1: Form renders with correct fields
 *   Case 2: Submit fires POST /api/jobs with correct body
 *   Case 3: 409 response shows user-friendly error
 *   Case 4: Success shows toast
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import DatasetsPage from "../pages/DatasetsPage";

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

import {
  fetchDatasets,
  fetchDataset,
  postJob,
} from "../lib/catalogClient";

const mockFetchDatasets = vi.mocked(fetchDatasets);
const mockFetchDataset = vi.mocked(fetchDataset);
const mockPostJob = vi.mocked(postJob);

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const DATASETS = [
  {
    name: "SO101",
    path: "data/SO101",
    ep_count: 33,
    annotated_ep_count: 17,
    robot_hint: "so101",
    task_text_hint: "Put the tape into the bottle",
    videos_root: "videos/chunk-000/observation.images.front",
    last_modified: "2026-05-17T10:00:00Z",
  },
  {
    name: "Piper",
    path: "data/Piper",
    ep_count: 10,
    annotated_ep_count: 0,
    robot_hint: null,
    task_text_hint: null,
    videos_root: null,
    last_modified: "2026-05-16T08:00:00Z",
  },
];

const SO101_DETAIL = {
  name: "SO101",
  path: "data/SO101",
  episodes: [
    {
      idx: 0,
      video_path: "videos/observation.images.front/chunk-000/episode_000000.mp4",
      parquet_path: "data/chunk-000/episode_000000.parquet",
      frame_count: null,
      fps: 15.0,
      runs: [
        {
          canonical: "episode_000000__abc123def456",
          run_hash: "sha256:" + "a".repeat(64),
          run_set: "so101_phase4_v5",
          pipeline_phase: 4,
          generated_at: "2026-05-16T10:00:00Z",
        },
      ],
    },
    {
      idx: 1,
      video_path: "videos/observation.images.front/chunk-000/episode_000001.mp4",
      parquet_path: "data/chunk-000/episode_000001.parquet",
      frame_count: null,
      fps: 15.0,
      runs: [],
    },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// F1 — Dataset list
// ---------------------------------------------------------------------------

describe("DatasetsPage — F1 dataset list", () => {
  it("Case 1: renders dataset list from mocked fetchDatasets", async () => {
    mockFetchDatasets.mockResolvedValueOnce(DATASETS);
    render(<DatasetsPage />);
    expect(screen.getByTestId("datasets-loading")).toBeTruthy();
    await waitFor(() => screen.getByTestId("datasets-page"));
    expect(screen.getByTestId("ds-name-SO101")).toBeTruthy();
    expect(screen.getByTestId("ds-name-Piper")).toBeTruthy();
  });

  it("Case 2: shows ep_count and annotated_ep_count per row", async () => {
    mockFetchDatasets.mockResolvedValueOnce(DATASETS);
    render(<DatasetsPage />);
    await waitFor(() => screen.getByTestId("datasets-page"));
    expect(screen.getByTestId("ds-ep-count-SO101").textContent).toBe("33");
    expect(screen.getByTestId("ds-annotated-SO101").textContent).toBe("17");
    expect(screen.getByTestId("ds-ep-count-Piper").textContent).toBe("10");
    expect(screen.getByTestId("ds-annotated-Piper").textContent).toBe("0");
  });

  it("Case 3: loading state while fetching", async () => {
    let resolve: ((v: typeof DATASETS) => void) | null = null;
    mockFetchDatasets.mockReturnValueOnce(
      new Promise((r) => { resolve = r; })
    );
    render(<DatasetsPage />);
    expect(screen.getByTestId("datasets-loading")).toBeTruthy();
    resolve!(DATASETS);
    await waitFor(() => screen.getByTestId("datasets-page"));
  });

  it("Case 4: click row → fetches detail, shows episode table", async () => {
    mockFetchDatasets.mockResolvedValueOnce(DATASETS);
    mockFetchDataset.mockResolvedValueOnce(SO101_DETAIL);
    render(<DatasetsPage />);
    await waitFor(() => screen.getByTestId("datasets-page"));
    fireEvent.click(screen.getByTestId("ds-name-SO101"));
    await waitFor(() => screen.getByTestId("ep-table-SO101"));
    expect(mockFetchDataset).toHaveBeenCalledWith("SO101");
  });

  it("Case 5: error state on fetch failure", async () => {
    mockFetchDatasets.mockRejectedValueOnce(new Error("network error"));
    render(<DatasetsPage />);
    await waitFor(() => screen.getByTestId("datasets-error"));
    expect(screen.getByTestId("datasets-error").textContent).toContain("network error");
  });
});

// ---------------------------------------------------------------------------
// F2 — AnnotateModal
// ---------------------------------------------------------------------------

describe("DatasetsPage — F2 annotate modal", () => {
  it("Case 1: form renders with correct fields", async () => {
    mockFetchDatasets.mockResolvedValueOnce(DATASETS);
    render(<DatasetsPage />);
    await waitFor(() => screen.getByTestId("datasets-page"));
    fireEvent.click(screen.getByTestId("annotate-btn-SO101"));
    expect(screen.getByTestId("annotate-modal")).toBeTruthy();
    expect(screen.getByTestId("input-run-set")).toBeTruthy();
    expect(screen.getByTestId("input-robot-config")).toBeTruthy();
    expect(screen.getByTestId("input-pipeline-config")).toBeTruthy();
    expect(screen.getByTestId("input-episode-indices")).toBeTruthy();
    expect(screen.getByTestId("input-gpu-index")).toBeTruthy();
    expect(screen.getByTestId("input-variant")).toBeTruthy();
  });

  it("Case 2: submit fires POST /api/jobs with correct body", async () => {
    mockFetchDatasets.mockResolvedValueOnce(DATASETS);
    mockPostJob.mockResolvedValueOnce({ job_id: "j_20260517_120000_abcd", status: "queued" });
    render(<DatasetsPage />);
    await waitFor(() => screen.getByTestId("datasets-page"));
    fireEvent.click(screen.getByTestId("annotate-btn-SO101"));
    // Fill in run_set
    fireEvent.change(screen.getByTestId("input-run-set"), { target: { value: "so101_test_run" } });
    fireEvent.change(screen.getByTestId("input-episode-indices"), { target: { value: "0, 1, 2" } });
    fireEvent.click(screen.getByTestId("submit-annotate"));
    await waitFor(() => screen.getByTestId("job-queued-toast"));
    expect(mockPostJob).toHaveBeenCalledWith(
      expect.objectContaining({
        dataset: "SO101",
        run_set: "so101_test_run",
        episode_indices: [0, 1, 2],
      }),
    );
  });

  it("Case 3: 409 response shows user-friendly error", async () => {
    mockFetchDatasets.mockResolvedValueOnce(DATASETS);
    mockPostJob.mockRejectedValueOnce(new Error("run_set already has overlapping runs."));
    render(<DatasetsPage />);
    await waitFor(() => screen.getByTestId("datasets-page"));
    fireEvent.click(screen.getByTestId("annotate-btn-SO101"));
    fireEvent.click(screen.getByTestId("submit-annotate"));
    await waitFor(() => screen.getByTestId("modal-error"));
    expect(screen.getByTestId("modal-error").textContent).toContain("overlapping runs");
  });

  it("Case 4: success shows job-queued toast", async () => {
    mockFetchDatasets.mockResolvedValueOnce(DATASETS);
    mockPostJob.mockResolvedValueOnce({ job_id: "j_20260517_120000_xxxx", status: "queued" });
    render(<DatasetsPage />);
    await waitFor(() => screen.getByTestId("datasets-page"));
    fireEvent.click(screen.getByTestId("annotate-btn-SO101"));
    fireEvent.click(screen.getByTestId("submit-annotate"));
    await waitFor(() => screen.getByTestId("job-queued-toast"));
    expect(screen.getByTestId("job-queued-toast").textContent).toContain("j_20260517_120000_xxxx");
  });
});
