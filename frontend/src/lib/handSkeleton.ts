/**
 * 21-joint hand skeleton drawing helper for canvas overlays.
 *
 * Bone topology: wrist-rooted, 5 fingers, 4 bones each = 20 bones total.
 * Joint indices follow the MediaPipe Hand Landmarker convention (0 = wrist,
 * 1-4 thumb, 5-8 index, 9-12 middle, 13-16 ring, 17-20 pinky).
 */

export const HAND_BONES: readonly (readonly [number, number])[] = [
  [0, 1], [1, 2], [2, 3], [3, 4],          // thumb
  [0, 5], [5, 6], [6, 7], [7, 8],          // index
  [0, 9], [9, 10], [10, 11], [11, 12],     // middle
  [0, 13], [13, 14], [14, 15], [15, 16],   // ring
  [0, 17], [17, 18], [18, 19], [19, 20],   // pinky
];

export function drawHandSkeleton(args: {
  ctx: CanvasRenderingContext2D;
  joints2d: readonly [number, number][];
  scaleX: number;
  scaleY: number;
  color: string;
  alpha: number;
}): void {
  const { ctx, joints2d, scaleX, scaleY, color, alpha } = args;
  if (joints2d.length < 21) return;
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.strokeStyle = color;
  ctx.fillStyle = color;
  ctx.lineWidth = 2;

  for (const [a, b] of HAND_BONES) {
    const [ax, ay] = joints2d[a];
    const [bx, by] = joints2d[b];
    ctx.beginPath();
    ctx.moveTo(ax * scaleX, ay * scaleY);
    ctx.lineTo(bx * scaleX, by * scaleY);
    ctx.stroke();
  }

  for (let i = 0; i < 21; i++) {
    const [x, y] = joints2d[i];
    ctx.beginPath();
    ctx.arc(x * scaleX, y * scaleY, 3, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.restore();
}
