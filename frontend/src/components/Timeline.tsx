import type { BoundaryCandidate, SubtaskSegment } from "../lib/manifest";
import BoundaryMarkerLayer from "./BoundaryMarkerLayer";

const TIMELINE_HEIGHT_PX = 80;
const PLAYHEAD_HEIGHT_PX = TIMELINE_HEIGHT_PX;
const SEGMENT_BAND_TOP = 0;
const SEGMENT_BAND_HEIGHT = 20;
const MARKER_BAND_TOP = 24;
const MARKER_BAND_HEIGHT = 32;

type Props = {
  widthPx: number;
  durationSec: number;
  currentTimeSec: number;
  candidates: BoundaryCandidate[];
  segments: SubtaskSegment[];
  onSeek: (tSec: number) => void;
};

export default function Timeline({
  widthPx,
  durationSec,
  currentTimeSec,
  candidates,
  segments,
  onSeek,
}: Props) {
  if (widthPx === 0 || durationSec <= 0) return null;
  const scaleX = (t: number) => (t / durationSec) * widthPx;

  return (
    <svg
      width={widthPx}
      height={TIMELINE_HEIGHT_PX}
      style={{ display: "block", background: "#f5f5f4", cursor: "crosshair" }}
      onClick={(e) => {
        const rect = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
        const x = e.clientX - rect.left;
        onSeek((x / widthPx) * durationSec);
      }}
    >
      {segments.map((s, i) => (
        <rect
          key={s.segment_id}
          x={scaleX(s.start_time)}
          y={SEGMENT_BAND_TOP}
          width={Math.max(scaleX(s.end_time) - scaleX(s.start_time), 1)}
          height={SEGMENT_BAND_HEIGHT}
          fill={i % 2 === 0 ? "#e5e7eb" : "#d1d5db"}
        >
          <title>{`${s.segment_id} ${s.phase} ${s.start_time.toFixed(2)}-${s.end_time.toFixed(2)}s`}</title>
        </rect>
      ))}
      <BoundaryMarkerLayer
        widthPx={widthPx}
        durationSec={durationSec}
        candidates={candidates}
        bandTopPx={MARKER_BAND_TOP}
        bandHeightPx={MARKER_BAND_HEIGHT}
      />
      <line
        x1={scaleX(currentTimeSec)}
        x2={scaleX(currentTimeSec)}
        y1={0}
        y2={PLAYHEAD_HEIGHT_PX}
        stroke="#111"
        strokeWidth={1.5}
        pointerEvents="none"
      />
    </svg>
  );
}
