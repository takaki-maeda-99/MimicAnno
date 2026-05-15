/**
 * Phase 5 B r2 T12 — draggable boundary ruler.
 *
 * Renders a 32px-high horizontal bar with vertical handles at each inner
 * boundary (i.e. segments[1..n-1].segment_id = boundary id). The first
 * and last segment endpoints are NOT shown as handles — they are timeline
 * edges, not boundaries.
 *
 * Drag contract:
 *   - Capture pointer on pointerDown; snapshot getBoundingClientRect once.
 *   - On pointerMove: compute candidate new_frame from x offset, clamp to
 *     [left.start_frame+1, right.end_frame].
 *   - On pointerUp/pointerCancel: emit onDragCommit(boundaryId, newFrame)
 *     only if newFrame differs from current boundary.
 *   - ←/→ keyboard nudge (1 frame) is emitted as a commit immediately.
 *
 * pendingPatch: when truthy, the bar dims and pointer events are disabled.
 *
 * NOTE: drag state is held in a useRef (not useState) so that pointer event
 * handlers — which close over the ref — always see the current value without
 * waiting for a React re-render cycle between events. Visual preview is
 * managed via a separate useState that triggers the re-render for handle
 * repositioning.
 */
import { useRef, useState } from "react";
import type { SubtaskSegment } from "../lib/manifest";

const RULER_HEIGHT_PX = 32;
const HANDLE_WIDTH_PX = 8;
const MIN_FRAME_PX = 4;

type Props = {
  widthPx: number;
  segments: SubtaskSegment[];
  fps: number;
  pendingPatch: boolean;
  onDragCommit: (boundaryId: string, newFrame: number) => void;
};

type DragRef = {
  boundaryId: string;
  leftStartFrame: number;
  rightEndFrame: number;
  currentFrame: number;
  totalFrames: number;
  rectLeft: number;
  rectWidth: number;
};

function clampFrame(
  newFrame: number,
  leftStartFrame: number,
  rightEndFrame: number,
  totalFrames: number,
): number | null {
  if (!Number.isFinite(newFrame)) return null;
  if (newFrame < 0 || newFrame >= totalFrames) return null;
  if (newFrame <= leftStartFrame) return null;
  if (newFrame > rightEndFrame) return null;
  return newFrame;
}

export default function TimelineRuler({
  widthPx,
  segments,
  fps: _fps,
  pendingPatch,
  onDragCommit,
}: Props) {
  // Drag state in ref: always current, no re-render lag between pointer events.
  const dragRef = useRef<DragRef | null>(null);
  // Preview frame per boundary_id: triggers re-render to reposition handles.
  const [previewFrames, setPreviewFrames] = useState<Record<string, number>>({});
  const rulerRef = useRef<HTMLDivElement>(null);

  if (widthPx === 0 || segments.length < 2) return null;

  const totalFrames = segments[segments.length - 1].end_frame + 1;
  const pxPerFrame = widthPx / totalFrames;
  const tooNarrow = pxPerFrame < MIN_FRAME_PX;

  const innerBoundaries = segments.slice(1);

  function frameToX(frame: number): number {
    return (frame / totalFrames) * widthPx;
  }

  function xToFrame(clientX: number, rectLeft: number, rectWidth: number): number {
    const rel = Math.max(0, Math.min(clientX - rectLeft, rectWidth - 1));
    return Math.round((rel / rectWidth) * totalFrames);
  }

  function onPointerDown(
    e: React.PointerEvent<HTMLDivElement>,
    seg: SubtaskSegment,
    leftSeg: SubtaskSegment,
  ) {
    if (pendingPatch || tooNarrow) return;
    e.preventDefault();
    const el = e.currentTarget as HTMLDivElement;
    if (el.setPointerCapture) el.setPointerCapture(e.pointerId);
    // Use widthPx (prop) as the ruler width — avoids getBoundingClientRect
    // for width, which returns 0 in jsdom. Only need left offset from DOM.
    const left = rulerRef.current!.getBoundingClientRect().left;
    dragRef.current = {
      boundaryId: seg.segment_id,
      leftStartFrame: leftSeg.start_frame,
      rightEndFrame: seg.end_frame,
      currentFrame: seg.start_frame,
      totalFrames,
      rectLeft: left,
      rectWidth: widthPx,
    };
  }

  function onPointerMove(e: React.PointerEvent<HTMLDivElement>) {
    const d = dragRef.current;
    if (!d) return;
    const candidate = xToFrame(e.clientX, d.rectLeft, d.rectWidth);
    const clamped = clampFrame(candidate, d.leftStartFrame, d.rightEndFrame, d.totalFrames);
    if (clamped !== null) {
      setPreviewFrames((prev) => ({ ...prev, [d.boundaryId]: clamped }));
    }
  }

  function onPointerUp() {
    const d = dragRef.current;
    if (!d) return;
    dragRef.current = null;
    const previewFrame = previewFrames[d.boundaryId] ?? d.currentFrame;
    setPreviewFrames((prev) => {
      const next = { ...prev };
      delete next[d.boundaryId];
      return next;
    });
    if (previewFrame !== d.currentFrame) {
      onDragCommit(d.boundaryId, previewFrame);
    }
  }

  function onKeyDown(
    e: React.KeyboardEvent<HTMLDivElement>,
    seg: SubtaskSegment,
    leftSeg: SubtaskSegment,
  ) {
    if (pendingPatch || tooNarrow) return;
    let delta = 0;
    if (e.key === "ArrowLeft") delta = -1;
    else if (e.key === "ArrowRight") delta = 1;
    else return;
    e.preventDefault();
    const newFrame = seg.start_frame + delta;
    const clamped = clampFrame(newFrame, leftSeg.start_frame, seg.end_frame, totalFrames);
    if (clamped !== null && clamped !== seg.start_frame) {
      onDragCommit(seg.segment_id, clamped);
    }
  }

  return (
    <div
      ref={rulerRef}
      style={{
        position: "relative",
        width: widthPx,
        height: RULER_HEIGHT_PX,
        background: "#e7e5e4",
        opacity: pendingPatch ? 0.4 : 1,
        flexShrink: 0,
        userSelect: "none",
      }}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
    >
      {innerBoundaries.map((seg, i) => {
        const leftSeg = segments[i];
        const isDragging = dragRef.current?.boundaryId === seg.segment_id;
        const displayFrame = previewFrames[seg.segment_id] ?? seg.start_frame;
        const x = frameToX(displayFrame) - HANDLE_WIDTH_PX / 2;

        return (
          <div
            key={seg.segment_id}
            role="slider"
            aria-label={`boundary ${seg.segment_id}`}
            aria-valuenow={displayFrame}
            aria-valuemin={leftSeg.start_frame + 1}
            aria-valuemax={seg.end_frame}
            tabIndex={pendingPatch || tooNarrow ? -1 : 0}
            style={{
              position: "absolute",
              left: x,
              top: 0,
              width: HANDLE_WIDTH_PX,
              height: RULER_HEIGHT_PX,
              background: isDragging ? "#2563eb" : "#78716c",
              cursor: pendingPatch || tooNarrow ? "default" : "ew-resize",
              touchAction: "none",
            }}
            onPointerDown={(e) => onPointerDown(e, seg, leftSeg)}
            onKeyDown={(e) => onKeyDown(e, seg, leftSeg)}
          />
        );
      })}
    </div>
  );
}
