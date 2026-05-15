import type { MouseEvent } from "react";
import type { HandFrameEntry, HandSignalsDoc } from "../lib/handsClient";

const HEIGHT = 64;
const PAD_V = 4;
const COLORS = { x: "#ef4444", y: "#22c55e", z: "#60a5fa" } as const;

type DataPoint = { cam_t: [number, number, number]; depth_ok: boolean } | null;

function extractSeries(
  signals: HandSignalsDoc,
  side: "right" | "left",
  totalFrames: number,
): DataPoint[] {
  const pts: DataPoint[] = [];
  for (let i = 0; i < totalFrames; i++) {
    const key = `frame_${String(i).padStart(6, "0")}`;
    const entry = signals[key] as HandFrameEntry | undefined;
    const hand = entry?.[side] ?? null;
    pts.push(hand ? { cam_t: hand.cam_t, depth_ok: hand.depth_ok } : null);
  }
  return pts;
}

function robustRange(pts: DataPoint[]): { minVal: number; maxVal: number } {
  // Use only depth_ok=true values to avoid outliers from HaMeR pseudo-metric frames.
  const vals: number[] = [];
  for (const pt of pts) {
    if (!pt || !pt.depth_ok) continue;
    for (const v of pt.cam_t) vals.push(v);
  }
  if (vals.length === 0) {
    // Fallback: use all frames if no depth_ok=true data
    for (const pt of pts) {
      if (!pt) continue;
      for (const v of pt.cam_t) vals.push(v);
    }
  }
  if (vals.length === 0) return { minVal: 0, maxVal: 1 };
  vals.sort((a, b) => a - b);
  const p2 = vals[Math.floor(vals.length * 0.02)];
  const p98 = vals[Math.ceil(vals.length * 0.98 - 1)];
  const pad = (p98 - p2) * 0.1 || 0.01;
  return { minVal: p2 - pad, maxVal: p98 + pad };
}

function buildPaths(
  pts: DataPoint[],
  axisIdx: 0 | 1 | 2,
  minVal: number,
  maxVal: number,
  widthPx: number,
): { solid: string; dashed: string } {
  const n = pts.length;
  const range = maxVal - minVal || 1;
  let solidD = "";
  let dashedD = "";
  let inSolid = false;
  let inDashed = false;

  for (let i = 0; i < n; i++) {
    const pt = pts[i];
    if (!pt) {
      inSolid = false;
      inDashed = false;
      continue;
    }
    const x = ((n <= 1 ? 0 : i / (n - 1)) * widthPx).toFixed(1);
    const rawY = PAD_V + (1 - (pt.cam_t[axisIdx] - minVal) / range) * (HEIGHT - PAD_V * 2);
    const y = Math.max(0, Math.min(HEIGHT, rawY)).toFixed(1);

    if (pt.depth_ok) {
      solidD += inSolid ? ` L ${x} ${y}` : ` M ${x} ${y}`;
      inSolid = true;
      inDashed = false;
    } else {
      dashedD += inDashed ? ` L ${x} ${y}` : ` M ${x} ${y}`;
      inDashed = true;
      inSolid = false;
    }
  }
  return { solid: solidD.trim(), dashed: dashedD.trim() };
}

type Props = {
  signals: HandSignalsDoc;
  side: "right" | "left";
  widthPx: number;
  totalFrames: number;
  currentFrame: number;
  onSeek: (frame: number) => void;
};

export default function HandSignalGraph({
  signals,
  side,
  widthPx,
  totalFrames,
  currentFrame,
  onSeek,
}: Props) {
  if (widthPx <= 0 || totalFrames <= 0) return null;

  const pts = extractSeries(signals, side, totalFrames);
  const { minVal, maxVal } = robustRange(pts);
  const axes = [0, 1, 2] as const;
  const playheadX = ((totalFrames <= 1 ? 0 : currentFrame / (totalFrames - 1)) * widthPx).toFixed(1);

  function handleClick(e: MouseEvent<SVGSVGElement>) {
    const rect = e.currentTarget.getBoundingClientRect();
    const frame = Math.min(
      Math.round(((e.clientX - rect.left) / widthPx) * (totalFrames - 1)),
      totalFrames - 1,
    );
    onSeek(frame);
  }

  return (
    <div>
      <div style={{ fontSize: 10, color: "var(--text-muted)", display: "flex", gap: 6, marginBottom: 1 }}>
        <span style={{ color: COLORS.x }}>x</span>
        <span style={{ color: COLORS.y }}>y</span>
        <span style={{ color: COLORS.z }}>z</span>
        <span>{side === "right" ? "右手" : "左手"} cam_t [m]</span>
      </div>
      <svg
        width={widthPx}
        height={HEIGHT}
        style={{ display: "block", background: "var(--bg-surface)", cursor: "crosshair" }}
        onClick={handleClick}
      >
        {axes.map((axisIdx) => {
          const color = COLORS[axisIdx === 0 ? "x" : axisIdx === 1 ? "y" : "z"];
          const { solid, dashed } = buildPaths(pts, axisIdx, minVal, maxVal, widthPx);
          return (
            <g key={axisIdx}>
              {solid && (
                <path d={solid} stroke={color} strokeWidth={1.2} fill="none" opacity={0.9} />
              )}
              {dashed && (
                <path
                  d={dashed}
                  stroke={color}
                  strokeWidth={1.2}
                  fill="none"
                  strokeDasharray="3 3"
                  opacity={0.45}
                />
              )}
            </g>
          );
        })}
        <line
          x1={playheadX}
          y1={0}
          x2={playheadX}
          y2={HEIGHT}
          stroke="#f1f5f9"
          strokeWidth={1}
          pointerEvents="none"
        />
      </svg>
    </div>
  );
}
