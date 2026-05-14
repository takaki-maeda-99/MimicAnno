/** Phase 5 B r1 T13.6-T13.9: SegmentTable component. */
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import SegmentTable from "../SegmentTable";
import type { SubtaskSegment } from "../../lib/manifest";
import type { LabelSetDoc } from "../../lib/labelsetClient";
import type { PatchResult } from "../../lib/editClient";

const seg = (id: string, phase: string): SubtaskSegment => ({
  segment_id: id,
  episode_id: "ep0",
  start_frame: 0,
  end_frame: 30,
  start_time: 0,
  end_time: 1,
  phase,
  verb: null,
  object: null,
  target: null,
  failure_flags: [],
  label_source: "vlm",
  object_state_unavailable: false,
  object_track_ids: [],
  label_version: "1.0.0",
  start_boundary: { candidate_id: null, time: 0, sources: ["zc"], score: 0.9 },
  end_boundary: { candidate_id: null, time: 1, sources: ["zc"], score: 0.9 },
  boundary_confidence: 0.9,
  vlm_confidence: 0.8,
  overall_confidence: 0.85,
  evidence: null,
  reviewed: false,
  reviewer_id: null,
});

const SEGMENTS: SubtaskSegment[] = [
  seg("seg-001", "idle"),
  seg("seg-002", "grasp_object"),
  seg("seg-003", "idle"),
];

const LABELSET: LabelSetDoc = {
  labels: [
    { id: "idle", requires_object: false },
    { id: "grasp_object", requires_object: true },
    { id: "approach_object", requires_object: true },
  ],
  labels_yaml_sha256: "sha256:" + "a".repeat(64),
};

describe("SegmentTable — read-only mode (T13.6)", () => {
  it("renders phase as text, no <select> in static mode", () => {
    render(
      <SegmentTable
        segments={SEGMENTS}
        apiEnabled={false}
        labelset={null}
        onPhaseEdit={vi.fn()}
        editInFlight={false}
        staleRun={false}
      />,
    );
    expect(screen.getAllByRole("row")).toHaveLength(SEGMENTS.length + 1);
    expect(screen.queryAllByRole("combobox")).toHaveLength(0);
    expect(screen.getAllByText("idle")).toHaveLength(2);
  });
});

describe("SegmentTable — editable mode (T13.7)", () => {
  it("renders one <select> per segment with labelset options", () => {
    render(
      <SegmentTable
        segments={SEGMENTS}
        apiEnabled={true}
        labelset={LABELSET}
        onPhaseEdit={vi.fn()}
        editInFlight={false}
        staleRun={false}
      />,
    );
    const selects = screen.getAllByRole("combobox");
    expect(selects).toHaveLength(SEGMENTS.length);
    // Each <select> has 3 options.
    for (const sel of selects) {
      expect(sel.querySelectorAll("option")).toHaveLength(LABELSET.labels.length);
    }
    expect((selects[0] as HTMLSelectElement).value).toBe("idle");
    expect((selects[1] as HTMLSelectElement).value).toBe("grasp_object");
  });
});

describe("SegmentTable — PATCH happy flow (T13.8)", () => {
  it("calls onPhaseEdit(segmentId, newPhase, oldPhase) on change", async () => {
    const onPhaseEdit = vi
      .fn<(seg: string, newP: string, oldP: string) => Promise<PatchResult>>()
      .mockResolvedValue({
        kind: "ok",
        runHash: "sha256:" + "b".repeat(64),
        manifest: {} as never,
      });

    render(
      <SegmentTable
        segments={SEGMENTS}
        apiEnabled={true}
        labelset={LABELSET}
        onPhaseEdit={onPhaseEdit}
        editInFlight={false}
        staleRun={false}
      />,
    );
    const sel = screen.getAllByRole("combobox")[0] as HTMLSelectElement;
    fireEvent.change(sel, { target: { value: "grasp_object" } });

    await waitFor(() => expect(onPhaseEdit).toHaveBeenCalledTimes(1));
    expect(onPhaseEdit).toHaveBeenCalledWith("seg-001", "grasp_object", "idle");
    // No toast on success.
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("SegmentTable — 412 flow (T13.9)", () => {
  it("rolls back cell, shows alert, disables all selects when staleRun=true", () => {
    render(
      <SegmentTable
        segments={SEGMENTS}
        apiEnabled={true}
        labelset={LABELSET}
        onPhaseEdit={vi.fn()}
        editInFlight={false}
        staleRun={true}
        toast={{
          level: "conflict",
          message: "etag_mismatch: someone else edited this run",
        }}
      />,
    );
    expect(screen.getByRole("alert").textContent).toMatch(/etag_mismatch/);
    for (const sel of screen.getAllByRole("combobox")) {
      expect((sel as HTMLSelectElement).disabled).toBe(true);
    }
    // getByRole throws if absent → no need for toBeInTheDocument.
    expect(screen.getByRole("button", { name: /reload/i }).tagName).toBe(
      "BUTTON",
    );
  });

  it("disables all selects while editInFlight=true (self-ETag race guard)", () => {
    render(
      <SegmentTable
        segments={SEGMENTS}
        apiEnabled={true}
        labelset={LABELSET}
        onPhaseEdit={vi.fn()}
        editInFlight={true}
        staleRun={false}
      />,
    );
    for (const sel of screen.getAllByRole("combobox")) {
      expect((sel as HTMLSelectElement).disabled).toBe(true);
    }
  });
});
