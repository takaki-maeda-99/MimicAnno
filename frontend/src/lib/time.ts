export function timeToFrame(tSec: number, fps: number): number {
  return Math.round(tSec * fps);
}

export function frameToTime(frame: number, fps: number): number {
  return frame / fps;
}

export function clampTime(tSec: number, durationSec: number): number {
  if (tSec < 0) return 0;
  if (tSec > durationSec) return durationSec;
  return tSec;
}
