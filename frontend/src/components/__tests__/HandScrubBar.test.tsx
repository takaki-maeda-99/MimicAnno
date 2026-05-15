import { describe, it, expect, vi } from "vitest";
import { render, fireEvent } from "@testing-library/react";
import HandScrubBar from "../HandScrubBar";

describe("HandScrubBar", () => {
  it("returns null when widthPx=0", () => {
    const { container } = render(
      <HandScrubBar widthPx={0} totalFrames={100} currentFrame={0} onSeek={vi.fn()} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("returns null when totalFrames=0", () => {
    const { container } = render(
      <HandScrubBar widthPx={400} totalFrames={0} currentFrame={0} onSeek={vi.fn()} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders SVG with correct dimensions", () => {
    const { container } = render(
      <HandScrubBar widthPx={400} totalFrames={100} currentFrame={10} onSeek={vi.fn()} />,
    );
    const svg = container.querySelector("svg");
    expect(svg).not.toBeNull();
    expect(svg?.getAttribute("width")).toBe("400");
    expect(svg?.getAttribute("height")).toBe("24");
  });

  it("calls onSeek with correct frame on center click — totalFrames=100", () => {
    const onSeek = vi.fn();
    const { container } = render(
      <HandScrubBar widthPx={400} totalFrames={100} currentFrame={0} onSeek={onSeek} />,
    );
    const svg = container.querySelector("svg")!;
    vi.spyOn(svg, "getBoundingClientRect").mockReturnValue(
      { left: 0, top: 0, right: 400, bottom: 24, width: 400, height: 24, x: 0, y: 0, toJSON: () => ({}) } as DOMRect,
    );
    fireEvent.click(svg, { clientX: 200 });
    // frame = Math.min(Math.round((200/400)*100), 99) = 50
    expect(onSeek).toHaveBeenCalledWith(50);
  });

  it("calls onSeek with correct frame — totalFrames=5 (odd), center click rounds up", () => {
    const onSeek = vi.fn();
    const { container } = render(
      <HandScrubBar widthPx={200} totalFrames={5} currentFrame={0} onSeek={onSeek} />,
    );
    const svg = container.querySelector("svg")!;
    vi.spyOn(svg, "getBoundingClientRect").mockReturnValue(
      { left: 0, top: 0, right: 200, bottom: 24, width: 200, height: 24, x: 0, y: 0, toJSON: () => ({}) } as DOMRect,
    );
    fireEvent.click(svg, { clientX: 100 });
    // frame = Math.min(Math.round((100/200)*5), 4) = Math.round(2.5) = 3
    expect(onSeek).toHaveBeenCalledWith(3);
  });

  it("renders playhead line at correct x position", () => {
    const { container } = render(
      <HandScrubBar widthPx={400} totalFrames={100} currentFrame={25} onSeek={vi.fn()} />,
    );
    const line = container.querySelector("line")!;
    // x = (25/100) * 400 = 100
    expect(line.getAttribute("x1")).toBe("100");
    expect(line.getAttribute("x2")).toBe("100");
  });
});
