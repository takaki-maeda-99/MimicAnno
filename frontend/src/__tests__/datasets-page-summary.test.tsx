/**
 * U-A2 — DatasetsPage summary tab vitest cases.
 *
 * Case 1: Summary tab button renders in expanded dataset row
 * Case 2: Summary tab renders label distribution bars
 * Case 3: Summary tab renders per-ep table rows
 * Case 4: Run_set selector shows current run_set
 * Case 5: Empty annotated_ep_count shows "No annotations"
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import DatasetsPage from "../pages/DatasetsPage";

// ---------------------------------------------------------------------------
// Mock catalogClient
// ---------------------------------------------------------------------------

vi.mock("../lib/catalogClient", () => ({
  fetchDatasets: vi.fn(),
  fetchDataset: vi.fn(),
  postJob: vi.fn(),
  deleteJob: vi.fn(),
  fetchJobs: vi.fn(),
  fetchJob: vi.fn(),
}));

// ---------------------------------------------------------------------------
// Mock datasetSummaryClient
// ---------------------------------------------------------------------------

vi.mock("../lib/datasetSummaryClient", () => ({
  fetchDatasetSummary: vi.fn(),
}));

import { fetchDatasets, fetchDataset } from "../lib/catalogClient";
import { fetchDatasetSummary } from "../lib/datasetSummaryClient";

const mockFetchDatasets = vi.mocked(fetchDatasets);
const mockFetchDataset = vi.mocked(fetchDataset);
const mockFetchDatasetSummary = vi.mocked(fetchDatasetSummary);

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
    videos_root: null,
    last_modified: "2026-05-17T10:00:00Z",
  },
];

const SO101_DETAIL = {
  name: "SO101",
  path: "data/SO101",
  episodes: [
    {
      idx: 0,
      video_path: "videos/chunk-000/episode_000000.mp4",
      parquet_path: "data/chunk-000/episode_000000.parquet",
      frame_count: null,
      fps: 15.0,
      runs: [
        {
          canonical: "episode_000000__abc123",
          run_hash: "sha256:" + "a".repeat(64),
          run_set: "so101_phase4_v5",
          pipeline_phase: 4,
          generated_at: "2026-05-16T10:00:00Z",
        },
      ],
    },
  ],
};

const MOCK_SUMMARY = {
  run_set: "so101_phase4_v5",
  ep_count: 33,
  annotated_ep_count: 2,
  label_distribution: { approach_object: 8, grasp: 4, place_object: 2 },
  segment_count_stats: { mean: 4.5, min: 3, max: 6 },
  reviewed_rate: 0.75,
  per_episode: [
    { idx: 0, canonical: "episode_000000__abc123", segment_count: 6, reviewed_count: 5, label_diversity: 3 },
    { idx: 1, canonical: "episode_000001__def456", segment_count: 3, reviewed_count: 3, label_diversity: 2 },
  ],
};

const MOCK_SUMMARY_EMPTY = {
  run_set: "so101_empty",
  ep_count: 33,
  annotated_ep_count: 0,
  label_distribution: {},
  segment_count_stats: { mean: 0, min: 0, max: 0 },
  reviewed_rate: 0.0,
  per_episode: [],
};

beforeEach(() => {
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function expandDataset(name: string) {
  mockFetchDatasets.mockResolvedValueOnce(DATASETS);
  mockFetchDataset.mockResolvedValueOnce(SO101_DETAIL);
  render(<DatasetsPage />);
  await waitFor(() => screen.getByTestId("datasets-page"));
  fireEvent.click(screen.getByTestId(`ds-name-${name}`));
  await waitFor(() => screen.getByTestId(`ep-table-${name}`));
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("DatasetsPage — U-A2 summary tab", () => {
  it("Case 1: Summary tab button renders in expanded dataset row", async () => {
    await expandDataset("SO101");
    expect(screen.getByTestId("summary-tab-btn-SO101")).toBeTruthy();
  });

  it("Case 2: Summary tab renders label distribution bars", async () => {
    await expandDataset("SO101");
    mockFetchDatasetSummary.mockResolvedValueOnce(MOCK_SUMMARY);
    fireEvent.click(screen.getByTestId("summary-tab-btn-SO101"));
    await waitFor(() => screen.getByTestId("label-distribution-SO101"));
    // Three bars should be rendered
    expect(screen.getByTestId("label-bar-approach_object")).toBeTruthy();
    expect(screen.getByTestId("label-bar-grasp")).toBeTruthy();
    expect(screen.getByTestId("label-bar-place_object")).toBeTruthy();
  });

  it("Case 3: Summary tab renders per-ep table rows", async () => {
    await expandDataset("SO101");
    mockFetchDatasetSummary.mockResolvedValueOnce(MOCK_SUMMARY);
    fireEvent.click(screen.getByTestId("summary-tab-btn-SO101"));
    await waitFor(() => screen.getByTestId("per-ep-table-SO101"));
    expect(screen.getByTestId("per-ep-row-0")).toBeTruthy();
    expect(screen.getByTestId("per-ep-row-1")).toBeTruthy();
  });

  it("Case 4: Run_set selector shows current run_set", async () => {
    await expandDataset("SO101");
    mockFetchDatasetSummary.mockResolvedValueOnce(MOCK_SUMMARY);
    fireEvent.click(screen.getByTestId("summary-tab-btn-SO101"));
    await waitFor(() => screen.getByTestId("run-set-display-SO101"));
    const el = screen.getByTestId("run-set-display-SO101");
    expect(el.textContent).toContain("so101_phase4_v5");
  });

  it("Case 5: Empty annotated_ep_count shows 'No annotations'", async () => {
    await expandDataset("SO101");
    mockFetchDatasetSummary.mockResolvedValueOnce(MOCK_SUMMARY_EMPTY);
    fireEvent.click(screen.getByTestId("summary-tab-btn-SO101"));
    await waitFor(() => screen.getByTestId("summary-empty-SO101"));
  });
});
