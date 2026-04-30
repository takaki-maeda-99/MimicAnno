import type { BoundaryCandidate, SubtaskSegment } from "../lib/manifest";
import BoundaryMarkerLayer from "./BoundaryMarkerLayer";

const TIMELINE_HEIGHT_PX = 80;
const PLAYHEAD_HEIGHT_PX = TIMELINE_HEIGHT_PX;
const SEGMENT_BAND_TOP = 0;
const SEGMENT_BAND_HEIGHT = 20;
const MARKER_BAND_TOP = 24;
const MARKER_BAND_HEIGHT = 32;
const SEGMENT_LABEL_MIN_WIDTH_PX = 30; // hide label on bands narrower than this

// Stable color palette (Tailwind-ish) — assigned per unique phase in
// first-appearance order. Reserved phases ("unlabeled" / "unknown") get
// muted gray. Keeps the same phase the same color across segments so the
// timeline reads as a label sequence at a glance.
const PHASE_PALETTE = [
  "#86efac", // green-300
  "#93c5fd", // blue-300
  "#fcd34d", // amber-300
  "#f9a8d4", // pink-300
  "#c4b5fd", // violet-300
  "#fdba74", // orange-300
  "#67e8f9", // cyan-300
  "#a3e635", // lime-400
  "#fda4af", // rose-300
  "#bef264", // lime-300
];
const RESERVED_PHASE_COLOR = "#d4d4d4";

function colorForPhase(phase: string, paletteAssignments: Map<string, string>): string {
  if (phase === "unlabeled" || phase === "unknown") return RESERVED_PHASE_COLOR;
  const cached = paletteAssignments.get(phase);
  if (cached !== undefined) return cached;
  const next = PHASE_PALETTE[paletteAssignments.size % PHASE_PALETTE.length];
  paletteAssignments.set(phase, next);
  return next;
}

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
  const paletteAssignments = new Map<string, string>();

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
      {segments.map((s) => {
        const x = scaleX(s.start_time);
        const w = Math.max(scaleX(s.end_time) - x, 1);
        const fill = colorForPhase(s.phase, paletteAssignments);
        const showLabel = w >= SEGMENT_LABEL_MIN_WIDTH_PX;
        return (
          <g key={s.segment_id}>
            <rect
              x={x}
              y={SEGMENT_BAND_TOP}
              width={w}
              height={SEGMENT_BAND_HEIGHT}
              fill={fill}
              stroke="#fff"
              strokeWidth={1}
            >
              <title>{`${s.segment_id} ${s.phase} ${s.start_time.toFixed(2)}-${s.end_time.toFixed(2)}s`}</title>
            </rect>
            {showLabel && (
              <text
                x={x + 4}
                y={SEGMENT_BAND_TOP + SEGMENT_BAND_HEIGHT / 2 + 4}
                fontSize={11}
                fontFamily="system-ui, sans-serif"
                fill="#111"
                pointerEvents="none"
                style={{ userSelect: "none" }}
              >
                {/* clip via SVG: width-based clipPath would be cleanest, but
                   we approximate by truncating to fit visually within the band */}
                {s.phase.length * 6.5 <= w - 6 ? s.phase : s.phase.slice(0, Math.max(1, Math.floor((w - 12) / 6.5))) + "…"}
              </text>
            )}
          </g>
        );
      })}
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
