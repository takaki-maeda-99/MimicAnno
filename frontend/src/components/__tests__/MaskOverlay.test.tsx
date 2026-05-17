/** U-A4 FT3-FT7: MaskOverlay component tests. */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import MaskOverlay from "../MaskOverlay";
import type { MasksMeta } from "../../lib/masksClient";

const META: MasksMeta = {
  run_set: "rs1",
  canonical: "ep0",
  frame_count: 5,
  shape: [240, 320],
  tracks: [
    {
      track_id: "obj:object:block:0",
      prompt: "block",
      role: "object",
      color: "#1f77b4",
      first_frame: 0,
      last_frame: 4,
    },
    {
      track_id: "obj:target:bin:0",
      prompt: "bin",
      role: "target",
      color: "#ff7f0e",
      first_frame: 0,
      last_frame: 4,
    },
  ],
};

beforeEach(() => {
  // Default: fetch returns 204 (no PNG for the frame)
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(null, { status: 204 })) as typeof fetch,
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

// FT3a: returns null when meta is null
describe("MaskOverlay", () => {
  it("FT3a: renders nothing when meta is null", () => {
    const { container } = render(
      <MaskOverlay
        apiBase=""
        runName="ep0"
        runSet="rs1"
        currentFrame={0}
        meta={null}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  // FT3b: returns null when frame_count is 0
  it("FT3b: renders nothing when frame_count is 0", () => {
    const emptyMeta: MasksMeta = { ...META, frame_count: 0, tracks: [] };
    const { container } = render(
      <MaskOverlay
        apiBase=""
        runName="ep0"
        runSet="rs1"
        currentFrame={0}
        meta={emptyMeta}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  // FT4: canvas is rendered with correct data-testid
  it("FT4: renders canvas with data-testid='mask-overlay-canvas'", () => {
    render(
      <MaskOverlay
        apiBase=""
        runName="ep0"
        runSet="rs1"
        currentFrame={0}
        meta={META}
      />,
    );
    expect(screen.getByTestId("mask-overlay-canvas")).toBeDefined();
  });

  // FT5: controls panel is rendered (alpha slider present)
  it("FT5: renders controls with alpha slider", () => {
    render(
      <MaskOverlay
        apiBase=""
        runName="ep0"
        runSet="rs1"
        currentFrame={0}
        meta={META}
      />,
    );
    expect(screen.getByTestId("mask-overlay-controls")).toBeDefined();
    expect(screen.getByTestId("mask-alpha-slider")).toBeDefined();
  });

  // FT6: color swatches rendered for each track
  it("FT6: renders color swatch for each track", () => {
    render(
      <MaskOverlay
        apiBase=""
        runName="ep0"
        runSet="rs1"
        currentFrame={0}
        meta={META}
      />,
    );
    for (const t of META.tracks) {
      expect(screen.getByTestId(`mask-color-swatch-${t.track_id}`)).toBeDefined();
    }
  });

  // FT7: frame fetch URL uses correct path
  it("FT7: fetches from correct mask PNG URL on mount", async () => {
    render(
      <MaskOverlay
        apiBase="http://localhost:5173"
        runName="ep0"
        runSet="rs1"
        currentFrame={3}
        meta={META}
      />,
    );
    // Wait for debounce (100ms) + fetch
    await new Promise((r) => setTimeout(r, 150));
    const calls = vi.mocked(fetch).mock.calls;
    const fetchedUrls = calls.map((c) => String(c[0]));
    expect(
      fetchedUrls.some((u) =>
        u.includes("/api/runs/ep0/masks/3") && u.includes("run_set=rs1"),
      ),
    ).toBe(true);
  });
});
