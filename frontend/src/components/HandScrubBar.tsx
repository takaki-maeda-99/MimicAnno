import type { MouseEvent } from "react";

type Props = {
  widthPx: number;
  totalFrames: number;
  currentFrame: number;
  onSeek: (frame: number) => void;
};

export default function HandScrubBar({ widthPx, totalFrames, currentFrame, onSeek }: Props) {
  if (widthPx <= 0 || totalFrames <= 0) return null;

  const x = (currentFrame / totalFrames) * widthPx;

  function handleClick(e: MouseEvent<SVGSVGElement>) {
    const rect = e.currentTarget.getBoundingClientRect();
    const clickX = e.clientX - rect.left;
    const frame = Math.min(
      Math.round((clickX / widthPx) * totalFrames),
      totalFrames - 1,
    );
    onSeek(frame);
  }

  return (
    <svg
      width={widthPx}
      height={24}
      style={{ display: "block", background: "var(--bg-surface)", cursor: "crosshair", maxWidth: "100%" }}
      onClick={handleClick}
    >
      <line x1={x} y1={0} x2={x} y2={24} stroke="#f1f5f9" strokeWidth={1.5} pointerEvents="none" />
    </svg>
  );
}
