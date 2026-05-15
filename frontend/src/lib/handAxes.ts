/**
 * Project hand-frame XYZ axes into image space for canvas overlay.
 *
 * Convention:
 *   - euler_deg = ZYX intrinsic (matches scipy `as_euler('ZYX', degrees=True)`
 *     used in scripts/run_hand_estimation.py).
 *     R = Rz(yaw) · Ry(pitch) · Rx(roll) when applied to a column vector.
 *   - Camera frame: x right, y down, z forward (standard pinhole / OpenCV).
 *   - Pinhole projection: px = fx·X/Z + cx, py = fy·Y/Z + cy.
 *
 * Camera intrinsics are approximated: fx = fy = videoWidth, cx = W/2, cy = H/2
 * (≈ 53° horizontal FOV). Good enough for a sanity-check overlay; replace
 * with calibrated K when available.
 */

export type EulerDeg = { yaw: number; pitch: number; roll: number };
export type Vec3 = [number, number, number];

const DEG = Math.PI / 180;

function rotMatrix(e: EulerDeg): number[][] {
  const cz = Math.cos(e.yaw * DEG), sz = Math.sin(e.yaw * DEG);
  const cy = Math.cos(e.pitch * DEG), sy = Math.sin(e.pitch * DEG);
  const cx = Math.cos(e.roll * DEG), sx = Math.sin(e.roll * DEG);
  // R = Rz · Ry · Rx
  return [
    [cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx],
    [sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx],
    [-sy,     cy * sx,                cy * cx],
  ];
}

/**
 * OpenCV equidistant fisheye projection (k1..k4 = 0).
 * pipeline.py back-projects wrist depth through this same model, so we
 * must use it to round-trip.
 */
function project(
  pt: Vec3,
  fx: number, fy: number, cx: number, cy: number,
): { x: number; y: number; behind: boolean } {
  const X = pt[0], Y = pt[1], Z = pt[2];
  const r = Math.hypot(X, Y);
  if (Z <= 0 && r < 1e-9) return { x: NaN, y: NaN, behind: true };
  const theta = Math.atan2(r, Z);
  // Forward fisheye: u = fx * (X/r) * theta + cx
  if (r < 1e-9) return { x: cx, y: cy, behind: false };
  return {
    x: fx * (X / r) * theta + cx,
    y: fy * (Y / r) * theta + cy,
    behind: Z < 0 && theta > Math.PI / 2,
  };
}

export type AxisProjection = {
  origin: { x: number; y: number };
  tipX: { x: number; y: number };
  tipY: { x: number; y: number };
  tipZ: { x: number; y: number };
};

/**
 * Returns null if the hand origin is behind the camera.
 *
 * If `intrinsics` is supplied, uses it as fx/fy/cx/cy. Otherwise estimates
 * fx = fy = videoWidth, cx = W/2, cy = H/2 (≈ 53° FOV).
 */
export function projectHandAxes(opts: {
  cam_t: Vec3;
  euler_deg: EulerDeg;
  axisLengthM: number;
  videoWidth: number;
  videoHeight: number;
  intrinsics?: { fx: number; fy: number; cx: number; cy: number };
}): AxisProjection | null {
  const { cam_t, euler_deg, axisLengthM, videoWidth, videoHeight, intrinsics } = opts;
  const fx = intrinsics?.fx ?? videoWidth;
  const fy = intrinsics?.fy ?? videoWidth;
  const cx = intrinsics?.cx ?? videoWidth / 2;
  const cy = intrinsics?.cy ?? videoHeight / 2;

  const R = rotMatrix(euler_deg);
  const tip = (axis: Vec3): Vec3 => {
    const a: Vec3 = [
      R[0][0] * axis[0] + R[0][1] * axis[1] + R[0][2] * axis[2],
      R[1][0] * axis[0] + R[1][1] * axis[1] + R[1][2] * axis[2],
      R[2][0] * axis[0] + R[2][1] * axis[1] + R[2][2] * axis[2],
    ];
    return [
      cam_t[0] + axisLengthM * a[0],
      cam_t[1] + axisLengthM * a[1],
      cam_t[2] + axisLengthM * a[2],
    ];
  };

  const origin = project(cam_t, fx, fy, cx, cy);
  if (origin.behind) return null;
  const tx = project(tip([1, 0, 0]), fx, fy, cx, cy);
  const ty = project(tip([0, 1, 0]), fx, fy, cx, cy);
  const tz = project(tip([0, 0, 1]), fx, fy, cx, cy);

  return {
    origin: { x: origin.x, y: origin.y },
    tipX: { x: tx.x, y: tx.y },
    tipY: { x: ty.x, y: ty.y },
    tipZ: { x: tz.x, y: tz.y },
  };
}

export type DrawAxisOpts = {
  ctx: CanvasRenderingContext2D;
  proj: AxisProjection;
  scaleX: number;   // displayed_width / videoWidth
  scaleY: number;   // displayed_height / videoHeight
  lineWidth?: number;
  alpha?: number;
};

export function drawAxes({
  ctx, proj, scaleX, scaleY, lineWidth = 2, alpha = 0.9,
}: DrawAxisOpts): void {
  const ox = proj.origin.x * scaleX;
  const oy = proj.origin.y * scaleY;
  const draw = (tip: { x: number; y: number }, color: string) => {
    ctx.beginPath();
    ctx.strokeStyle = color;
    ctx.lineWidth = lineWidth;
    ctx.globalAlpha = alpha;
    ctx.moveTo(ox, oy);
    ctx.lineTo(tip.x * scaleX, tip.y * scaleY);
    ctx.stroke();
  };
  draw(proj.tipX, "#ff3030"); // X red
  draw(proj.tipY, "#30c030"); // Y green
  draw(proj.tipZ, "#3060ff"); // Z blue
  // Origin dot
  ctx.beginPath();
  ctx.fillStyle = "#ffffff";
  ctx.globalAlpha = 1.0;
  ctx.arc(ox, oy, lineWidth + 1, 0, Math.PI * 2);
  ctx.fill();
}
