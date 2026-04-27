import type { BoundaryCandidate } from "../lib/manifest";

const COLOR_FOR: Record<string, string> = {
  gripper_transition: "#e63946",
  eef_velocity_valley: "#1d4ed8",
  eef_acceleration_peak: "#16a34a",
  action_norm_change: "#f97316",
  episode_start: "#6b7280",
  episode_end: "#6b7280",
};
const FALLBACK_COLOR = "#999";

type Props = {
  widthPx: number;
  durationSec: number;
  candidates: BoundaryCandidate[];
  bandHeightPx: number;
  bandTopPx: number;
};

export default function BoundaryMarkerLayer({
  widthPx,
  durationSec,
  candidates,
  bandHeightPx,
  bandTopPx,
}: Props) {
  if (durationSec <= 0) return null;
  return (
    <g className="boundary-markers">
      {candidates.flatMap((c) => {
        const x = (c.time / durationSec) * widthPx;
        const sources = [...c.sources].sort();
        return sources.map((src, i) => {
          const y0 = bandTopPx + (i * bandHeightPx) / Math.max(sources.length, 1);
          const dy = bandHeightPx / Math.max(sources.length, 1);
          return (
            <line
              key={`${c.id}__${src}`}
              x1={x}
              x2={x}
              y1={y0}
              y2={y0 + dy}
              stroke={COLOR_FOR[src] ?? FALLBACK_COLOR}
              strokeWidth={2}
            >
              <title>{`${c.id} t=${c.time.toFixed(3)}s score=${c.score.toFixed(3)} ${src}`}</title>
            </line>
          );
        });
      })}
    </g>
  );
}
