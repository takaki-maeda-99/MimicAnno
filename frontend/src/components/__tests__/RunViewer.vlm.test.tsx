/** U-A3 — RunViewer ↔ VlmPanel integration: selectSegmentIdByTime. */
import { describe, it, expect } from "vitest";
import { selectSegmentIdByTime } from "../RunViewer";
import type { SubtaskSegment } from "../../lib/manifest";

function seg(id: string, start: number, end: number): SubtaskSegment {
  return {
    segment_id: id,
    episode_id: "ep0",
    start_frame: 0,
    end_frame: 30,
    start_time: start,
    end_time: end,
    phase: "idle",
    verb: null,
    object: null,
    target: null,
    failure_flags: [],
    label_source: "vlm",
    object_state_unavailable: false,
    object_track_ids: [],
    label_version: "1.0.0",
    start_boundary: { candidate_id: null, time: start, sources: [], score: 1 },
    end_boundary: { candidate_id: null, time: end, sources: [], score: 1 },
    boundary_confidence: 1,
    vlm_confidence: 1,
    overall_confidence: 1,
    evidence: null,
    reviewed: false,
    reviewer_id: null,
  };
}

const SEGMENTS: SubtaskSegment[] = [
  seg("s_001", 0, 1),
  seg("s_002", 1, 2.5),
  seg("s_003", 2.5, 4),
];

describe("selectSegmentIdByTime", () => {
  it("returns segment containing the time", () => {
    expect(selectSegmentIdByTime(SEGMENTS, 0.5)).toBe("s_001");
    expect(selectSegmentIdByTime(SEGMENTS, 1.0)).toBe("s_002");
    expect(selectSegmentIdByTime(SEGMENTS, 2.4)).toBe("s_002");
    expect(selectSegmentIdByTime(SEGMENTS, 2.5)).toBe("s_003");
  });

  it("returns null when no segment contains the time", () => {
    expect(selectSegmentIdByTime(SEGMENTS, -0.1)).toBeNull();
    expect(selectSegmentIdByTime(SEGMENTS, 10)).toBeNull();
  });

  it("returns null for empty segments", () => {
    expect(selectSegmentIdByTime([], 0)).toBeNull();
  });
});
