import { describe, it, expect, vi } from "vitest";
import { MANO_BONES, drawHandSkeleton } from "../handSkeleton";

function mkPoints(): [number, number][] {
  return Array.from({ length: 21 }, (_, i) => [i * 10, i * 5] as [number, number]);
}

function fakeCtx() {
  return {
    beginPath: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    stroke: vi.fn(),
    arc: vi.fn(),
    fill: vi.fn(),
    save: vi.fn(),
    restore: vi.fn(),
    set strokeStyle(_v: string) {},
    set fillStyle(_v: string) {},
    set lineWidth(_v: number) {},
    set globalAlpha(_v: number) {},
  } as unknown as CanvasRenderingContext2D;
}

describe("MANO_BONES", () => {
  it("has exactly 20 bones", () => {
    expect(MANO_BONES.length).toBe(20);
  });
  it("each bone references joints in 0..20", () => {
    for (const [a, b] of MANO_BONES) {
      expect(a).toBeGreaterThanOrEqual(0);
      expect(a).toBeLessThan(21);
      expect(b).toBeGreaterThanOrEqual(0);
      expect(b).toBeLessThan(21);
    }
  });
});

describe("drawHandSkeleton", () => {
  it("draws 20 bones (one moveTo+lineTo per bone) for 21 valid joints", () => {
    const ctx = fakeCtx();
    drawHandSkeleton({
      ctx,
      joints2d: mkPoints(),
      scaleX: 1,
      scaleY: 1,
      color: "rgb(0,220,60)",
      alpha: 0.95,
    });
    expect((ctx.moveTo as any).mock.calls.length).toBe(20);
    expect((ctx.lineTo as any).mock.calls.length).toBe(20);
    expect((ctx.arc as any).mock.calls.length).toBe(21);
  });

  it("scales coordinates by scaleX/scaleY", () => {
    const ctx = fakeCtx();
    drawHandSkeleton({
      ctx,
      joints2d: mkPoints(),
      scaleX: 0.5,
      scaleY: 0.25,
      color: "rgb(0,220,60)",
      alpha: 1,
    });
    // First bone is [0,1]: from (0,0) to (10,5) → scaled (0,0)→(5,1.25)
    const firstMoveTo = (ctx.moveTo as any).mock.calls[0];
    const firstLineTo = (ctx.lineTo as any).mock.calls[0];
    expect(firstMoveTo).toEqual([0, 0]);
    expect(firstLineTo).toEqual([5, 1.25]);
  });
});
